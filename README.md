# Collaborator Map (Person-Centric Collaboration Atlas)

This project builds a person-centric collaboration atlas with:

- `server/` FastAPI backend (OpenAlex as canonical graph source, SQLite caching, snapshot API)
- `client/` React + Leaflet frontend (institution blobs, drilldown collaborator lists, filters)

## 1) Backend setup (`collab` conda env)

```bash
conda activate collab
conda install python
pip install -r server/requirements.txt
```

Create or update:

- `server/.env`
- `server/.env.example`

Required env vars are already listed in both files:

- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL_PRIMARY` (default `openai/gpt-5.4-mini`)
- `OPENROUTER_MODEL_SECONDARY` (default `deepseek/deepseek-v3.2`)
- `OPENROUTER_ACTIVE_MODEL` (`primary` or `secondary`)
- `OPENROUTER_FORCE_ONLINE` (`true` to append `:online` automatically)
- `OPENROUTER_WEB_MAX_RESULTS`
- `OPENALEX_BASE_URL`
- `OPENALEX_API_KEY`
- `EXA_API_KEY`
- `SEARCH_CACHE_VERSION` (bump to invalidate stale suggestion ranking cache)
- `GEOCODE_ENABLED`
- `GEOCODE_TIMEOUT_SECONDS`
- `GEOCODE_MAX_LOOKUPS_PER_SNAPSHOT`
- `LLM_GEOCODE_ENABLED`
- `LLM_GEOCODE_TIMEOUT_SECONDS`
- `DATABASE_URL`
- cache + refresh TTL vars

Run backend:

```bash
uvicorn server.app.main:app --reload --port 8000
```

## 2) Frontend setup

```bash
cd client
npm install
npm run dev
```

Optional frontend API target override:

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```

Production note:

- Leave `VITE_API_BASE` unset in production so the frontend calls same-origin `/api/*` through your reverse proxy.

## 3) v1 flow

1. Type at least 4 characters in search.
2. Select focal scholar (stores canonical OpenAlex author ID).
3. Map renders institution blobs from latest joint-paper placements.
4. Click a blob to inspect collaborators.
5. Click a collaborator row to open preferred external link (OpenAlex fallback guaranteed).

## Local one-command launch

After installing backend and frontend dependencies:

```bash
./start-servers.sh
```

Defaults:

- Backend: `127.0.0.1:5180`
- Frontend: `127.0.0.1:5179`
- Logs: `.run-logs/backend.log` and `.run-logs/frontend.log`

Optional overrides:

```bash
CONDA_ENV=collab BACKEND_PORT=9000 FRONTEND_PORT=5174 ./start-servers.sh
```

Port conflict behavior:

- Frontend uses strict port mode (`--strictPort`) and will fail instead of silently switching ports.
- Launcher always auto-kills existing processes bound to selected backend/frontend ports before startup.
- Dev proxy target is auto-wired to the launcher backend URL via `VITE_DEV_API_TARGET`.

## API endpoints

- `GET /api/autocomplete/authors?q=...`
- `POST /api/focal/select`
- `GET /api/map/{focal_author_id}`
- `GET /api/map/{focal_author_id}/static.svg`
- `GET /api/blob/{focal_author_id}/{institution_key}`
- `GET /api/collaborator/{focal_author_id}/{collaborator_author_id}`
- `POST /api/focal/refresh-affiliation?focal_author_id=...`
- `POST /api/collaborator/enrich-links?collaborator_author_id=...`
- `GET /api/admin/debug/normalization`
- `GET /api/admin/config` (read-only, server-local only)

## Sharing links

- Dynamic permalink: copy from UI button (`Copy dynamic permalink`)
- Static image link: copy from UI button (`Copy static image link`)
- Download static map image: UI button (`Download static SVG`)

## Production deployment on `colab.write-up.dev`

1. Point DNS `A`/`AAAA` for `colab.write-up.dev` to your server.
2. Copy project to `/opt/collab-map`.
3. Build frontend static assets:

```bash
cd /opt/collab-map/client
npm ci
npm run build
```

4. Install backend requirements into the `collab` env:

```bash
conda run -n collab python -m pip install -r /opt/collab-map/server/requirements.txt
```

5. Install systemd service:

