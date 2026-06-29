import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import dispose_engine
from app.main import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    await dispose_engine()
