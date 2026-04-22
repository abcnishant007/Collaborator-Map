from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import get_settings, resolve_openrouter_cheap_model, resolve_openrouter_model
from .db import utc_now_iso
from .normalization import normalize_institution_key, normalize_text
from .openalex import OpenAlexClient, canonical_author_id
from .university_reference import (
    append_coordinate_cache_row,
    infer_country_for_institution,
    infer_city_for_institution,
    infer_local_coordinates,
)

logger = logging.getLogger(__name__)


def execute_write_with_retry(conn: sqlite3.Connection, sql: str, params: tuple, retries: int = 3) -> None:
    attempt = 0
    while True:
        try:
            conn.execute(sql, params)
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            attempt += 1
            message = str(exc).lower()
            if "database is locked" not in message or attempt > retries:
                raise
            time.sleep(0.08 * attempt)


def choose_preferred_link(
    website_url: Optional[str],
    google_scholar_url: Optional[str],
    orcid_url: Optional[str],
    openalex_url: str,
) -> Tuple[str, List[str]]:
    available: List[str] = []
    for candidate in [website_url, google_scholar_url, orcid_url, openalex_url]:
        if candidate and candidate not in available:
            available.append(candidate)
    preferred = website_url or google_scholar_url or orcid_url or openalex_url
    return preferred, available


def recency_bucket(last_year: Optional[int]) -> str:
    if not last_year:
        return "unknown"
    year_now = datetime.now(timezone.utc).year
    delta = year_now - last_year
    if delta <= 2:
        return "recent"
    if delta <= 5:
        return "warm"
    return "older"


def parse_hint(hint: str) -> Tuple[Optional[str], Optional[str]]:
    if not hint:
        return None, None
    parts = [chunk.strip() for chunk in hint.split(",") if chunk.strip()]
    if not parts:
        return None, None
    affiliation = parts[0]
    country = parts[-1] if len(parts) > 1 else None
    return affiliation, country


def author_search_row_to_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    last_institutions = row.get("last_known_institutions") or []
    primary_inst = last_institutions[0] if last_institutions else {}
    geo = primary_inst.get("geo") or {}
    ids = row.get("ids") or {}
    return {
        "id": row.get("id"),
        "display_name": row.get("display_name"),
        "affiliation": primary_inst.get("display_name"),
        "country": geo.get("country") or geo.get("country_code"),
        "works_count": row.get("works_count") or 0,
        "cited_by_count": row.get("cited_by_count") or 0,
        "openalex_url": row.get("id"),
        "orcid": ids.get("orcid"),
        "source": "openalex",
    }


def get_local_search_candidates(conn: sqlite3.Connection, query: str, limit: int = 15) -> List[Dict[str, Any]]:
    prefix = normalize_text(query)
    rows = conn.execute(
        """
        SELECT
            openalex_author_id, display_name, last_known_affiliation, country_code,
            works_count, cited_by_count, openalex_url, homepage_url, google_scholar_url, orcid
        FROM author_cache
        WHERE normalized_name LIKE ?
        ORDER BY works_count DESC, cited_by_count DESC
        LIMIT ?
        """,
        (f"{prefix}%", limit),
    ).fetchall()
    return [
        {
            "id": row["openalex_author_id"],
            "display_name": row["display_name"],
            "affiliation": row["last_known_affiliation"],
            "country": row["country_code"],
            "works_count": row["works_count"],
            "cited_by_count": row["cited_by_count"],
            "openalex_url": row["openalex_url"],
            "website_url": row["homepage_url"],
            "google_scholar_url": row["google_scholar_url"],
            "orcid": row["orcid"],
            "source": "local",
        }
        for row in rows
    ]


def persist_author_candidate(conn: sqlite3.Connection, candidate: Dict[str, Any]) -> None:
    now = utc_now_iso()
    openalex_id = canonical_author_id(candidate["id"])
    openalex_url = candidate.get("openalex_url") or openalex_id
    execute_write_with_retry(
        conn,
        """
        INSERT INTO author_cache (
            openalex_author_id, display_name, normalized_name, last_known_affiliation,
            country_code, works_count, cited_by_count, orcid, openalex_url,
            homepage_url, google_scholar_url, last_seen_at, last_refreshed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(openalex_author_id) DO UPDATE SET
            display_name=excluded.display_name,
            normalized_name=excluded.normalized_name,
            last_known_affiliation=COALESCE(excluded.last_known_affiliation, author_cache.last_known_affiliation),
            country_code=COALESCE(excluded.country_code, author_cache.country_code),
            works_count=MAX(excluded.works_count, author_cache.works_count),
            cited_by_count=MAX(excluded.cited_by_count, author_cache.cited_by_count),
            orcid=COALESCE(excluded.orcid, author_cache.orcid),
            homepage_url=COALESCE(excluded.homepage_url, author_cache.homepage_url),
            google_scholar_url=COALESCE(excluded.google_scholar_url, author_cache.google_scholar_url),
            last_seen_at=excluded.last_seen_at,
            last_refreshed_at=excluded.last_refreshed_at
        """,
        (
            openalex_id,
            candidate.get("display_name") or "Unknown",
            normalize_text(candidate.get("display_name") or "Unknown"),
            candidate.get("affiliation"),
            candidate.get("country"),
            int(candidate.get("works_count") or 0),
            int(candidate.get("cited_by_count") or 0),
            candidate.get("orcid"),
            openalex_url,
            candidate.get("website_url"),
            candidate.get("google_scholar_url"),
            now,
            now,
        ),
    )


