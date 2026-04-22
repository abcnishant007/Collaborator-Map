import json
import csv
import threading
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .normalization import normalize_text

_COORD_CACHE_LOCK = threading.Lock()


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache
def _load_university_coordinate_rows() -> List[dict]:
    candidates = [
        _repo_root() / "more_data" / "institution_coordinate_cache.csv",
        _repo_root() / "more_data" / "universities_with_coordinates.csv",
        _repo_root() / "more_data" / "Unis_with_lat_long.csv",
    ]
    rows: List[dict] = []
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows.extend(list(reader))
    return rows


@lru_cache
def _university_coordinates_index() -> Dict[str, Tuple[float, float, Optional[str]]]:
    index: Dict[str, Tuple[float, float, Optional[str]]] = {}
    for row in _load_university_coordinate_rows():
        inst = normalize_text(row.get("Institution", ""))
        if not inst:
            continue
        try:
            lat = float(row.get("Latitude", ""))
            lon = float(row.get("Longitude", ""))
        except (TypeError, ValueError):
            continue
        location = row.get("Location")
        if inst not in index:
            index[inst] = (lat, lon, location)
    return index


@lru_cache
def _load_city_rows() -> List[dict]:
    path = _repo_root() / "cities_lat_long.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache
def _cities_by_country() -> Dict[str, List[Tuple[str, float, float]]]:
    grouped: Dict[str, List[Tuple[str, float, float]]] = {}
    for row in _load_city_rows():
        country_code = (row.get("country") or "").strip().upper()
        city = normalize_text(row.get("name", ""))
        if not country_code or not city or len(city) < 4:
            continue
        try:
            lat = float(row.get("lat", ""))
            lon = float(row.get("lng", ""))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(country_code, []).append((city, lat, lon))

    for country, values in grouped.items():
        grouped[country] = sorted(values, key=lambda item: len(item[0]), reverse=True)
    return grouped


def infer_local_coordinates(
    institution_name: Optional[str],
    country_code: Optional[str],
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not institution_name:
        return None, None, None

    normalized = normalize_text(institution_name)
    if not normalized:
        return None, None, None

    uni_row = _university_coordinates_index().get(normalized)
    if uni_row:
        lat, lon, _location = uni_row
        return lat, lon, "local_university_csv"

    city_name, city_lat, city_lon, _ = infer_city_for_institution(institution_name, country_code)
    if city_lat is not None and city_lon is not None:
        return city_lat, city_lon, "local_city_csv"

    return None, None, None


def infer_city_for_institution(
    institution_name: Optional[str],
    country_code: Optional[str],
) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[str]]:
    if not institution_name:
        return None, None, None, None
    normalized = normalize_text(institution_name)
    if not normalized:
        return None, None, None, None
    cc = (country_code or "").strip().upper()
    if not cc:
        return None, None, None, None

    city_rows = _cities_by_country().get(cc, [])
    padded = f" {normalized} "
    for city, lat, lon in city_rows:
        if f" {city} " in padded:
            return city, lat, lon, "local_city_csv"
    return None, None, None, None


def append_coordinate_cache_row(
    institution_name: str,
    country_code: Optional[str],
    lat: float,
    lon: float,
    source: str = "nominatim",
) -> None:
    if not institution_name:
        return
    normalized = normalize_text(institution_name)
    if not normalized:
        return
    existing = _university_coordinates_index().get(normalized)
    if existing:
        return

    cache_path = _repo_root() / "more_data" / "institution_coordinate_cache.csv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not cache_path.exists()

    with _COORD_CACHE_LOCK:
        with cache_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if is_new_file:
                writer.writerow(["Institution", "CountryCode", "Latitude", "Longitude", "Source"])
            writer.writerow([institution_name, (country_code or "").upper(), f"{lat:.8f}", f"{lon:.8f}", source])

    _load_university_coordinate_rows.cache_clear()
    _university_coordinates_index.cache_clear()
