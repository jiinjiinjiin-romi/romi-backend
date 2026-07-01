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
- Driving Session REST API:
  - `POST /api/v1/driving-sessions`
  - `GET /api/v1/driving-sessions/active`
  - `GET /api/v1/driving-sessions/{sessionId}`
  - `GET /api/v1/driving-sessions/{sessionId}/timeline`
  - `GET /api/v1/driving-sessions/{sessionId}/locations`
  - `POST /api/v1/driving-sessions/{sessionId}/end`
  - `GET /api/v1/profiles/{profileId}/driving-sessions`
- Agent Conversation REST API:
  - `POST /api/v1/driving-sessions/{sessionId}/agent/conversations`
  - `GET /api/v1/agent/conversations/{conversationId}`
- Report Read REST API:
  - `GET /api/v1/profiles/{profileId}/reports/summary`
  - `GET /api/v1/profiles/{profileId}/reports/behavior-events`
  - `GET /api/v1/profiles/{profileId}/reports/sessions`
- Driving Session WebSocket connection foundation:
  - `WS /ws/v1/driving-sessions/{sessionId}`
  - accept-before validation, SESSION_READY, PING/PONG heartbeat, duplicate replacement
  - `LOCATION_UPDATE` receive path, runtime location state, driving-state policy, and throttled `location_samples` persistence
- REST 3-6 integration, regression, and OpenAPI contract verification
- Docker Compose stack for backend and MySQL
- Ruff, pytest, compileall, OpenAPI, and smoke checks

## Not Implemented Yet

- Login, JWT, passwords, roles, or authority management
- Account CRUD API
- Search History creation REST API
- Agent messages, Gemini handling, ToolExecution handling, and Report Export APIs
- WebSocket FRAME_META, binary JPEG, ViT inference, DETECTION_UPDATE, and Agent utterance handling
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
- Driving Session API: `http://localhost:8000/api/v1/driving-sessions`
- Driving Session History API: `http://localhost:8000/api/v1/profiles/{profileId}/driving-sessions`
- Agent Conversation API: `http://localhost:8000/api/v1/driving-sessions/{sessionId}/agent/conversations`
- Agent Conversation Detail API: `http://localhost:8000/api/v1/agent/conversations/{conversationId}`
- Report Summary API: `http://localhost:8000/api/v1/profiles/{profileId}/reports/summary`
- Report Behavior API: `http://localhost:8000/api/v1/profiles/{profileId}/reports/behavior-events`
- Report Sessions API: `http://localhost:8000/api/v1/profiles/{profileId}/reports/sessions`
- Driving Session WebSocket: `ws://localhost:8000/ws/v1/driving-sessions/{sessionId}`

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

## Driving Session API Example

`POST /api/v1/driving-sessions` checks ViT model readiness through the existing
health capability path. If `/app/artifacts/models/best_vit.pth` is absent, the
start request returns `503 MODEL_NOT_AVAILABLE`.

```powershell
$startBody = @{
    profileId = $profile.id
    startLocation = @{
        latitude = 37.5501
        longitude = 127.0734
    }
    destination = @{
        providerPlaceId = "smoke-destination-001"
        name = "Smoke Destination"
        latitude = 37.5510
        longitude = 127.0737
    }
} | ConvertTo-Json -Depth 4

$session = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/driving-sessions" `
    -ContentType "application/json" `
    -Body $startBody

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/driving-sessions/active?profileId=$($profile.id)"

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/driving-sessions/$($session.id)"

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/driving-sessions/$($session.id)/timeline"

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/driving-sessions/$($session.id)/locations?limit=1000"

$endBody = @{
    endReason = "USER_REQUEST"
    endLocation = @{
        latitude = 37.5602
        longitude = 127.0811
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/driving-sessions/$($session.id)/end" `
    -ContentType "application/json" `
    -Body $endBody

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/driving-sessions?page=1&size=20"
```

## Driving Session WebSocket

`WS /ws/v1/driving-sessions/{sessionId}` accepts only owned ACTIVE sessions and
checks ViT readiness before `accept()`. Handshake failures return the common JSON
error shape as HTTP denial responses:

