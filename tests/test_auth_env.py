import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from src.config import Settings
from src.helpers import session_scope, init_db, connection
from src.db.models import Base
from src.services.auth import sync_env_admin


@pytest.mark.asyncio
async def test_env_admin_sync_and_login():
    # 0. Initialize database
    init_db(Settings.DATABASE_URL)
    async with connection._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1. Sync admin user from .env settings
    async with session_scope() as session:
        user = await sync_env_admin(session)
        assert user is not None
        assert user.username == Settings.AUTH_USERNAME
        assert user.tier == "admin"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 2. Login with valid .env credentials (username + password)
        login_res = await ac.post(
            "/api/auth/login",
            json={
                "username": Settings.AUTH_USERNAME,
                "password": Settings.AUTH_PASSWORD,
            },
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert "token" in data
        assert data["name"] == Settings.AUTH_NAME
        token = data["token"]

        # 3. Access /api/auth/me with issued token
        me_res = await ac.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["username"] == Settings.AUTH_USERNAME
        assert me_data["tier"] == "admin"

        # 4. Login with incorrect password returns 401
        bad_login = await ac.post(
            "/api/auth/login",
            json={
                "username": Settings.AUTH_USERNAME,
                "password": "wrongpassword123",
            },
        )
        assert bad_login.status_code == 401

        # 5. Login with email instead of username
        email_login = await ac.post(
            "/api/auth/login",
            json={
                "email": Settings.AUTH_EMAIL,
                "password": Settings.AUTH_PASSWORD,
            },
        )
        assert email_login.status_code == 200
        assert "token" in email_login.json()

        # 6. Verify unauthenticated requests to protected endpoints return 401
        unauth_services = await ac.get("/api/services")
        assert unauth_services.status_code == 401

        unauth_system = await ac.get("/api/system/overview")
        assert unauth_system.status_code == 401

        # 7. Verify authenticated requests to protected endpoints return 200
        auth_services = await ac.get(
            "/api/services",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert auth_services.status_code == 200

        auth_system = await ac.get(
            "/api/system/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert auth_system.status_code == 200