```bash
sudo cp /opt/collab-map/deploy/systemd/collab-map-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now collab-map-backend.service
```

6. Install Caddy config:

```bash
sudo cp /opt/collab-map/deploy/caddy/Caddyfile.colab.write-up.dev /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

This setup serves frontend at `https://colab.write-up.dev` and proxies `/api/*` to backend on `127.0.0.1:8000`, so no public port is exposed.
Admin endpoints are blocked at Caddy (`/api/admin/* -> 403`) and also backend-restricted to loopback requests.

## API keys checklist

- Recommended for core app (needed for reliable scale and daily free quota tracking):
  - `OPENALEX_API_KEY`
- Required for optional focal affiliation adjudication:
  - `OPENROUTER_API_KEY` (uses OpenRouter web search mode by default)
- Optional for future retrieval enrichment:
  - `EXA_API_KEY` (not needed for current v1 flow if using OpenRouter `:online`)

## Model A/B testing

Switch between model options in `server/.env`:

- `OPENROUTER_ACTIVE_MODEL=primary` -> `OPENROUTER_MODEL_PRIMARY`
- `OPENROUTER_ACTIVE_MODEL=secondary` -> `OPENROUTER_MODEL_SECONDARY`

Web-search behavior:

- `OPENROUTER_FORCE_ONLINE=true` adds `:online` automatically and enables web plugin usage
- `OPENROUTER_FORCE_ONLINE=false` calls the same selected model without web plugin

## Optional local coordinate datasets (faster map builds)

- University coordinates (Kaggle): `https://www.kaggle.com/datasets/alirezarazeghi/universities-info-with-coordinates/data`
- World cities CSV: `https://raw.githubusercontent.com/joelacus/world-cities/main/world_cities_15000.csv`

If present locally, the backend now uses them before network geocoding:

- `more_data/universities_with_coordinates.csv` (or `more_data/Unis_with_lat_long.csv`)
- `more_data/institution_coordinate_cache.csv` (auto-grown from successful online fallback lookups)
- `cities_lat_long.csv`

Lookup order for missing institution coordinates:

1. OpenAlex institution `geo`
2. cached coordinates in local DB
3. local university coordinate CSV
4. local city CSV (country-filtered name match)
5. OpenRouter model geocoding (`OPENROUTER_ACTIVE_MODEL` + `:online`) with strict JSON lat/lon extraction
6. network geocoding (bounded timeout and per-snapshot cap)

When step 5 or 6 succeeds, the institution coordinate is appended to `more_data/institution_coordinate_cache.csv` so future runs can resolve it locally without another network lookup.

## AWS deployment steps (EC2)

1. Launch EC2 instance (Ubuntu 22.04 LTS recommended) with a public IP.
2. Security Group inbound:
   - allow `22` from your IP
   - allow `80` from `0.0.0.0/0`
   - allow `443` from `0.0.0.0/0`
   - do not expose `8000` publicly
3. Point DNS for `colab.write-up.dev` to the EC2 public IP.
4. SSH into instance and install runtime:

```bash
sudo apt update
sudo apt install -y git curl build-essential
```

5. Install Miniconda and create env:

```bash
conda create -n collab python=3.11 -y
conda run -n collab python -m pip install -r /opt/collab-map/server/requirements.txt
```

6. Install Node.js 20+ and build frontend:

```bash
cd /opt/collab-map/client
npm ci
npm run build
```

7. Configure backend env:

```bash
cp /opt/collab-map/server/.env.example /opt/collab-map/server/.env
# then edit keys and model toggles
```

8. Install and start systemd backend service:

```bash
sudo cp /opt/collab-map/deploy/systemd/collab-map-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now collab-map-backend.service
```

9. Install Caddy and configure TLS reverse proxy:

```bash
sudo apt install -y caddy
sudo cp /opt/collab-map/deploy/caddy/Caddyfile.colab.write-up.dev /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

10. Verify:

```bash
curl -I https://colab.write-up.dev
curl -s https://colab.write-up.dev/api/map/<OPENALEX_AUTHOR_ID> | head
curl -i https://colab.write-up.dev/api/admin/config         # should be 403
curl -s http://127.0.0.1:8000/api/admin/config              # run on server, should return JSON
```