```text
422 INVALID_SESSION_ID
404 SESSION_NOT_FOUND
409 SESSION_NOT_ACTIVE
503 MODEL_NOT_AVAILABLE
```

The first successful server message is `SESSION_READY`:

```json
{
  "type": "SESSION_READY",
  "occurredAt": "2026-06-28T03:10:00.000000Z",
  "payload": {
    "sessionId": "67371b45-204c-4d87-b8f7-8a334229a41e",
    "modelVersion": "vit-dms-1.0.0",
    "policyVersion": "risk-policy-1.0.0",
    "recommendedFrameFps": 5,
    "locationIntervalMs": 1000,
    "heartbeatIntervalMs": 10000
  }
}
```

Server PING and client PONG are JSON application messages. The default heartbeat
interval is 10 seconds and timeout is 30 seconds; timeout closes with `4008`.
A second WebSocket for the same session replaces the first and closes the old
connection with `4001`. WebSocket disconnect does not end the DrivingSession;
use `POST /api/v1/driving-sessions/{sessionId}/end` for that.

Clients may send silent `LOCATION_UPDATE` messages:

```json
{
  "type": "LOCATION_UPDATE",
  "requestId": "48dc5bde-31c7-478a-a0a0-e9e30b78899b",
  "occurredAt": "2026-06-28T03:10:10.000000Z",
  "payload": {
    "latitude": 37.5501,
    "longitude": 127.0734,
    "speedKph": 32.4,
    "accuracyMeters": 8.2,
    "source": "GPS"
  }
}
```

`occurredAt` must be timezone-aware and is normalized to UTC. Runtime state is
updated for every fresh valid location. The first valid location is persisted
immediately; later samples persist only when the server monotonic clock has
advanced by `WS_LOCATION_PERSIST_INTERVAL_MS` since the last successful
persistence. Normal updates do not send ACK messages. Invalid location payloads
send recoverable `INVALID_LOCATION_UPDATE` and keep the socket open. Older
locations send recoverable `STALE_LOCATION_UPDATE`; duplicate `occurredAt`
values are ignored silently. DB persistence failures send recoverable
`LOCATION_PERSIST_FAILED` and leave runtime state intact for retry. If a session
is no longer ACTIVE at a persist point, the server sends `SESSION_NOT_ACTIVE`
with `recoverable=false` and closes with `1008`.

Driving state for LOCATION_UPDATE is currently:

```text
accuracyMeters > DRIVING_LOCATION_MAX_ACCURACY_METERS -> UNKNOWN
speedKph is null -> UNKNOWN
speedKph >= DRIVING_MOVING_SPEED_THRESHOLD_KPH -> MOVING
0 <= speedKph < DRIVING_MOVING_SPEED_THRESHOLD_KPH -> TEMPORARY_STOP
```

`PARKED` is not generated from LOCATION_UPDATE in this phase.

Local development commonly has ViT DOWN because `/app/artifacts/models/best_vit.pth`
is absent, so live successful `SESSION_READY` smoke may be unavailable. The
success path is covered by the MySQL WebSocket integration tests with explicit
fake readiness.

## Agent Conversation API Example

This endpoint starts a new general Agent conversation container for an existing
ACTIVE driving session. It creates one `agent_conversations` row only; Agent
messages, Tool executions, Gemini calls, and WebSocket utterance handling are
future steps.

```powershell
$conversationBody = @{
    mode = "GENERAL_ASSISTANT"
} | ConvertTo-Json

$conversation = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/driving-sessions/$($session.id)/agent/conversations" `
    -ContentType "application/json" `
    -Body $conversationBody

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/agent/conversations/$($conversation.id)"
```

## Report Read API Example

Report dates are Asia/Seoul calendar dates. The backend converts them to UTC
half-open `started_at` bounds and includes only `COMPLETED` and `ABORTED`
sessions. These endpoints are read-only and do not create `report_exports` rows.

