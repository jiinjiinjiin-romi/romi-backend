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

## Configuration

Settings are loaded from environment variables and `.env`.

- `APP_ENV`
- `APP_NAME`
- `API_V1_PREFIX`
- `WS_V1_PREFIX`
- `LOG_LEVEL`
- `DEMO_MODE`
- `CORS_ORIGINS`
- `MODEL_PATH`
- `MODEL_VERSION`
- `POLICY_VERSION`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `EMAIL_PROVIDER`

`CORS_ORIGINS` accepts either a comma-separated string or a JSON array string.
