from __future__ import annotations

import ipaddress
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from .db import get_conn, init_db
from .services import (
    autocomplete_authors,
    build_map_snapshot,
    enrich_collaborator_links,
    get_blob_details,
    get_collaborator_details,
    refresh_focal_affiliation,
    select_focal_scholar,
)


class SelectFocalRequest(BaseModel):
    openalex_author_id: str


class DebugQuery(BaseModel):
    focal_author_id: Optional[str] = None


app = FastAPI(title="Collaboration Atlas API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _ensure_server_local_access(request: Request) -> None:
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(status_code=403, detail="Admin endpoint requires server-local access")
    if not ip.is_loopback:
        raise HTTPException(status_code=403, detail="Admin endpoint requires server-local access")


@app.get("/api/autocomplete/authors")
def api_autocomplete_authors(q: str = Query("", min_length=0)) -> Dict[str, Any]:
    with get_conn() as conn:
        payload = autocomplete_authors(conn, q)
    return {"query": q, **payload}


@app.post("/api/focal/select")
def api_select_focal(payload: SelectFocalRequest) -> Dict[str, Any]:
    with get_conn() as conn:
        selected = select_focal_scholar(conn, payload.openalex_author_id)
    return selected


@app.get("/api/map")
def api_map_snapshot(focal_author_id: str = Query(...), force_refresh: bool = False) -> Dict[str, Any]:
    with get_conn() as conn:
        snapshot = build_map_snapshot(conn, focal_author_id, force_refresh=force_refresh)
    return snapshot


def _project_lon_lat(lon: float, lat: float, width: int, height: int) -> tuple[float, float]:
    x = ((lon + 180.0) / 360.0) * width
    y = ((90.0 - lat) / 180.0) * height
    return x, y


@app.get("/api/map/static.svg")
def api_map_static_svg(focal_author_id: str = Query(...), force_refresh: bool = False) -> Response:
    with get_conn() as conn:
        snapshot = build_map_snapshot(conn, focal_author_id, force_refresh=force_refresh)

    width, height = 1400, 700
    color_map = {
        "recent": "#1f9d55",
        "warm": "#f59e0b",
        "older": "#e11d48",
        "unknown": "#64748b",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="#f4f7fb" />',
        '<text x="24" y="38" font-size="24" font-family="Arial, sans-serif" fill="#0f172a">Collaboration Atlas (Static Snapshot)</text>',
        '<text x="24" y="64" font-size="14" font-family="Arial, sans-serif" fill="#334155">Blob size = collaborators by institution; color = recency</text>',
    ]

    for blob in snapshot.get("blobs", []):
        lat = blob.get("lat")
        lon = blob.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        x, y = _project_lon_lat(lon, lat, width, height)
        count = int(blob.get("collaborator_count") or 0)
        radius = max(6, int(6 + (count ** 0.5) * 2.5))
        fill = color_map.get(blob.get("color_bucket"), color_map["unknown"])
        label = (
            f'{blob.get("institution_name", "Unknown")} '
            f'({blob.get("country_name", "Unknown country")}) '
            f'- {count} collaborators'
        )
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{fill}" fill-opacity="0.75" stroke="#0f172a" stroke-width="1">'
            f'<title>{label}</title></circle>'
        )

    parts.append('<rect x="20" y="610" width="310" height="74" fill="#ffffff" stroke="#cbd5e1" />')
    parts.append('<circle cx="38" cy="632" r="7" fill="#1f9d55" /><text x="54" y="637" font-size="12" font-family="Arial">Recent (<=2 years)</text>')
    parts.append('<circle cx="38" cy="652" r="7" fill="#f59e0b" /><text x="54" y="657" font-size="12" font-family="Arial">Warm (3-5 years)</text>')
    parts.append('<circle cx="38" cy="672" r="7" fill="#e11d48" /><text x="54" y="677" font-size="12" font-family="Arial">Older (>5 years)</text>')
    parts.append("</svg>")

    return Response(content="".join(parts), media_type="image/svg+xml")


@app.get("/api/blob")
def api_blob_details(focal_author_id: str = Query(...), institution_key: str = Query(...)) -> Dict[str, Any]:
    with get_conn() as conn:
        snapshot = build_map_snapshot(conn, focal_author_id, force_refresh=False)
        blob = get_blob_details(snapshot, institution_key)
    if not blob:
        raise HTTPException(status_code=404, detail="Institution blob not found")
    return blob


@app.get("/api/collaborator")
def api_collaborator_details(
    focal_author_id: str = Query(...),
    collaborator_author_id: str = Query(...),
) -> Dict[str, Any]:
    with get_conn() as conn:
        snapshot = build_map_snapshot(conn, focal_author_id, force_refresh=False)
        details = get_collaborator_details(snapshot, collaborator_author_id)
    if not details:
        raise HTTPException(status_code=404, detail="Collaborator not found")
    return details


@app.post("/api/focal/{focal_author_id}/refresh-affiliation")
def api_refresh_focal_affiliation(focal_author_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        refreshed = refresh_focal_affiliation(conn, focal_author_id)
    return refreshed


@app.post("/api/collaborator/{collaborator_author_id}/enrich-links")
def api_enrich_collaborator_links(collaborator_author_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        details = enrich_collaborator_links(conn, collaborator_author_id)
    return details


@app.get("/api/admin/debug/normalization")
def api_debug_normalization(request: Request, focal_author_id: Optional[str] = None) -> Dict[str, Any]:
    _ensure_server_local_access(request)
    with get_conn() as conn:
        institution_rows = conn.execute(
            """
            SELECT institution_key, institution_name, country_code, normalization_source, lat, lon
            FROM institution
            ORDER BY institution_name
            LIMIT 200
            """
        ).fetchall()
        payload: Dict[str, Any] = {
            "institutions": [dict(row) for row in institution_rows],
            "focal_author_id": focal_author_id,
        }
        if focal_author_id:
            issues = conn.execute(
                """
                SELECT collaborator_author_id, reason, raw_evidence_json
                FROM unplaced_collaborators
                WHERE focal_author_id = ?
                ORDER BY updated_at DESC
                LIMIT 200
                """,
                (focal_author_id,),
            ).fetchall()
            payload["unplaced_issues"] = [dict(row) for row in issues]
    return payload


@app.get("/api/admin/config")
def api_admin_config(request: Request) -> Dict[str, Any]:
    _ensure_server_local_access(request)
    from .config import get_settings, resolve_openrouter_model

    settings = get_settings()
    return {
        "openrouter_base_url": settings.openrouter_base_url,
        "openrouter_active_model": settings.openrouter_active_model,
        "openrouter_resolved_model": resolve_openrouter_model(settings),
        "openrouter_force_online": settings.openrouter_force_online,
        "openrouter_web_max_results": settings.openrouter_web_max_results,
        "openalex_base_url": settings.openalex_base_url,
        "has_openrouter_api_key": bool(settings.openrouter_api_key),
        "has_exa_api_key": bool(settings.exa_api_key),
    }
