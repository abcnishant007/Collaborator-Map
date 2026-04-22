import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS author_cache (
    openalex_author_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    last_known_affiliation TEXT,
    country_code TEXT,
    works_count INTEGER DEFAULT 0,
    cited_by_count INTEGER DEFAULT 0,
    orcid TEXT,
    openalex_url TEXT NOT NULL,
    homepage_url TEXT,
    google_scholar_url TEXT,
    last_seen_at TEXT NOT NULL,
    last_refreshed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS author_alias_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    openalex_author_id TEXT NOT NULL,
    alias_name TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_prefix TEXT NOT NULL,
    chosen_author_id TEXT,
    clicked_rank INTEGER,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_suggestion_cache (
    prefix TEXT PRIMARY KEY,
    candidate_json TEXT NOT NULL,
    freshness_timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS focal_person (
    openalex_author_id TEXT PRIMARY KEY,
    display_name TEXT,
    selected_at TEXT NOT NULL,
    current_affiliation_name TEXT,
    current_affiliation_source_url TEXT,
    current_affiliation_confidence REAL,
    last_verified_at TEXT
);

CREATE TABLE IF NOT EXISTS collaborator (
    openalex_author_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    joint_paper_count INTEGER NOT NULL,
    first_collaboration_year INTEGER,
    last_collaboration_year INTEGER,
    openalex_url TEXT NOT NULL,
    last_updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS institution (
    institution_key TEXT PRIMARY KEY,
    institution_id TEXT,
    institution_name TEXT NOT NULL,
    country_code TEXT,
    country_name TEXT,
    lat REAL,
    lon REAL,
    normalization_source TEXT NOT NULL,
    alias_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collaborator_placement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    focal_author_id TEXT NOT NULL,
    collaborator_author_id TEXT NOT NULL,
    institution_key TEXT,
    placement_basis TEXT NOT NULL,
    source_work_id TEXT,
    source_year INTEGER,
    raw_institutions_json TEXT NOT NULL,
    is_joint_position INTEGER DEFAULT 0,
    primary_is_super_clear INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_links (
    openalex_author_id TEXT PRIMARY KEY,
    website_url TEXT,
    google_scholar_url TEXT,
    orcid_url TEXT,
    openalex_url TEXT NOT NULL,
    available_links_json TEXT NOT NULL,
    preferred_url TEXT NOT NULL,
    link_confidence REAL DEFAULT 0.2,
    last_verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS affiliation_resolution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    openalex_author_id TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    adjudication_json TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS map_snapshot (
    focal_author_id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    freshness_info TEXT NOT NULL,
    last_built_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unplaced_collaborators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    focal_author_id TEXT NOT NULL,
    collaborator_author_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    raw_evidence_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite DATABASE_URL is supported in v1")
    relative_or_abs = database_url.replace("sqlite:///", "", 1)
    return Path(relative_or_abs).resolve()


def init_db() -> None:
    settings = get_settings()
    db_path = database_path_from_url(settings.database_url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=20000;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn():
    settings = get_settings()
    db_path = database_path_from_url(settings.database_url)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=20.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=20000;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_json_cache(
    conn: sqlite3.Connection,
    table: str,
    key_column: str,
    key: str,
    payload: dict,
) -> None:
    if table != "map_snapshot":
        raise ValueError("Only map_snapshot is currently supported")
    now = utc_now_iso()
    freshness = json.dumps({"cached_at": now})
    conn.execute(
        """
        INSERT INTO map_snapshot (focal_author_id, snapshot_json, freshness_info, last_built_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(focal_author_id) DO UPDATE SET
            snapshot_json=excluded.snapshot_json,
            freshness_info=excluded.freshness_info,
            last_built_time=excluded.last_built_time
        """,
        (key, json.dumps(payload), freshness, now),
    )