```powershell
Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/reports/summary?periodStart=2026-01-01&periodEnd=2026-12-31"

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/reports/behavior-events?periodStart=2026-01-01&periodEnd=2026-12-31&behaviorTypes=DROWSINESS,PHONE_USE"

Invoke-RestMethod `
    -Method Get `
    -Uri "http://localhost:8000/api/v1/profiles/$($profile.id)/reports/sessions?periodStart=2026-01-01&periodEnd=2026-12-31&page=1&size=20"
```

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

Latest verified result on 2026-07-01 KST:

```text
Docker Compose verification -> backend/mysql healthy with current working tree
Docker host port override used for this verification: BACKEND_EXPOSED_PORT=8001, MYSQL_EXPOSED_PORT=3308
docker compose exec backend ruff check . -> passed
docker compose exec backend python -m compileall app -> passed
docker compose exec backend pytest -ra -> 338 passed, 0 skipped, 1 warning
4-2 targeted Docker pytest -> 76 passed, 0 skipped, 1 warning
MySQL-gated tests -> executed inside Docker Compose; no MYSQL_HOST/MYSQL_PASSWORD skip remains
Live smoke -> health 200 DEGRADED with database UP, bootstrap 200, Swagger /docs 200, OpenAPI 200
OpenAPI live check -> 27 REST method/path contracts present and WebSocket path absent from REST paths
tzdata/ZoneInfo smoke -> tzdata 2026.2 and ZoneInfo("Asia/Seoul") passed
OpenAPI Contract Test -> passed
REST E2E Integration -> passed
Saved Place MySQL Integration -> passed
Search History MySQL Integration -> passed
Driving Session MySQL/API Integration -> passed
Driving Session concurrent start Integration -> passed
Driving Session Timeline/Location MySQL Integration -> passed
Agent Conversation MySQL/API Integration -> passed
Agent Conversation Detail MySQL/API Integration -> passed
Agent Conversation Detail N+1 guard -> 2 fixed SELECT statements
Agent Conversation POST -> GET messages=[] flow -> passed
Report Summary/Behavior/Sessions MySQL Integration -> passed
WebSocket Protocol Unit -> passed
ConnectionManager Unit -> passed
SessionRuntime Unit -> passed
Heartbeat Unit -> passed
Driving Session WebSocket MySQL Integration -> passed
Report Period Unit -> passed
Report Sessions N+1 guard -> 2 fixed report-table SELECT statements
REST 3-6 ownership isolation regression -> passed
REST 3-6 common error/204/camelCase/UTC Z regression -> passed
REST 3-6 cascade cleanup regression -> passed
Session end conversation-abort regression -> passed
Concurrent fixed-place/favorite tests -> passed
PowerShell smoke -> health DEGRADED with database UP and vitModel/Gemini/email DOWN
PowerShell smoke -> bootstrap and profiles returned 200
Live WebSocket smoke -> invalid sessionId returned HTTP 422 INVALID_SESSION_ID JSON denial
Live WebSocket smoke -> random missing session returned HTTP 404 SESSION_NOT_FOUND JSON denial
Live SESSION_READY smoke -> skipped because local ViT model is DOWN and no prepared live ACTIVE session was created
OpenAPI live check -> current 27 REST method/path contracts present
OpenAPI live check -> /ws/v1/driving-sessions/{sessionId} absent from REST paths
Swagger /docs -> 200 OK
Alembic current/head -> 0004_agent_report_tables
```

No Alembic revision was created for 4-2, and the DB schema did not change.
safetyScore is intentionally nullable until the future risk/safety score policy
is implemented. The report read APIs aggregate stored data on request. Report
Export, PDF rendering, file download, email sending, Agent message creation,
Tool executions, Gemini handling, Demo APIs, FRAME_META, Binary
JPEG, ViT inference, and WebSocket utterance handling remain future work.

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
- `WS_RECOMMENDED_FRAME_FPS`
- `WS_LOCATION_INTERVAL_MS`
- `WS_LOCATION_PERSIST_INTERVAL_MS`
- `WS_HEARTBEAT_INTERVAL_MS`
- `WS_HEARTBEAT_TIMEOUT_MS`
- `DRIVING_MOVING_SPEED_THRESHOLD_KPH`
- `DRIVING_LOCATION_MAX_ACCURACY_METERS`
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
