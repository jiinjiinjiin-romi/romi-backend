# driving-agent backend

FastAPI backend bootstrap for the `driving-agent` project.

This first setup unit intentionally excludes database connections, Alembic configuration,
Docker files, health endpoints, domain APIs, WebSocket handlers, AI integrations, email,
reports, and risk policies.

## Requirements

- Python 3.12
- Dependencies managed by `pyproject.toml`

## Setup

```bash
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` for local overrides. Do not commit `.env`.

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

## Verify

```bash
ruff check .
pytest
python -m compileall app
```

## Docker Compose

From the project root, one directory above this backend folder:

```bash
cp .env.example .env
docker compose config
docker compose build
docker compose up -d
docker compose ps
```

The Compose stack starts:

- `mysql`: MySQL 8.4 with `utf8mb4` and `utf8mb4_0900_ai_ci`
- `backend`: FastAPI app on `http://localhost:8000`

The backend waits for the MySQL healthcheck, runs `alembic upgrade head`, and then starts
Uvicorn. This step has no SQLAlchemy entities or Alembic revisions yet, so no domain tables are
created.

Useful checks:

```bash
curl -i http://localhost:8000/api/v1/health
curl -i http://localhost:8000/docs
curl -i http://localhost:8000/openapi.json
docker compose exec backend alembic current
docker compose exec backend ruff check .
docker compose exec backend pytest
docker compose exec backend python -m compileall app
```

## Configuration

Settings are loaded from environment variables and `.env`.

- `APP_ENV`
- `APP_NAME`
- `API_V1_PREFIX`
- `WS_V1_PREFIX`
- `LOG_LEVEL`
- `SQL_ECHO`
- `DEMO_MODE`
- `CORS_ORIGINS`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MODEL_PATH`
- `MODEL_VERSION`
- `POLICY_VERSION`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `EMAIL_PROVIDER`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USERNAME`
- `EMAIL_PASSWORD`
- `EMAIL_FROM`
- `REPORT_STORAGE_PATH`

`CORS_ORIGINS` accepts either a comma-separated string or a JSON array string.
