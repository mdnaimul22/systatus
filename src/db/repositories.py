"""
User Repository — extends BaseRepository with auth-specific queries.
"""

from __future__ import annotations

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.helpers import BaseRepository
from src.db.models import User


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def find_by_email(self, email: str) -> User | None:
        """Lookup user by email (case-insensitive)."""
        stmt = select(self.model).where(func.lower(self.model.email) == email.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_username(self, username: str) -> User | None:
        """Lookup user by username (case-insensitive)."""
        stmt = select(self.model).where(func.lower(self.model.username) == username.lower().strip())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_identifier(self, identifier: str) -> User | None:
        """Lookup user by username or email (case-insensitive)."""
        clean = identifier.lower().strip()
        stmt = select(self.model).where(
            or_(
                func.lower(self.model.email) == clean,
                func.lower(self.model.username) == clean,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        name: str,
        password_hash: str,
        username: str | None = None,
        tier: str = "registered",
        user_id: str | None = None,
    ) -> User:
        """Create a new user with pre-hashed password and optional username/tier."""
        kwargs = {
            "email": email.lower().strip(),
            "name": name.strip(),
            "password_hash": password_hash,
            "tier": tier,
        }
        if username:
            kwargs["username"] = username.lower().strip()
        if user_id:
            kwargs["id"] = user_id
        return await self.create(**kwargs)
