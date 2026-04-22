import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app.config import get_settings
from server.app.db import init_db
from server.app.main import app
from server.app.openalex import canonical_author_id


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_file = tempfile.NamedTemporaryFile(prefix="collab_map_test_", suffix=".db", delete=False)
        db_file.close()
        os.environ["DATABASE_URL"] = f"sqlite:///{db_file.name}"
        get_settings.cache_clear()
        init_db()
        cls.client = TestClient(app)
        cls.focal_id = "https://openalex.org/AFOCAL"

    @classmethod
    def tearDownClass(cls):
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "", 1)
            if os.path.exists(db_path):
                os.remove(db_path)

    def _mock_focal_author(self):
        return {
            "id": self.focal_id,
            "display_name": "Focal Researcher",
            "works_count": 12,
            "cited_by_count": 345,
            "ids": {"orcid": "https://orcid.org/0000-0000-0000-0001"},
            "last_known_institutions": [
                {
                    "id": "https://openalex.org/I999",
                    "display_name": "ETH Zurich",
                    "country_code": "CH",
                    "geo": {"country": "Switzerland", "country_code": "CH", "latitude": 47.37, "longitude": 8.54},
                }
            ],
        }

    def _mock_works(self):
        return [
            {
                "id": "https://openalex.org/W1",
                "publication_year": 2024,
                "authorships": [
                    {
                        "author": {"id": self.focal_id, "display_name": "Focal Researcher"},
                        "institutions": [
                            {
                                "id": "https://openalex.org/I999",
                                "display_name": "ETH Zurich",
                                "country_code": "CH",
                                "geo": {"country": "Switzerland", "latitude": 47.37, "longitude": 8.54},
                            }
                        ],
                    },
                    {
                        "author": {"id": "https://openalex.org/ACO1", "display_name": "Co Author"},
                        "institutions": [
                            {
                                "id": "https://openalex.org/I100",
                                "display_name": "MIT",
                                "country_code": "US",
                                "geo": {"country": "United States", "latitude": 42.36, "longitude": -71.09},
                            }
                        ],
                    },
                    {
                        "author": {"id": None, "display_name": "Missing Id Author"},
                        "institutions": [],
                    },
                ],
            }
        ]

    def test_canonical_author_id_handles_none(self):
        self.assertEqual(canonical_author_id(None), "")
        self.assertEqual(canonical_author_id("A123"), "https://openalex.org/A123")

    def test_pipeline_autocomplete_select_and_map_snapshot(self):
        autocomplete_rows = [
            {
                "id": self.focal_id,
                "display_name": "Focal Researcher",
                "hint": "ETH Zurich, Switzerland",
                "works_count": 12,
                "cited_by_count": 345,
            }
        ]
        with patch("server.app.openalex.OpenAlexClient.autocomplete_authors", return_value=autocomplete_rows):
            response = self.client.get("/api/autocomplete/authors", params={"q": "foca"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["results"]), 1)

        with (
            patch("server.app.openalex.OpenAlexClient.fetch_author", return_value=self._mock_focal_author()),
            patch("server.app.openalex.OpenAlexClient.fetch_works_for_author", return_value=self._mock_works()),
        ):
            select_response = self.client.post("/api/focal/select", json={"openalex_author_id": self.focal_id})
            self.assertEqual(select_response.status_code, 200)

            map_response = self.client.get(
                "/api/map",
                params={"focal_author_id": self.focal_id, "force_refresh": "true"},
            )
            self.assertEqual(map_response.status_code, 200)
            snapshot = map_response.json()
            self.assertEqual(snapshot["summary"]["unique_collaborators"], 1)
            self.assertGreaterEqual(len(snapshot["blobs"]), 1)
            self.assertEqual(snapshot["blobs"][0]["people"][0]["display_name"], "Co Author")


if __name__ == "__main__":
    unittest.main()

