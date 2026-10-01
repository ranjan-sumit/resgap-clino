# Local Deployment — Docker Compose

Full local stack per `_bmad-output/clinova/08-local-deployment-architecture.md`.

## Services & ports

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `postgres` | postgres:16-alpine | **5433** | Mandatory. Role `clinova_app`, DB `clinova`; schema self-migrates (`migrations/*.sql`) on first app touch |
| `arcadedb` | arcadedata/arcadedb | **2480** | Optional knowledge-graph persistence (opt-in checkbox in Streamlit) |
| `api` | built from `Dockerfile.api` | **8000** | FastAPI backend (`apps/api`), health at `GET /api/health` |
| `web` | built from `Dockerfile.web` | **3000** | Next.js frontend (build bakes `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`) |
| `streamlit` | built from `Dockerfile.api` | **8501** | Original full-pipeline UI (`app.py`) |

## First start

```bash
# from the repo root — bash (WSL) or Git Bash:
bash scripts/make_dotenv.sh
#   …or in PowerShell:
# powershell -File scripts/make_dotenv.ps1

# EDIT .env: replace paste-your-nvidia-key-here with your key (https://build.nvidia.com)

docker compose up -d --build      # first build is long (docling/torch + Next.js build)
docker compose ps                 # wait until all show (healthy)
```

Then open:

- **Web UI**: http://localhost:3000
- **Streamlit UI**: http://localhost:8501 (paste your NVIDIA key in the sidebar if not in `.env`)
- **API docs**: http://localhost:8000/docs

## Health checks

```bash
docker compose ps                          # status column
docker compose logs -f api                 # follow a service
```

Each service has a Compose healthcheck: Postgres `pg_isready`, API `GET /api/health`,
Streamlit `GET /healthz`, web HTTP ping. Nothing depends on ArcadeDB being healthy —
it is opt-in at runtime; if its healthcheck shows unhealthy, check
`docker compose logs arcadedb`.

## Everyday commands

```bash
docker compose up -d              # start (after first build)
docker compose stop               # stop, keep data
docker compose down               # stop, remove containers (data volumes kept)
docker compose down -v            # ALSO delete Postgres/ArcadeDB data (irreversible)
docker compose up -d --build api  # rebuild one service after dependency changes
```

Code in `pipeline/`, `utils/`, `app.py`, and `apps/api/` is bind-mounted into the
`api`/`streamlit` containers (uvicorn runs with `--reload`), so Python edits only need:

```bash
docker compose restart api streamlit   # streamlit has no auto-reload
```

The `web` image has no bind mount — rebuild it after frontend changes:
`docker compose up -d --build web`.

## Running tests on the host

The DB ports are published, so host-side pytest/scripts work against the containers:

```bash
pip install -r requirements-dev.txt   # adds pytest, python-dotenv
pytest tests/ -q                      # uses POSTGRES_URL=postgresql://localhost:5433 from .env
```

## Troubleshooting

- **`POSTGRES_PASSWORD` error on `compose up`** — create `.env` first (see above).
- **Streamlit shows a DB exception at startup** — Postgres not healthy yet; `docker compose ps`,
  wait for `(healthy)`, then `docker compose restart streamlit`.
- **Web UI can't reach API from the browser** — `NEXT_PUBLIC_API_BASE_URL` is baked at build time;
  if the API is not at `http://localhost:8000` from the browser's perspective, rebuild:
  `docker compose build --build-arg NEXT_PUBLIC_API_BASE_URL=<browser-reachable-url> web`.
- **Slow first run analysis** — docling's first paper conversion is ~90s and the Quality Engine
  toggle needs it; the API and Streamlit boot fine without it.
- **LLM errors in runs** — key missing/invalid: check `NVIDIA_API_KEY` in `.env` was set
  *before* `docker compose up` (or paste it in the Streamlit sidebar).
