"""
Service — Authentication & Cryptography.
Handles password hashing (bcrypt), token issuance/decoding (JWT),
credential verification against .env, and exposes auth workflows and dependencies to routers.
"""

from __future__ import annotations

import asyncio
import hmac
from datetime import timedelta
import bcrypt
import jwt
from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, setup_logger
from src.core import auth as core_auth
from src.core.auth import User, get_session
from src.schema.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileResponse,
)
from src.helpers import (
    ConflictError,
    AuthenticationError,
    time_now,
)

logger = setup_logger(Settings.LOG_DIR / "service.log", name="app.services.auth")


# ── Encryption & Decryption ──────────────────────────────────────────

async def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt asynchronously."""
    return await asyncio.to_thread(
        lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    )


async def verify_password(password: str, hashed: str) -> bool:
    """Compare plaintext against stored bcrypt hash asynchronously."""
    return await asyncio.to_thread(
        lambda: bcrypt.checkpw(password.encode(), hashed.encode())
    )


def create_token(user_id: str) -> str:
    """Create a JWT token for a given user_id."""
    payload = {
        "sub": user_id,
        "exp": time_now() + timedelta(hours=Settings.JWT_EXPIRY_HOURS),
        "iat": time_now(),
    }
    return jwt.encode(payload, Settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> str:
    """Decode JWT and return user_id. Raises AuthenticationError on invalid/expired."""
    try:
        payload = jwt.decode(token, Settings.JWT_SECRET, algorithms=["HS256"])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token: missing subject")
        return user_id
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid token. Please log in again.")


# ── FastAPI Dependencies Exposed to Routers ──────────────────────────

async def get_current_user(
    authorization: str | None = Header(None),
    token_query: str | None = Query(None, alias="token"),
    session: AsyncSession = Depends(get_session),
) -> User:
    """
    FastAPI dependency — extracts authenticated user from Authorization header or ?token= query param.
    Usage: user: User = Depends(get_current_user)
    """
    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    elif token_query:
        token = token_query.strip()

    if not token:
        raise AuthenticationError("Authentication required. Missing token.")

    user_id = decode_token(token)
    user = await core_auth.get_user_by_id(user_id, session)
    if not user:
        raise AuthenticationError("User not found or session has expired.")
    return user


async def get_optional_user(
    authorization: str | None = Header(None),
    token_query: str | None = Query(None, alias="token"),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """FastAPI dependency — returns User if token provided and valid, None otherwise."""
    try:
        return await get_current_user(authorization, token_query, session)
    except Exception:
        return None


# ── Business Workflows ───────────────────────────────────────────────

async def sync_env_admin(session: AsyncSession) -> User | None:
    """Synchronize admin credentials from .env Settings with database."""
    admin_user = (Settings.AUTH_USERNAME or "").strip()
    admin_pass = (Settings.AUTH_PASSWORD or "").strip()
    if not admin_user or not admin_pass:
        return None

    admin_email = (Settings.AUTH_EMAIL or f"{admin_user}@systatus.local").strip().lower()
    admin_name = (Settings.AUTH_NAME or admin_user.capitalize()).strip()

    # Encrypt password from .env
    hashed = await hash_password(admin_pass)

    user = await core_auth.sync_env_admin_record(
        session=session,
        admin_user=admin_user,
        admin_email=admin_email,
        admin_name=admin_name,
        password_hash=hashed,
    )
    logger.info(f"Admin user '{admin_user}' synchronized with .env configuration")
    return user


async def login(body: LoginRequest, session: AsyncSession) -> TokenResponse:
    """Authenticate user with credentials, checking .env first."""
    clean_id = body.username.strip().lower()

    # 1. Check against .env credentials
    env_user = (Settings.AUTH_USERNAME or "").strip().lower()
    env_email = (Settings.AUTH_EMAIL or "").strip().lower()
    env_pass = Settings.AUTH_PASSWORD or ""

    if env_user and clean_id in (env_user, env_email):
        if hmac.compare_digest(body.password, env_pass):
            user = await sync_env_admin(session)
            if user:
                token = create_token(user.id)
                logger.info(f"Admin logged in via .env credentials: {user.username or user.email}")
                return TokenResponse(
                    token=token,
                    user_id=user.id,
                    name=user.name,
                    username=user.username,
                    email=user.email,
                )

    # 2. Check database users via core_auth
    user = await core_auth.get_user_by_identifier(clean_id, session)
    if not user or not await verify_password(body.password, user.password_hash):
        raise AuthenticationError("Invalid username or password")

    token = create_token(user.id)
    logger.info(f"User logged in: {user.username or user.email}")
    return TokenResponse(
        token=token,
        user_id=user.id,
        name=user.name,
        username=user.username,
        email=user.email,
    )


async def register(body: RegisterRequest, session: AsyncSession) -> TokenResponse:
    """Register a new user."""
    existing = await core_auth.get_user_by_email(body.email, session)
    if existing:
        raise ConflictError(f"Email already registered: {body.email}")

    if body.username:
        existing_u = await core_auth.get_user_by_username(body.username, session)
        if existing_u:
            raise ConflictError(f"Username already taken: {body.username}")

    hashed = await hash_password(body.password)
    user = await core_auth.create_user(
        email=body.email,
        name=body.name,
        password_hash=hashed,
        username=body.username,
        session=session,
    )

    token = create_token(user.id)
    logger.info(f"User registered: {user.email} (id={user.id})")
    return TokenResponse(
        token=token,
        user_id=user.id,
        name=user.name,
        username=user.username,
        email=user.email,
    )


def get_profile(user: User) -> UserProfileResponse:
    """Map User model to UserProfileResponse schema."""
    return core_auth.to_user_profile(user)
