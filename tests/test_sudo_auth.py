import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from src.helpers import is_passwordless_sudo_available


@pytest.mark.asyncio
async def test_is_passwordless_sudo_helper():
    res = await is_passwordless_sudo_available()
    assert isinstance(res, bool)


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
async def test_api_sudo_status():
    transport = ASGITransport(app=app)
    headers = await _get_auth_headers()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated request rejected
        unauth = await ac.get("/api/auth/sudo-status")
        assert unauth.status_code == 401

        res = await ac.get("/api/auth/sudo-status", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "nopasswd" in data
        assert isinstance(data["nopasswd"], bool)


@pytest.mark.asyncio
async def test_api_sudo_verify_empty():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/api/auth/sudo-verify", json={"sudo_password": ""})
        assert res.status_code in (401, 400, 422)
