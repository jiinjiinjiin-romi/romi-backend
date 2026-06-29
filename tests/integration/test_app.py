from app.api.v1.endpoints.health import get_health_service
from app.core.config import Settings
from app.main import create_app
from app.services.health_service import DatabaseUnavailableError, HealthService


async def db_ok() -> None:
    return None


def get_test_health_service() -> HealthService:
    settings = Settings(
        mysql_password="test-password",
        model_path="missing-model-file.pth",
        gemini_api_key="",
        gemini_model="",
        email_provider="",
        email_host="",
        email_port="",
        email_username="",
        email_password="",
        email_from="",
    )
    return HealthService(settings=settings, db_checker=db_ok)


def test_create_app_succeeds() -> None:
    app = create_app()

    assert app.title == "driving-agent-api"


async def test_openapi_json_is_available(client) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200


async def test_swagger_docs_are_available(client) -> None:
    response = await client.get("/docs")

    assert response.status_code == 200


async def test_unknown_path_returns_404(client) -> None:
    response = await client.get("/api/v1/unknown")

    assert response.status_code == 404


async def test_response_includes_request_id(client) -> None:
    response = await client.get("/openapi.json")

    assert response.headers["X-Request-ID"]


async def test_response_reuses_provided_request_id(client) -> None:
    request_id = "request-id-from-client"

    response = await client.get("/openapi.json", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


async def test_health_returns_200_with_database_up(app, client) -> None:
    app.dependency_overrides[get_health_service] = get_test_health_service

    response = await client.get("/api/v1/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"]["database"] == "UP"
    assert payload["checkedAt"]


async def test_health_is_degraded_when_optional_services_are_unconfigured(app, client) -> None:
    app.dependency_overrides[get_health_service] = get_test_health_service

    response = await client.get("/api/v1/health")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "DEGRADED"
    assert payload["services"]["vitModel"] == "DOWN"
    assert payload["services"]["gemini"] == "DOWN"
    assert payload["services"]["email"] == "DOWN"


async def test_health_returns_common_error_when_database_is_down(app) -> None:
    class FailingHealthService:
        async def get_health(self):
            raise DatabaseUnavailableError("database unavailable")

    app.dependency_overrides[get_health_service] = lambda: FailingHealthService()

    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        response = await test_client.get("/api/v1/health")

    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": 503,
        "message": "데이터베이스에 연결할 수 없습니다.",
        "error": "DATABASE_UNAVAILABLE",
    }


async def test_openapi_registers_health_api(client) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
