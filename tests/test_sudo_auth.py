import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from src.helpers import is_passwordless_sudo_available


@pytest.mark.asyncio
async def test_is_passwordless_sudo_helper():
    res = await is_passwordless_sudo_available()
    assert isinstance(res, bool)


@pytest.mark.asyncio
async def test_api_sudo_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/api/auth/sudo-status")
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
