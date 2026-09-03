"""
Router — Authentication (Register / Login / Profile / Sudo).
Exposes HTTP endpoints by consuming auth services and schema contracts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.schema.auth import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    UserProfileResponse,
)
from src.schema import SudoVerifyRequest
from src.services import auth_service, get_current_user
from src.services.auth import User, get_session
from src.helpers.rate_limit import RateLimiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

_register_limiter = RateLimiter(max_calls=3, window_seconds=60)
_login_limiter = RateLimiter(max_calls=5, window_seconds=60)


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, request: Request, session: AsyncSession = Depends(get_session)):
    """Create a new user account."""
    _register_limiter.check(request)
    return await auth_service.register(body, session)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request, session: AsyncSession = Depends(get_session)):
    """Authenticate and get JWT token."""
    _login_limiter.check(request)
    return await auth_service.login(body, session)


@router.get("/me", response_model=UserProfileResponse)
async def me(
    user: User = Depends(get_current_user),
):
    """Get current authenticated user profile."""
    return auth_service.get_profile(user)


@router.get("/sudo-status", summary="Check if passwordless sudo is available")
async def get_sudo_status(
    _user: User = Depends(get_current_user),
):
    from src.helpers import is_passwordless_sudo_available
    nopasswd = await is_passwordless_sudo_available()
    return {"nopasswd": nopasswd}


@router.post("/sudo-verify", summary="Verify candidate sudo password")
async def verify_sudo(
    payload: SudoVerifyRequest,
    _user: User = Depends(get_current_user),
):
    from src.helpers import verify_sudo_password, SudoInvalidPasswordError
    valid = await verify_sudo_password(payload.sudo_password)
    if not valid:
        raise SudoInvalidPasswordError()
    return {"valid": True, "message": "Sudo authentication confirmed"}
