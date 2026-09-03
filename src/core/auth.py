"""
Core — Authentication & User Database operations.
Accesses the database (UserRepository) using schema data contracts.
Blind to services, providers, and routers.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db import UserRepository, User, get_session
from src.schema.auth import UserProfileResponse


async def get_user_by_id(user_id: str, session: AsyncSession) -> User | None:
    """Retrieve user by primary key ID."""
    repo = UserRepository(session)
    return await repo.get(user_id)


async def get_user_by_identifier(identifier: str, session: AsyncSession) -> User | None:
    """Retrieve user by username or email."""
    repo = UserRepository(session)
    return await repo.find_by_identifier(identifier)


async def get_user_by_email(email: str, session: AsyncSession) -> User | None:
    """Retrieve user by email."""
    repo = UserRepository(session)
    return await repo.find_by_email(email)


async def get_user_by_username(username: str, session: AsyncSession) -> User | None:
    """Retrieve user by username."""
    repo = UserRepository(session)
    return await repo.find_by_username(username)


async def create_user(
    email: str,
    name: str,
    password_hash: str,
    session: AsyncSession,
    username: str | None = None,
    tier: str = "registered",
    user_id: str | None = None,
) -> User:
    """Persist a new user into the database."""
    repo = UserRepository(session)
    user = await repo.create_user(
        email=email,
        name=name,
        password_hash=password_hash,
        username=username,
        tier=tier,
        user_id=user_id,
    )
    await session.commit()
    await session.refresh(user)
    return user


async def sync_env_admin_record(
    session: AsyncSession,
    admin_user: str,
    admin_email: str,
    admin_name: str,
    password_hash: str,
) -> User:
    """
    Ensure admin record in database is synchronized with .env credentials.
    """
    repo = UserRepository(session)
    user = await repo.find_by_identifier(admin_user)
    if not user:
        user = await repo.find_by_email(admin_email)

    if not user:
        user = await repo.create_user(
            email=admin_email,
            name=admin_name,
            password_hash=password_hash,
            username=admin_user,
            tier="admin",
            user_id="admin",
        )
        await session.commit()
        await session.refresh(user)
    else:
        needs_commit = False
        if user.password_hash != password_hash:
            user.password_hash = password_hash
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

    return user


def to_user_profile(user: User) -> UserProfileResponse:
    """Map ORM User model to UserProfileResponse schema."""
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        username=user.username,
        tier=user.tier,
        created_at=user.created_at,
    )
