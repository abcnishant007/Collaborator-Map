import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from .normalization import normalize_text


@lru_cache
def _load_rows() -> list[dict]:
    path = Path(__file__).resolve().parents[2] / "world_universities_and_domains.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache
def _by_name() -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for row in _load_rows():
        name = normalize_text(row.get("name", ""))
        if name and name not in index:
            index[name] = row
    return index


def infer_country_for_institution(institution_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not institution_name:
        return None, None
    row = _by_name().get(normalize_text(institution_name))
    if not row:
        return None, None
    return row.get("alpha_two_code"), row.get("country")