def merge_and_rank_candidates(local: List[Dict[str, Any]], remote: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for candidate in remote + local:
        key = canonical_author_id(candidate["id"])
        existing = merged.get(key)
        if not existing:
            merged[key] = dict(candidate)
            merged[key]["id"] = key
            continue
        # Prefer richer values from whichever entry has them.
        for field_name in ["affiliation", "country", "website_url", "google_scholar_url", "orcid", "openalex_url"]:
            if not existing.get(field_name) and candidate.get(field_name):
                existing[field_name] = candidate[field_name]
        for metric_name in ["works_count", "cited_by_count"]:
            existing[metric_name] = max(int(existing.get(metric_name) or 0), int(candidate.get(metric_name) or 0))

    normalized_query = normalize_text(query)

    def score(item: Dict[str, Any]) -> Tuple[int, int, int, int]:
        name = normalize_text(item.get("display_name") or "")
        prefix_bonus = 2 if name.startswith(normalized_query) else 0
        source_kind = item.get("source")
        source_bonus = 0
        if source_kind == "openalex_autocomplete":
            source_bonus = 3
        elif source_kind == "local":
            source_bonus = 1
        elif source_kind == "openalex_search_fallback":
            source_bonus = -1
        impact = int(math.log1p(max(int(item.get("works_count") or 0), int(item.get("cited_by_count") or 0))))
        orcid_bonus = 1 if item.get("orcid") else 0
        return prefix_bonus, source_bonus, impact, orcid_bonus

    def collapse_likely_duplicates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            name_key = normalize_text(item.get("display_name") or "")
            if not name_key:
                continue
            grouped.setdefault(name_key, []).append(item)

        collapsed: List[Dict[str, Any]] = []
        for _, group in grouped.items():
            best = sorted(
                group,
                key=lambda x: (
                    score(x),
                    int(x.get("works_count") or 0),
                    int(x.get("cited_by_count") or 0),
                ),
                reverse=True,
            )[0]
            collapsed.append(best)
        return collapsed

    de_duplicated = collapse_likely_duplicates(list(merged.values()))
    ranked = sorted(
        de_duplicated,
        key=lambda x: (
            score(x),
            int(x.get("works_count") or 0),
            int(x.get("cited_by_count") or 0),
        ),
        reverse=True,
    )
    return ranked[:15]


def autocomplete_authors(conn: sqlite3.Connection, query: str) -> Dict[str, Any]:
    settings = get_settings()
    q = query.strip()
    if len(q) < 4:
        local_results = get_local_search_candidates(conn, q, limit=8)
        return {
            "results": local_results,
            "remote_error": None,
            "remote_source": "skipped_below_min_chars",
            "local_count": len(local_results),
            "remote_count": 0,
        }

    local = get_local_search_candidates(conn, q, limit=12)
    remote_error: Optional[str] = None
    remote_source = "autocomplete"
    remote_count = 0
    cache_key = f"v{settings.search_cache_version}:{normalize_text(q)}"
    cached_row = conn.execute(
        "SELECT candidate_json, freshness_timestamp FROM search_suggestion_cache WHERE prefix = ?",
        (cache_key,),
    ).fetchone()
    if cached_row:
        freshness = datetime.fromisoformat(cached_row["freshness_timestamp"])
        if datetime.now(timezone.utc) - freshness <= timedelta(seconds=settings.search_cache_ttl_seconds):
            cached = json.loads(cached_row["candidate_json"])
            if cached:
                return {
                    "results": cached,
                    "remote_error": None,
                    "remote_source": "cache",
                    "local_count": len(local),
                    "remote_count": 0,
                }

    remote_candidates: List[Dict[str, Any]] = []
    openalex = OpenAlexClient()
    try:
        for row in openalex.autocomplete_authors(q, per_page=12):
            affiliation, country = parse_hint(row.get("hint", ""))
            remote_candidates.append(
                {
                    "id": row.get("id"),
                    "display_name": row.get("display_name"),
                    "affiliation": affiliation,
                    "country": country,
                    "works_count": row.get("works_count") or 0,
                    "cited_by_count": row.get("cited_by_count") or 0,
                    "openalex_url": row.get("id"),
                    "source": "openalex_autocomplete",
                }
            )
        if not remote_candidates:
            remote_source = "authors_search_fallback"
            for row in openalex.search_authors(q, per_page=12):
                candidate = author_search_row_to_candidate(row)
                if candidate.get("id") and candidate.get("display_name"):
                    candidate["source"] = "openalex_search_fallback"
                    remote_candidates.append(candidate)
        remote_count = len(remote_candidates)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        response_text = ""
        try:
            response_text = (exc.response.text or "").strip()[:180]
        except Exception:
            response_text = ""
        remote_error = f"OpenAlex HTTP {status}. {response_text or 'Request rejected.'}"
        logger.warning("OpenAlex HTTP failure during autocomplete: %s", remote_error)
        remote_candidates = []
    except httpx.RequestError as exc:
        remote_error = f"OpenAlex network error: {str(exc)[:180]}"
        logger.warning("OpenAlex network failure during autocomplete: %s", remote_error)
        remote_candidates = []
    except Exception as exc:
        # Keep autocomplete functional from local cache even if OpenAlex is temporarily unavailable.
        remote_error = f"OpenAlex search failed: {str(exc)[:180]}"
        logger.exception("Unexpected OpenAlex autocomplete failure")
        remote_candidates = []
    finally:
        openalex.close()

    merged = merge_and_rank_candidates(local, remote_candidates, q)
    for candidate in merged:
        try:
            persist_author_candidate(conn, candidate)
        except sqlite3.OperationalError as exc:
            logger.warning("Skipping author cache write due to SQLite lock: %s", exc)

    now = utc_now_iso()
    try:
        execute_write_with_retry(
            conn,
            """
            INSERT INTO search_suggestion_cache(prefix, candidate_json, freshness_timestamp)
            VALUES (?, ?, ?)
            ON CONFLICT(prefix) DO UPDATE SET
                candidate_json=excluded.candidate_json,
                freshness_timestamp=excluded.freshness_timestamp
            """,
            (cache_key, json.dumps(merged), now),
        )
    except sqlite3.OperationalError as exc:
        logger.warning("Skipping suggestion cache write due to SQLite lock: %s", exc)
    return {
        "results": merged,
        "remote_error": remote_error,
        "remote_source": remote_source,
        "local_count": len(local),
        "remote_count": remote_count,
    }


@dataclass
class PlacementCandidate:
    institution_id: Optional[str]
    institution_name: Optional[str]
    country_code: Optional[str]
    country_name: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    source_work_id: str
    source_year: Optional[int]


@dataclass
class CollaboratorAggregate:
    openalex_author_id: str
    display_name: str
    joint_paper_count: int = 0
    first_collaboration_year: Optional[int] = None
    last_collaboration_year: Optional[int] = None
    candidates: List[PlacementCandidate] = field(default_factory=list)
    raw_institutions: List[dict] = field(default_factory=list)


def pick_primary_candidate(candidates: List[PlacementCandidate]) -> Optional[PlacementCandidate]:
    if not candidates:
        return None
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            c.source_year if c.source_year is not None else -1,
            1 if c.institution_id else 0,
        ),
        reverse=True,
    )
    for candidate in sorted_candidates:
        if normalize_institution_key(candidate.institution_id, candidate.institution_name):
            return candidate
    return None


