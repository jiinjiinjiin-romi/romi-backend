from app.main import create_app


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
