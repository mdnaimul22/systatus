import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_get_unit_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/services/omniroute.service/file")
        assert response.status_code == 200
        data = response.json()
        assert data["unit_name"] == "omniroute.service"
        assert "content" in data
        assert "[Service]" in data["content"] or "[Unit]" in data["content"]
        assert "is_writable" in data
        assert data["is_writable"] is True  # User service is writable by current user