def infer_links_from_author_payload(author_payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    website = author_payload.get("homepage_url")
    ids = author_payload.get("ids") or {}
    orcid = ids.get("orcid")
    scholar = None
    for value in ids.values():
        if isinstance(value, str) and "scholar.google." in value:
            scholar = value
            break
    return website, scholar, orcid


def upsert_person_links(
    conn: sqlite3.Connection,
    openalex_author_id: str,
    website_url: Optional[str],
    google_scholar_url: Optional[str],
    orcid_url: Optional[str],
) -> Dict[str, Any]:
    openalex_url = canonical_author_id(openalex_author_id)
    preferred_url, available_links = choose_preferred_link(website_url, google_scholar_url, orcid_url, openalex_url)
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO person_links (
            openalex_author_id, website_url, google_scholar_url, orcid_url, openalex_url,
            available_links_json, preferred_url, link_confidence, last_verified_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(openalex_author_id) DO UPDATE SET
            website_url=COALESCE(excluded.website_url, person_links.website_url),
            google_scholar_url=COALESCE(excluded.google_scholar_url, person_links.google_scholar_url),
            orcid_url=COALESCE(excluded.orcid_url, person_links.orcid_url),
            available_links_json=excluded.available_links_json,
            preferred_url=excluded.preferred_url,
            last_verified_at=excluded.last_verified_at
        """,
        (
            openalex_author_id,
            website_url,
            google_scholar_url,
            orcid_url,
            openalex_url,
            json.dumps(available_links),
            preferred_url,
            0.5 if website_url or google_scholar_url or orcid_url else 0.2,
            now,
        ),
    )
    return {"preferred_url": preferred_url, "available_links": available_links}


def fetch_person_links(conn: sqlite3.Connection, openalex_author_id: str) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT preferred_url, available_links_json FROM person_links
        WHERE openalex_author_id = ?
        """,
        (openalex_author_id,),
    ).fetchone()
    if row:
        return {"preferred_url": row["preferred_url"], "available_links": json.loads(row["available_links_json"])}
    openalex_url = canonical_author_id(openalex_author_id)
    return {"preferred_url": openalex_url, "available_links": [openalex_url]}


def geocode_institution_once(
    name: Optional[str],
    country_name: Optional[str],
    timeout_seconds: float = 1.5,
) -> Tuple[Optional[float], Optional[float]]:
    if not name:
        return None, None
    query = name if not country_name else f"{name}, {country_name}"
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": "collaboration-atlas/0.1"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            return None, None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        return None, None


def llm_geocode_institution_once(
    institution_name: Optional[str],
    country_name: Optional[str],
    timeout_seconds: float = 15.0,
) -> Tuple[Optional[float], Optional[float]]:
    settings = get_settings()
    if not institution_name or not settings.openrouter_api_key or not settings.llm_geocode_enabled:
        return None, None

    prompt_payload = {
        "institution_name": institution_name,
        "country_name": country_name,
        "required_output_json_schema": {"lat": "float", "lon": "float"},
    }
    body = {
        "model": resolve_openrouter_model(settings),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Find institution coordinates from web evidence. "
                    "Return STRICT JSON only with keys lat and lon. "
                    "No markdown, no prose, no extra keys."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload)},
        ],
        "temperature": 0,
    }
    if settings.openrouter_force_online:
        body["plugins"] = [{"id": "web", "max_results": settings.openrouter_web_max_results}]

    client = httpx.Client(timeout=timeout_seconds)
    try:
        response = client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json=body,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = None
        try:
            parsed = json.loads(content)
        except Exception:
            # Strip fluff/code fences and parse the first JSON object only.
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            return None, None
        lat = float(parsed.get("lat"))
        lon = float(parsed.get("lon"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, None
        return lat, lon
    except Exception:
        return None, None
    finally:
        client.close()


def _parse_loose_json_object(content: str) -> Optional[dict]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def infer_unplaced_institution_from_openalex_recent_works(
    collaborator_openalex_id: str,
    recent_years: int,
) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    canonical_collaborator = canonical_author_id(collaborator_openalex_id)
    if not canonical_collaborator:
        return None

    current_year = datetime.now(timezone.utc).year
    min_year = current_year - max(0, int(recent_years)) + 1
    choices: Dict[str, Dict[str, Any]] = {}

    openalex = OpenAlexClient()
    try:
        works = openalex.fetch_works_for_author(
            canonical_collaborator,
            per_page=settings.unplaced_openalex_per_page,
            max_pages=settings.unplaced_openalex_max_work_pages,
        )
    except Exception:
        return None
    finally:
        openalex.close()

    for work in works:
        publication_year = work.get("publication_year")
        if publication_year is not None and publication_year < min_year:
            break
        work_id = str(work.get("id") or "")
        for authorship in (work.get("authorships") or []):
            author = authorship.get("author") or {}
            if canonical_author_id(author.get("id", "")) != canonical_collaborator:
                continue
            for inst in (authorship.get("institutions") or []):
                institution_name = (inst.get("display_name") or "").strip()
                if not institution_name:
                    continue
                institution_id = inst.get("id")
                country_code = (inst.get("country_code") or "").strip().upper() or None
                key = normalize_institution_key(institution_id, institution_name)
                if not key:
                    continue
                item = choices.get(key)
                if not item:
                    item = {
                        "institution_name": institution_name,
                        "country_code": country_code,
                        "count": 0,
                        "latest_year": publication_year,
                        "evidence_urls": [],
                    }
                    choices[key] = item
                item["count"] += 1
                if publication_year is not None:
                    if item["latest_year"] is None or publication_year > item["latest_year"]:
                        item["latest_year"] = publication_year
                if work_id and work_id not in item["evidence_urls"] and len(item["evidence_urls"]) < 5:
                    item["evidence_urls"].append(work_id)

    if not choices:
        return None

    best = max(
        choices.values(),
        key=lambda x: (
            int(x.get("count") or 0),
            int(x.get("latest_year") or -1),
        ),
    )
    count = int(best.get("count") or 0)
    confidence = min(1.0, 0.55 + (0.1 * max(0, count - 1)))
    return {
        "institution_name": best.get("institution_name"),
        "country_code": best.get("country_code"),
        "confidence": confidence,
        "evidence_urls": best.get("evidence_urls") or [],
        "reason_short": f"OpenAlex recent works match count={count}",
        "resolution_source": "openalex_recent_works",
    }


def llm_infer_unplaced_institution(
    collaborator_name: str,
    collaborator_openalex_id: str,
    focal_author_name: Optional[str],
    timeout_seconds: float = 12.0,
) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    if not settings.openrouter_api_key or not settings.unplaced_online_resolution_enabled:
        return None
    model = resolve_openrouter_cheap_model(settings)
    if not model:
        return None
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Identify the scholar's most likely institution for map placement fallback. "
                    "Use web evidence including Google Scholar/university profile/ORCID/OpenAlex where possible. "
                    "Return STRICT JSON ONLY with keys: institution_name, country_code, confidence, evidence_urls, reason_short. "
                    "confidence must be 0..1. If unsure, set institution_name null and confidence <= 0.4."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "collaborator_name": collaborator_name,
                        "collaborator_openalex_id": collaborator_openalex_id,
                        "focal_author_name": focal_author_name,
                    }
                ),
            },
        ],
        "temperature": 0,
    }
    if settings.openrouter_force_online:
        body["plugins"] = [{"id": "web", "max_results": settings.openrouter_web_max_results}]

    client = httpx.Client(timeout=timeout_seconds)
    try:
        response = client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            json=body,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        parsed = _parse_loose_json_object(content)
        if not parsed:
            return None
        institution_name = parsed.get("institution_name")
        if institution_name is not None:
            institution_name = str(institution_name).strip()
            if not institution_name:
                institution_name = None
        country_code = parsed.get("country_code")
        if country_code is not None:
            country_code = str(country_code).strip().upper()[:2]
            if not country_code:
                country_code = None
        try:
            confidence = float(parsed.get("confidence"))
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        evidence_urls = parsed.get("evidence_urls")
        if not isinstance(evidence_urls, list):
            evidence_urls = []
        evidence_urls = [str(url) for url in evidence_urls[:5] if isinstance(url, (str, bytes))]
        reason_short = str(parsed.get("reason_short") or "")[:200]
        return {
            "institution_name": institution_name,
            "country_code": country_code,
            "confidence": confidence,
            "evidence_urls": evidence_urls,
            "reason_short": reason_short,
        }
    except Exception:
        return None
    finally:
        client.close()


