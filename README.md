# driving-agent backend

FastAPI backend for the `driving-agent` project.

The backend stores data in MySQL 8.4 with InnoDB, `utf8mb4`, and
`utf8mb4_0900_ai_ci`. Schema changes are managed only through Alembic migrations.
Do not use `Base.metadata.create_all()` for application schema management.

## Current Scope

- FastAPI application factory with lifespan startup/shutdown
- Pydantic Settings and `.env` support
- Async SQLAlchemy engine and `AsyncSession`
- Async Alembic migration environment
- SQLAlchemy models and Alembic migrations through phase 2:
  - accounts
  - driver profiles, saved places, and search histories
  - driving sessions, location samples, safety behavior events, interventions, and driver responses
  - agent conversations, agent messages, tool executions, and report exports
- Default admin account seed command
- `GET /api/v1/health`
- MVP `current_account` dependency backed by `DEFAULT_ADMIN_ACCOUNT_ID`
- `GET /api/v1/bootstrap`
- Driver Profile REST API:
  - `GET /api/v1/profiles`
  - `POST /api/v1/profiles`
  - `GET /api/v1/profiles/{profileId}`
  - `PATCH /api/v1/profiles/{profileId}`
  - `DELETE /api/v1/profiles/{profileId}`
  - `POST /api/v1/profiles/{profileId}/select`
- Saved Place REST API:
  - `GET /api/v1/profiles/{profileId}/saved-places`
  - `PUT /api/v1/profiles/{profileId}/saved-places/{placeType}`
  - `POST /api/v1/profiles/{profileId}/favorites`
  - `PATCH /api/v1/saved-places/{placeId}`
  - `DELETE /api/v1/saved-places/{placeId}`
- Search History REST API:
  - `GET /api/v1/profiles/{profileId}/search-histories`
  - `DELETE /api/v1/profiles/{profileId}/search-histories`
- Docker Compose stack for backend and MySQL
- Ruff, pytest, compileall, OpenAPI, and smoke checks

## Not Implemented Yet

- Login, JWT, passwords, roles, or authority management
- Account CRUD API
- Search History creation REST API
- Driving Session, Agent, Report, and Report Export APIs
- WebSocket
- ViT inference, Gemini calls, email delivery, report file generation, and risk policy services

The default admin account is only seed data for early development. It is not a
login account, has no password, and must not be treated as production
authentication. Never use development passwords in production.

## Requirements

- Python 3.12
- Docker Desktop
- Docker Compose
- Project dependencies managed by `pyproject.toml`

## Local Setup

```bash
python -m pip install -e ".[dev]"
```

Copy the example environment file before running Docker Compose:

```bash
cp .env.example .env
```

Do not commit `.env`.

## Docker Compose

Run from the project root, one directory above this backend folder:

```bash
docker compose config
docker compose up --build -d
docker compose ps
```

The backend waits for MySQL to become healthy. The backend container then runs:

```text
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If migration fails, seed and Uvicorn do not run. If seed fails, Uvicorn does not run.

## URLs

- Swagger: `http://localhost:8000/docs`
- OpenAPI: `http://localhost:8000/openapi.json`
- Health API: `http://localhost:8000/api/v1/health`
- Bootstrap API: `http://localhost:8000/api/v1/bootstrap`
- Profile API: `http://localhost:8000/api/v1/profiles`
- Saved Places API: `http://localhost:8000/api/v1/profiles/{profileId}/saved-places`
- Search Histories API: `http://localhost:8000/api/v1/profiles/{profileId}/search-histories`

## Profile API Example

```powershell
$body = @{
    displayName = "Codex Smoke"
    agentCallName = "Codex"
    reportEmail = "codex-smoke@example.com"
    agentPersonality = "FRIENDLY"
    warningSensitivity = "MEDIUM"
    ttsVoiceId = $null
    ttsSpeed = 1.0
    guidanceVolume = 70
    theme = "SYSTEM"
} | ConvertTo-Json

$profile = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/profiles" `
    -ContentType "application/json" `
    -Body $body

Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/select"
```

## Saved Place API Example

```powershell
$homeBody = @{
    label = "Smoke Home"
    provider = "KAKAO"
    providerPlaceId = "smoke-home-001"
    address = "서울특별시 광진구 능동로 209"
    latitude = 37.5501
    longitude = 127.0734
} | ConvertTo-Json

$home = Invoke-RestMethod `
    -Method Put `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/saved-places/HOME" `
    -ContentType "application/json" `
    -Body $homeBody

$favoriteBody = @{
    label = "Smoke Favorite"
    provider = "KAKAO"
    providerPlaceId = "smoke-favorite-001"
    address = "서울특별시 성동구 성수동"
    latitude = 37.5442
    longitude = 127.0557
} | ConvertTo-Json

$favorite = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/favorites" `
    -ContentType "application/json" `
    -Body $favoriteBody

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/saved-places"
```

## Search History API Example

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/search-histories?page=1&size=20"

Invoke-RestMethod `
    -Method Delete `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/search-histories"
```

Search history creation REST API is not defined yet. The latest-50 retention
policy is applied by the future writer that creates search history rows.

## Logs And Status

```bash
docker compose ps
docker compose logs --no-color mysql
docker compose logs --no-color backend
```

## Alembic

Upgrade to the latest revision:

```bash
docker compose exec backend alembic upgrade head
```

Show current revision:

```bash
docker compose exec backend alembic current
```

Create a new revision in later schema work:

```bash
docker compose exec backend alembic revision -m "describe change"
```

The first revision is `0001_create_accounts`.

Current migration chain:

```text
0001_create_accounts
0002_profile_place_tables
0003_driving_safety_tables
0004_agent_report_tables
```

`report_exports` is intentionally linked only to `driver_profiles`; there is no
direct report-to-driving-session join table in the current ERD. The active
driving session uniqueness rule uses a MySQL generated column and unique index.

## Seed

Run the seed manually:

```bash
docker compose exec backend python -m app.db.seed
```

The seed command:

- looks up `DEFAULT_ADMIN_ACCOUNT_ID`
- creates the account if it does not exist
- updates the email if the same ID already exists with a different email
- fails if the configured email is already used by another account
- can be run repeatedly without creating duplicate accounts

## Verification

```bash
docker compose exec backend ruff check .
docker compose exec backend pytest -ra
docker compose exec backend python -m compileall app
curl -i http://localhost:8000/api/v1/health
curl -i http://localhost:8000/api/v1/bootstrap
curl -i http://localhost:8000/api/v1/profiles
curl -i http://localhost:8000/docs
curl -i http://localhost:8000/openapi.json
```

Latest verified result on 2026-06-30:

```text
ruff check . -> passed
pytest -ra -> 146 passed
python -m compileall app -> passed
Saved Place MySQL Integration -> passed
Search History MySQL Integration -> passed
Concurrent fixed-place/favorite tests -> passed
Current working tree OpenAPI import check -> passed
Alembic current/head -> 0004_agent_report_tables
```

During the 3-2 implementation run, Docker image build completed but backend
container recreation failed with a Docker Desktop daemon `metadata.db`
input/output error. The live `localhost:8000` container was therefore not
replaced and PowerShell API smoke tests were not completed in that run.

## Stop Containers

```bash
docker compose down
```

Remove containers and the named MySQL volume only when it is safe to delete local
development data:

```bash
docker compose down -v
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
- `MYSQL_ROOT_PASSWORD`
- `DEFAULT_ADMIN_ACCOUNT_ID`
- `DEFAULT_ADMIN_EMAIL`
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
