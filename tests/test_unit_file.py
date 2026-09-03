import pytest
from httpx import AsyncClient, ASGITransport
from main import app


async def _get_auth_headers():
    from src.config import Settings
    from src.helpers import init_db, session_scope
    from src.services.auth import sync_env_admin, create_token
    init_db(Settings.DATABASE_URL)
    async with session_scope() as session:
        user = await sync_env_admin(session)
        token = create_token(user.id)
        return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_unit_file():
    transport = ASGITransport(app=app)
    headers = await _get_auth_headers()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated request rejected
        unauth = await ac.get("/api/services/omniroute.service/file")
        assert unauth.status_code == 401

        response = await ac.get("/api/services/omniroute.service/file", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["unit_name"] == "omniroute.service"
        assert "content" in data
        assert "[Service]" in data["content"] or "[Unit]" in data["content"]
        assert "is_writable" in data
        assert data["is_writable"] is True  # User service is writable by current user