def build_map_snapshot(conn: sqlite3.Connection, focal_author_id: str, force_refresh: bool = False) -> Dict[str, Any]:
    settings = get_settings()
    canonical_focal = canonical_author_id(focal_author_id)
    snapshot_row = conn.execute(
        "SELECT snapshot_json, last_built_time FROM map_snapshot WHERE focal_author_id = ?",
        (canonical_focal,),
    ).fetchone()
    if snapshot_row and not force_refresh:
        built_at = datetime.fromisoformat(snapshot_row["last_built_time"])
        if datetime.now(timezone.utc) - built_at <= timedelta(seconds=settings.snapshot_ttl_seconds):
            return json.loads(snapshot_row["snapshot_json"])

    openalex = OpenAlexClient()
    try:
        focal_author = openalex.fetch_author(canonical_focal)
        works = openalex.fetch_works_for_author(canonical_focal)
    finally:
        openalex.close()

    collaborators: Dict[str, CollaboratorAggregate] = {}
    unplaced: List[Dict[str, Any]] = []
    focal_found_in_works = 0
    unplaced_openalex_attempts = 0
    unplaced_online_attempts = 0
    focal_display_name = focal_author.get("display_name")

    for work in works:
        authorships = work.get("authorships") or []
        work_id = work.get("id", "")
        publication_year = work.get("publication_year")
        focal_in_work = False
        for authorship in authorships:
            author = authorship.get("author") or {}
            if canonical_author_id(author.get("id", "")) == canonical_focal:
                focal_in_work = True
                break
        if not focal_in_work:
            continue
        focal_found_in_works += 1

        for authorship in authorships:
            author = authorship.get("author") or {}
            coauthor_id_raw = author.get("id")
            if not coauthor_id_raw:
                continue
            coauthor_id = canonical_author_id(coauthor_id_raw)
            if coauthor_id == canonical_focal:
                continue

            agg = collaborators.get(coauthor_id)
            if not agg:
                agg = CollaboratorAggregate(
                    openalex_author_id=coauthor_id,
                    display_name=author.get("display_name", "Unknown"),
                )
                collaborators[coauthor_id] = agg

            agg.joint_paper_count += 1
            if publication_year is not None:
                agg.first_collaboration_year = (
                    publication_year
                    if agg.first_collaboration_year is None
                    else min(agg.first_collaboration_year, publication_year)
                )
                agg.last_collaboration_year = (
                    publication_year
                    if agg.last_collaboration_year is None
                    else max(agg.last_collaboration_year, publication_year)
                )

            institutions = authorship.get("institutions") or []
            agg.raw_institutions.extend(institutions)
            for inst in institutions:
                geo = inst.get("geo") or {}
                agg.candidates.append(
                    PlacementCandidate(
                        institution_id=inst.get("id"),
                        institution_name=inst.get("display_name"),
                        country_code=inst.get("country_code"),
                        country_name=geo.get("country"),
                        lat=geo.get("latitude"),
                        lon=geo.get("longitude"),
                        source_work_id=work_id,
                        source_year=publication_year,
                    )
                )

    blobs: Dict[str, Dict[str, Any]] = {}
    total_placements = 0
    geocode_attempts = 0
    known_institution_coords: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for row in conn.execute("SELECT institution_key, lat, lon FROM institution").fetchall():
        known_institution_coords[row["institution_key"]] = (row["lat"], row["lon"])
    now = utc_now_iso()
    conn.execute("DELETE FROM collaborator_placement WHERE focal_author_id = ?", (canonical_focal,))
    conn.execute("DELETE FROM unplaced_collaborators WHERE focal_author_id = ?", (canonical_focal,))

    for collaborator_id, agg in collaborators.items():
        primary_candidate = pick_primary_candidate(agg.candidates)
        conn.execute(
            """
            INSERT INTO collaborator(
                openalex_author_id, display_name, joint_paper_count, first_collaboration_year,
                last_collaboration_year, openalex_url, last_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(openalex_author_id) DO UPDATE SET
                display_name=excluded.display_name,
                joint_paper_count=excluded.joint_paper_count,
                first_collaboration_year=excluded.first_collaboration_year,
                last_collaboration_year=excluded.last_collaboration_year,
                openalex_url=excluded.openalex_url,
                last_updated_at=excluded.last_updated_at
            """,
            (
                collaborator_id,
                agg.display_name,
                agg.joint_paper_count,
                agg.first_collaboration_year,
                agg.last_collaboration_year,
                collaborator_id,
                now,
            ),
        )
        link_info = fetch_person_links(conn, collaborator_id)

        if not primary_candidate:
            fallback_institution_name: Optional[str] = None
            fallback_country_code: Optional[str] = None
            fallback_confidence: float = 0.0
            evidence_urls: List[str] = []
            fallback_source = "none"

            cached_resolution = conn.execute(
                """
                SELECT adjudication_json, confidence
                FROM affiliation_resolution
                WHERE openalex_author_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (collaborator_id,),
            ).fetchone()
            if cached_resolution:
                try:
                    parsed = json.loads(cached_resolution["adjudication_json"])
                except Exception:
                    parsed = {}
                fallback_institution_name = parsed.get("institution_name") or parsed.get("primary_affiliation")
                fallback_country_code = parsed.get("country_code")
                fallback_confidence = float(cached_resolution["confidence"] or 0.0)
                evidence_urls = parsed.get("evidence_urls") or []
                fallback_source = str(parsed.get("resolution_source") or "cached")

            should_try_openalex = (
                not fallback_institution_name
                and settings.unplaced_openalex_resolution_enabled
                and force_refresh
                and unplaced_openalex_attempts < settings.unplaced_openalex_max_per_snapshot
            )
            if should_try_openalex:
                unplaced_openalex_attempts += 1
                inferred = infer_unplaced_institution_from_openalex_recent_works(
                    collaborator_openalex_id=collaborator_id,
                    recent_years=settings.unplaced_openalex_recent_years,
                )
                if inferred:
                    fallback_institution_name = inferred.get("institution_name")
                    fallback_country_code = inferred.get("country_code")
                    fallback_confidence = float(inferred.get("confidence") or 0.0)
                    evidence_urls = inferred.get("evidence_urls") or []
                    fallback_source = str(inferred.get("resolution_source") or "openalex_recent_works")
                    now_resolution = utc_now_iso()
                    conn.execute(
                        """
                        INSERT INTO affiliation_resolution(
                            openalex_author_id, evidence_json, adjudication_json, confidence, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            collaborator_id,
                            json.dumps({"evidence_urls": evidence_urls}),
                            json.dumps(inferred),
                            fallback_confidence,
                            now_resolution,
                            now_resolution,
                        ),
                    )

            should_try_online = (
                not fallback_institution_name
                and settings.unplaced_online_resolution_enabled
                and settings.openrouter_api_key
                and force_refresh
                and unplaced_online_attempts < settings.unplaced_online_max_per_snapshot
            )
            if should_try_online:
                unplaced_online_attempts += 1
                inferred = llm_infer_unplaced_institution(
                    collaborator_name=agg.display_name,
                    collaborator_openalex_id=collaborator_id,
                    focal_author_name=focal_display_name,
                    timeout_seconds=settings.unplaced_online_timeout_seconds,
                )
                if inferred:
                    fallback_institution_name = inferred.get("institution_name")
                    fallback_country_code = inferred.get("country_code")
                    fallback_confidence = float(inferred.get("confidence") or 0.0)
                    evidence_urls = inferred.get("evidence_urls") or []
                    fallback_source = "llm_online_unplaced"
                    now_resolution = utc_now_iso()
                    conn.execute(
                        """
                        INSERT INTO affiliation_resolution(
                            openalex_author_id, evidence_json, adjudication_json, confidence, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            collaborator_id,
                            json.dumps({"evidence_urls": evidence_urls}),
                            json.dumps({**inferred, "resolution_source": fallback_source}),
                            fallback_confidence,
                            now_resolution,
                            now_resolution,
                        ),
                    )

            min_required_confidence = (
                settings.unplaced_openalex_min_confidence
                if fallback_source == "openalex_recent_works"
                else settings.unplaced_online_min_confidence
            )
            if fallback_institution_name and fallback_confidence >= min_required_confidence:
                _, inferred_country_name = infer_country_for_institution(fallback_institution_name)
                key = normalize_institution_key(None, fallback_institution_name)
                if key:
                    total_placements += 1
                    local_lat, local_lon, _src = infer_local_coordinates(fallback_institution_name, fallback_country_code)
                    lat, lon = local_lat, local_lon
                    if (lat is None or lon is None) and settings.llm_geocode_enabled:
                        llm_lat, llm_lon = llm_geocode_institution_once(
                            fallback_institution_name,
                            inferred_country_name,
                            timeout_seconds=settings.llm_geocode_timeout_seconds,
                        )
                        lat = lat if lat is not None else llm_lat
                        lon = lon if lon is not None else llm_lon
                    if (lat is None or lon is None) and settings.geocode_enabled:
                        geo_lat, geo_lon = geocode_institution_once(
                            fallback_institution_name,
                            inferred_country_name,
                            timeout_seconds=settings.geocode_timeout_seconds,
                        )
                        lat = lat if lat is not None else geo_lat
                        lon = lon if lon is not None else geo_lon

                    conn.execute(
                        """
                        INSERT INTO institution(
                            institution_key, institution_id, institution_name, country_code, country_name,
                            lat, lon, normalization_source, alias_json, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(institution_key) DO UPDATE SET
                            institution_name=excluded.institution_name,
                            country_code=COALESCE(excluded.country_code, institution.country_code),
                            country_name=COALESCE(excluded.country_name, institution.country_name),
                            lat=COALESCE(excluded.lat, institution.lat),
                            lon=COALESCE(excluded.lon, institution.lon),
                            updated_at=excluded.updated_at
                        """,
                        (
                            key,
                            None,
                            fallback_institution_name,
                            fallback_country_code,
                            inferred_country_name,
                            lat,
                            lon,
                            fallback_source,
                            json.dumps([]),
                            now,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO collaborator_placement(
                            focal_author_id, collaborator_author_id, institution_key, placement_basis,
                            source_work_id, source_year, raw_institutions_json, is_joint_position,
                            primary_is_super_clear, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            canonical_focal,
                            collaborator_id,
                            key,
                            fallback_source,
                            None,
                            agg.last_collaboration_year,
                            json.dumps({"evidence_urls": evidence_urls}),
                            0,
                            0,
                            now,
                        ),
                    )
                    person_row = {
                        "openalex_author_id": collaborator_id,
                        "display_name": agg.display_name,
                        "joint_paper_count": agg.joint_paper_count,
                        "first_collaboration_year": agg.first_collaboration_year,
                        "last_collaboration_year": agg.last_collaboration_year,
                        "is_joint_position": False,
                        "primary_is_super_clear": False,
                        "preferred_url": link_info["preferred_url"],
                        "available_links": link_info["available_links"],
                    }
                    if key not in blobs:
                        blobs[key] = {
                            "institution_key": key,
                            "institution_name": fallback_institution_name,
                            "country_code": fallback_country_code,
                            "country_name": inferred_country_name,
                            "lat": lat,
                            "lon": lon,
                            "city_name": None,
                            "city_lat": None,
                            "city_lon": None,
                            "coordinate_basis": fallback_source,
                            "people": [],
                            "max_last_collaboration_year": agg.last_collaboration_year,
                            "min_last_collaboration_year": agg.last_collaboration_year,
                        }
                    blobs[key]["people"].append(person_row)
                    if agg.last_collaboration_year is not None:
                        current_max = blobs[key]["max_last_collaboration_year"]
                        current_min = blobs[key]["min_last_collaboration_year"]
                        blobs[key]["max_last_collaboration_year"] = (
                            agg.last_collaboration_year
                            if current_max is None
                            else max(current_max, agg.last_collaboration_year)
                        )
                        blobs[key]["min_last_collaboration_year"] = (
                            agg.last_collaboration_year
                            if current_min is None
                            else min(current_min, agg.last_collaboration_year)
                        )
                    continue

            unplaced_row = {
                "openalex_author_id": collaborator_id,
                "display_name": agg.display_name,
                "joint_paper_count": agg.joint_paper_count,
                "last_collaboration_year": agg.last_collaboration_year,
                "reason": "missing_institution_on_joint_papers",
                "preferred_url": link_info["preferred_url"],
            }
            unplaced.append(unplaced_row)
            conn.execute(
                """
                INSERT INTO unplaced_collaborators(
                    focal_author_id, collaborator_author_id, reason, raw_evidence_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    canonical_focal,
                    collaborator_id,
                    "missing_institution_on_joint_papers",
                    json.dumps(agg.raw_institutions),
                    now,
                ),
            )
            continue

        key = normalize_institution_key(primary_candidate.institution_id, primary_candidate.institution_name)
        if not key:
            continue
        total_placements += 1
        fallback_country_code, fallback_country_name = infer_country_for_institution(primary_candidate.institution_name)
        country_code = primary_candidate.country_code or fallback_country_code
        country_name = primary_candidate.country_name or fallback_country_name
        fallback_city_name: Optional[str] = None
        fallback_city_lat: Optional[float] = None
        fallback_city_lon: Optional[float] = None
        coordinate_basis = "institution"
        existing_lat, existing_lon = known_institution_coords.get(key, (None, None))
        lat = primary_candidate.lat if primary_candidate.lat is not None else existing_lat
        lon = primary_candidate.lon if primary_candidate.lon is not None else existing_lon
        if (
            (lat is None or lon is None)
            and settings.geocode_enabled
            and geocode_attempts < settings.geocode_max_lookups_per_snapshot
        ):
            local_lat, local_lon, source = infer_local_coordinates(primary_candidate.institution_name, country_code)
            lat = lat if lat is not None else local_lat
            lon = lon if lon is not None else local_lon
            if source == "local_city_csv":
                city_name, city_lat, city_lon, _ = infer_city_for_institution(
                    primary_candidate.institution_name,
                    country_code,
                )
                fallback_city_name = city_name
                fallback_city_lat = city_lat
                fallback_city_lon = city_lon
                if lat is not None and lon is not None:
                    coordinate_basis = "city_fallback"

        if (
            (lat is None or lon is None)
            and settings.geocode_enabled
            and geocode_attempts < settings.geocode_max_lookups_per_snapshot
        ):
            geocode_attempts += 1
            llm_lat, llm_lon = llm_geocode_institution_once(
                primary_candidate.institution_name,
                country_name,
                timeout_seconds=settings.llm_geocode_timeout_seconds,
            )
            lat = lat if lat is not None else llm_lat
            lon = lon if lon is not None else llm_lon
            if lat is not None and lon is not None and primary_candidate.institution_name:
                append_coordinate_cache_row(
                    institution_name=primary_candidate.institution_name,
                    country_code=country_code,
                    lat=lat,
                    lon=lon,
                    source="openrouter_online",
                )
                coordinate_basis = "llm_online"

        if (
            (lat is None or lon is None)
            and settings.geocode_enabled
            and geocode_attempts < settings.geocode_max_lookups_per_snapshot
        ):
            geocode_attempts += 1
            geocoded_lat, geocoded_lon = geocode_institution_once(
                primary_candidate.institution_name,
                country_name,
                timeout_seconds=settings.geocode_timeout_seconds,
            )
            lat = lat if lat is not None else geocoded_lat
            lon = lon if lon is not None else geocoded_lon
            if lat is not None and lon is not None and primary_candidate.institution_name:
                append_coordinate_cache_row(
                    institution_name=primary_candidate.institution_name,
                    country_code=country_code,
                    lat=lat,
                    lon=lon,
                    source="nominatim",
                )
                coordinate_basis = "nominatim"
        known_institution_coords[key] = (lat, lon)
        if lat is None or lon is None:
            coordinate_basis = "unknown"

        conn.execute(
            """
            INSERT INTO institution(
                institution_key, institution_id, institution_name, country_code, country_name,
                lat, lon, normalization_source, alias_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(institution_key) DO UPDATE SET
                institution_name=excluded.institution_name,
                country_code=COALESCE(excluded.country_code, institution.country_code),
                country_name=COALESCE(excluded.country_name, institution.country_name),
                lat=COALESCE(excluded.lat, institution.lat),
                lon=COALESCE(excluded.lon, institution.lon),
                updated_at=excluded.updated_at
            """,
            (
                key,
                primary_candidate.institution_id,
                primary_candidate.institution_name or "Unknown Institution",
                country_code,
                country_name,
                lat,
                lon,
                "openalex_id" if primary_candidate.institution_id else "normalized_name",
                json.dumps([]),
                now,
            ),
        )

        conn.execute(
            """
            INSERT INTO collaborator_placement(
                focal_author_id, collaborator_author_id, institution_key, placement_basis,
                source_work_id, source_year, raw_institutions_json, is_joint_position,
                primary_is_super_clear, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_focal,
                collaborator_id,
                key,
                "latest_joint_paper",
                primary_candidate.source_work_id,
                primary_candidate.source_year,
                json.dumps(agg.raw_institutions),
                0,
                0,
                now,
            ),
        )

        person_row = {
            "openalex_author_id": collaborator_id,
            "display_name": agg.display_name,
            "joint_paper_count": agg.joint_paper_count,
            "first_collaboration_year": agg.first_collaboration_year,
            "last_collaboration_year": agg.last_collaboration_year,
            "is_joint_position": False,
            "primary_is_super_clear": False,
            "preferred_url": link_info["preferred_url"],
            "available_links": link_info["available_links"],
        }

        if key not in blobs:
            blobs[key] = {
                "institution_key": key,
                "institution_name": primary_candidate.institution_name or "Unknown Institution",
                "country_code": country_code,
                "country_name": country_name,
                "lat": lat,
                "lon": lon,
                "city_name": fallback_city_name,
                "city_lat": fallback_city_lat,
                "city_lon": fallback_city_lon,
                "coordinate_basis": coordinate_basis,
                "people": [],
                "max_last_collaboration_year": agg.last_collaboration_year,
                "min_last_collaboration_year": agg.last_collaboration_year,
            }
        blobs[key]["people"].append(person_row)
        if agg.last_collaboration_year is not None:
            current_max = blobs[key]["max_last_collaboration_year"]
            current_min = blobs[key]["min_last_collaboration_year"]
            blobs[key]["max_last_collaboration_year"] = (
                agg.last_collaboration_year
                if current_max is None
                else max(current_max, agg.last_collaboration_year)
            )
            blobs[key]["min_last_collaboration_year"] = (
                agg.last_collaboration_year
                if current_min is None
                else min(current_min, agg.last_collaboration_year)
            )

    for blob in blobs.values():
        blob["people"].sort(
            key=lambda person: (
                person.get("last_collaboration_year") or 0,
                person.get("joint_paper_count") or 0,
            ),
            reverse=True,
        )
        blob["collaborator_count"] = len(blob["people"])
        blob["color_bucket"] = recency_bucket(blob.get("max_last_collaboration_year"))

    focal_last_known = (focal_author.get("last_known_institutions") or [{}])[0]
    focal_geo = focal_last_known.get("geo") or {}
    snapshot = {
        "focal_author": {
            "openalex_author_id": canonical_focal,
            "display_name": focal_author.get("display_name"),
            "works_count": focal_author.get("works_count"),
            "cited_by_count": focal_author.get("cited_by_count"),
            "last_known_affiliation": focal_last_known.get("display_name"),
            "last_known_country": focal_geo.get("country"),
            "last_known_lat": focal_geo.get("latitude"),
            "last_known_lon": focal_geo.get("longitude"),
            "openalex_url": focal_author.get("id"),
        },
        "summary": {
            "unique_collaborators": len(collaborators),
            "total_institution_placements": total_placements,
            "unplaced_collaborators": len(unplaced),
            "focal_verified_works": focal_found_in_works,
            "last_built_at": now,
        },
        "blobs": sorted(blobs.values(), key=lambda b: b["collaborator_count"], reverse=True),
        "unplaced_collaborators": unplaced,
    }

    conn.execute(
        """
        INSERT INTO map_snapshot(focal_author_id, snapshot_json, freshness_info, last_built_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(focal_author_id) DO UPDATE SET
            snapshot_json=excluded.snapshot_json,
            freshness_info=excluded.freshness_info,
            last_built_time=excluded.last_built_time
        """,
        (
            canonical_focal,
            json.dumps(snapshot),
            json.dumps({"cache_source": "openalex", "ttl_seconds": settings.snapshot_ttl_seconds}),
            now,
        ),
    )
    return snapshot


def select_focal_scholar(conn: sqlite3.Connection, openalex_author_id: str) -> Dict[str, Any]:
    canonical = canonical_author_id(openalex_author_id)
    openalex = OpenAlexClient()
    try:
        author = openalex.fetch_author(canonical)
    finally:
        openalex.close()

    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO focal_person(openalex_author_id, display_name, selected_at)
        VALUES (?, ?, ?)
        ON CONFLICT(openalex_author_id) DO UPDATE SET
            display_name=excluded.display_name,
            selected_at=excluded.selected_at
        """,
        (canonical, author.get("display_name"), now),
    )

    primary_inst = (author.get("last_known_institutions") or [{}])[0]
    geo = primary_inst.get("geo") or {}
    candidate = {
        "id": canonical,
        "display_name": author.get("display_name"),
        "affiliation": primary_inst.get("display_name"),
        "country": geo.get("country_code"),
        "works_count": author.get("works_count") or 0,
        "cited_by_count": author.get("cited_by_count") or 0,
        "orcid": (author.get("ids") or {}).get("orcid"),
        "openalex_url": author.get("id"),
    }
    persist_author_candidate(conn, candidate)
    return {"openalex_author_id": canonical, "display_name": author.get("display_name")}


def enrich_collaborator_links(conn: sqlite3.Connection, collaborator_author_id: str) -> Dict[str, Any]:
    canonical = canonical_author_id(collaborator_author_id)
    openalex = OpenAlexClient()
    try:
        author = openalex.fetch_author(canonical)
    finally:
        openalex.close()
    website, scholar, orcid = infer_links_from_author_payload(author)
    result = upsert_person_links(conn, canonical, website, scholar, orcid)
    persist_author_candidate(
        conn,
        {
            "id": canonical,
            "display_name": author.get("display_name"),
            "affiliation": ((author.get("last_known_institutions") or [{}])[0]).get("display_name"),
            "country": (((author.get("last_known_institutions") or [{}])[0]).get("geo") or {}).get("country_code"),
            "works_count": author.get("works_count") or 0,
            "cited_by_count": author.get("cited_by_count") or 0,
            "orcid": (author.get("ids") or {}).get("orcid"),
            "openalex_url": author.get("id"),
            "website_url": website,
            "google_scholar_url": scholar,
        },
    )
    return {"openalex_author_id": canonical, **result}


def refresh_focal_affiliation(conn: sqlite3.Connection, focal_author_id: str) -> Dict[str, Any]:
    settings = get_settings()
    canonical = canonical_author_id(focal_author_id)
    openalex = OpenAlexClient()
    try:
        author = openalex.fetch_author(canonical)
    finally:
        openalex.close()

    last_inst = (author.get("last_known_institutions") or [{}])[0]
    primary_guess = last_inst.get("display_name")
    source_url = author.get("id")
    confidence = 0.55

    if settings.openrouter_api_key:
        client = httpx.Client(timeout=20.0)
        try:
            prompt = {
                "model": resolve_openrouter_model(settings),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Return strict JSON for affiliation adjudication with keys: "
                            "primary_affiliation, secondary_affiliation, is_joint_position, "
                            "primary_is_super_clear, confidence, evidence_urls, reason_short."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "author_name": author.get("display_name"),
                                "openalex_last_known_institution": primary_guess,
                                "openalex_url": author.get("id"),
                            }
                        ),
                    },
                ],
                "temperature": 0,
            }
            if settings.openrouter_force_online:
                prompt["plugins"] = [{"id": "web", "max_results": settings.openrouter_web_max_results}]
            response = client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                json=prompt,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            adjudication = json.loads(content)
            primary_guess = adjudication.get("primary_affiliation") or primary_guess
            confidence = float(adjudication.get("confidence") or confidence)
            evidence_urls = adjudication.get("evidence_urls") or [source_url]
            source_url = evidence_urls[0] if evidence_urls else source_url
            now = utc_now_iso()
            conn.execute(
                """
                INSERT INTO affiliation_resolution(
                    openalex_author_id, evidence_json, adjudication_json, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (canonical, json.dumps({"openalex_url": author.get("id")}), json.dumps(adjudication), confidence, now, now),
            )
        except Exception:
            # v1 resilience fallback to OpenAlex-only placement if LLM output is weak/unparseable.
            confidence = 0.5
        finally:
            client.close()

    now = utc_now_iso()
    conn.execute(
        """
        UPDATE focal_person
        SET current_affiliation_name=?, current_affiliation_source_url=?,
            current_affiliation_confidence=?, last_verified_at=?
        WHERE openalex_author_id=?
        """,
        (primary_guess, source_url, confidence, now, canonical),
    )
    return {
        "openalex_author_id": canonical,
        "current_affiliation_name": primary_guess,
        "current_affiliation_source_url": source_url,
        "current_affiliation_confidence": confidence,
        "last_verified_at": now,
    }


def get_blob_details(snapshot: Dict[str, Any], institution_key: str) -> Optional[Dict[str, Any]]:
    for blob in snapshot.get("blobs", []):
        if blob.get("institution_key") == institution_key:
            return blob
    return None


def get_collaborator_details(snapshot: Dict[str, Any], collaborator_id: str) -> Optional[Dict[str, Any]]:
    canonical = canonical_author_id(collaborator_id)
    for blob in snapshot.get("blobs", []):
        for person in blob.get("people", []):
            if canonical_author_id(person.get("openalex_author_id", "")) == canonical:
                return {
                    **person,
                    "institution_key": blob.get("institution_key"),
                    "institution_name": blob.get("institution_name"),
                    "country_name": blob.get("country_name"),
                }
    for person in snapshot.get("unplaced_collaborators", []):
        if canonical_author_id(person.get("openalex_author_id", "")) == canonical:
            return person
    return None
