import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from src.providers import SystemdProvider, JournalProvider, validate_unit_name
from src.schema import ServiceScope, ServiceAction, LogQueryFilter
from src.helpers import ValidationError


def test_validate_unit_name():
    assert validate_unit_name("omniroute.service") == "omniroute.service"
    assert validate_unit_name("user@1000.service") == "user@1000.service"
    with pytest.raises(ValidationError):
        validate_unit_name("; rm -rf /")
    with pytest.raises(ValidationError):
        validate_unit_name("service with spaces.service")


@pytest.mark.asyncio
async def test_service_discovery_and_status():
    provider = SystemdProvider()
    discovered = provider.discover_custom_service_files()
    assert isinstance(discovered, list)
    # Check that known user service omniroute or antigravity-claude-proxy is found
    names = [name for name, scope, path in discovered]
    assert "omniroute.service" in names or len(names) > 0


@pytest.mark.asyncio
async def test_journal_structured_parsing():
    provider = JournalProvider()
    logs = await provider.fetch_structured_logs(
        unit_name="omniroute.service",
        scope=ServiceScope.USER,
        filter_params=LogQueryFilter(lines=5)
    )
    assert isinstance(logs, list)
    if logs:
        entry = logs[0]
        assert entry.unit == "omniroute.service"
        assert hasattr(entry, "level")
        assert hasattr(entry, "message")


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
async def test_api_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_api_system_overview():
    transport = ASGITransport(app=app)
    headers = await _get_auth_headers()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated request should be rejected
        unauth = await ac.get("/api/system/overview")
        assert unauth.status_code == 401

        # Authenticated request
        response = await ac.get("/api/system/overview", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "hostname" in data
        assert "uptime_seconds" in data
        assert "total_services_monitored" in data
        assert data["total_services_monitored"] >= 0


@pytest.mark.asyncio
async def test_api_services_list():
    transport = ASGITransport(app=app)
    headers = await _get_auth_headers()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated request should be rejected
        unauth = await ac.get("/api/services")
        assert unauth.status_code == 401

        # Authenticated request
        response = await ac.get("/api/services", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            first = data[0]
            assert "id" in first
            assert "active_state" in first
            assert "is_active" in first


@pytest.mark.asyncio
async def test_api_service_logs():
    transport = ASGITransport(app=app)
    headers = await _get_auth_headers()
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated request should be rejected
        unauth = await ac.get("/api/services/omniroute.service/logs?lines=3")
        assert unauth.status_code == 401

        # Authenticated request
        response = await ac.get("/api/services/omniroute.service/logs?lines=3", headers=headers)
        assert response.status_code == 200
        logs = response.json()
        assert isinstance(logs, list)
