"""
Service — Authentication.
"""

from __future__ import annotations

import hmac
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, setup_logger
from src.core.auth import hash_password, verify_password, create_token
from src.helpers import ConflictError, AuthenticationError
from src.db import UserRepository, User

logger = setup_logger(Settings.LOG_DIR / "service.log", name="app.services.auth")


async def sync_env_admin(session: AsyncSession) -> User | None:
    """
    Ensure the admin user configured in Settings (.env) exists in the database.
    If the password or details in .env changed, update them in the database.
    """
    admin_user = (Settings.AUTH_USERNAME or "").strip()
    admin_pass = (Settings.AUTH_PASSWORD or "").strip()
    if not admin_user or not admin_pass:
        return None

    repo = UserRepository(session)
    admin_email = (Settings.AUTH_EMAIL or f"{admin_user}@systatus.local").strip().lower()
    admin_name = (Settings.AUTH_NAME or admin_user.capitalize()).strip()

    user = await repo.find_by_identifier(admin_user)
    if not user:
        user = await repo.find_by_email(admin_email)

    hashed = await hash_password(admin_pass)

    if not user:
        user = await repo.create_user(
            email=admin_email,
            name=admin_name,
            password_hash=hashed,
            username=admin_user,
            tier="admin",
            user_id="admin",
        )
        await session.commit()
        await session.refresh(user)
        logger.info(f"Initialized admin user '{admin_user}' from .env configuration")
    else:
        needs_commit = False
        if not await verify_password(admin_pass, user.password_hash):
            user.password_hash = hashed
            needs_commit = True
        if user.name != admin_name:
            user.name = admin_name
            needs_commit = True
        if user.tier != "admin":
            user.tier = "admin"
            needs_commit = True
        if user.username != admin_user:
            user.username = admin_user
            needs_commit = True

        if needs_commit:
            await session.commit()
            await session.refresh(user)
            logger.info(f"Synchronized admin user '{admin_user}' with .env configuration")

    return user


async def register(
    email: str,
    name: str,
    password: str,
    session: AsyncSession,
    username: str | None = None,
) -> dict:
    """Register a new user. Returns token + user info."""
    repo = UserRepository(session)

    existing = await repo.find_by_email(email)
    if existing:
        raise ConflictError(f"Email already registered: {email}")

    if username:
        existing_username = await repo.find_by_username(username)
        if existing_username:
            raise ConflictError(f"Username already taken: {username}")

    hashed = await hash_password(password)
    user = await repo.create_user(
        email=email,
        name=name,
        password_hash=hashed,
        username=username,
    )
    await session.commit()
    await session.refresh(user)

    token = create_token(user.id)
    logger.info(f"User registered: {user.email} (id={user.id})")
    return {
        "token": token,
        "user_id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
    }


async def login(identifier: str, password: str, session: AsyncSession) -> dict:
    """Authenticate user with username/email and password, checking .env first."""
    repo = UserRepository(session)
    clean_id = identifier.strip().lower()

    # 1. Check against .env credentials
    env_user = (Settings.AUTH_USERNAME or "").strip().lower()
    env_email = (Settings.AUTH_EMAIL or "").strip().lower()
    env_pass = Settings.AUTH_PASSWORD or ""

    if env_user and clean_id in (env_user, env_email):
        if hmac.compare_digest(password, env_pass):
            user = await sync_env_admin(session)
            if user:
                token = create_token(user.id)
                logger.info(f"Admin logged in via .env credentials: {user.username or user.email}")
                return {
                    "token": token,
                    "user_id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email,
                }

    # 2. Check existing database users
    user = await repo.find_by_identifier(clean_id)
    if not user or not await verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid username or password")

    token = create_token(user.id)
    logger.info(f"User logged in: {user.username or user.email}")
    return {
        "token": token,
        "user_id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
    }
