from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .config import get_settings


def canonical_author_id(author_id: Optional[str]) -> str:
    if not author_id:
        return ""
    author_id = str(author_id).strip()
    if author_id.startswith("https://openalex.org/"):
        return author_id
    if author_id.startswith("A"):
        return f"https://openalex.org/{author_id}"
    return author_id


class OpenAlexClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.Client(timeout=30.0)

    def _params(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        merged = dict(params or {})
        if self.settings.openalex_mailto:
            merged["mailto"] = self.settings.openalex_mailto
        if self.settings.openalex_api_key:
            merged["api_key"] = self.settings.openalex_api_key
        return merged

    def autocomplete_authors(self, query: str, per_page: int = 10) -> List[Dict[str, Any]]:
        url = f"{self.settings.openalex_base_url}/autocomplete/authors"
        _ = per_page
        response = self.client.get(url, params=self._params({"q": query}))
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])

    def search_authors(self, query: str, per_page: int = 10) -> List[Dict[str, Any]]:
        url = f"{self.settings.openalex_base_url}/authors"
        response = self.client.get(url, params=self._params({"search": query, "per-page": per_page}))
        response.raise_for_status()
        payload = response.json()
        return payload.get("results", [])

    def fetch_author(self, author_id: str) -> Dict[str, Any]:
        canonical = canonical_author_id(author_id)
        url = canonical.replace("https://openalex.org", self.settings.openalex_base_url)
        response = self.client.get(url, params=self._params())
        response.raise_for_status()
        return response.json()

    def fetch_works_for_author(self, author_id: str) -> List[Dict[str, Any]]:
        canonical = canonical_author_id(author_id)
        url = f"{self.settings.openalex_base_url}/works"
        params = self._params(
            {
                "filter": f"authorships.author.id:{canonical}",
                "per-page": self.settings.openalex_per_page,
                "cursor": "*",
                "sort": "publication_year:desc",
            }
        )
        works: List[Dict[str, Any]] = []
        page = 0
        while True:
            page += 1
            if page > self.settings.openalex_max_work_pages:
                break
            response = self.client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])
            works.extend(results)
            next_cursor = (payload.get("meta") or {}).get("next_cursor")
            if not next_cursor:
                break
            params["cursor"] = next_cursor
        return works

    def close(self) -> None:
        self.client.close()
