import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.limiter import limiter
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse
from app.schemas.base import SuccessResponse
from app.services.auth import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "refresh_token"
_AUTH_LIMIT = "10 per 15 minutes"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=raw_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, httponly=True, secure=settings.COOKIE_SECURE, samesite="lax")


@router.post("/register", status_code=201)
@limiter.limit(_AUTH_LIMIT)
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[RegisterResponse]:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "VALIDATION_ERROR", "message": "Email already registered."},
        )
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return SuccessResponse(data=RegisterResponse(user_id=user.id, email=user.email))


@router.post("/login")
@limiter.limit(_AUTH_LIMIT)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[TokenResponse]:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid credentials."},
        )
    access_token = create_access_token(user.id)
    raw_refresh, refresh_hash = create_refresh_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.commit()
    _set_refresh_cookie(response, raw_refresh)
    return SuccessResponse(data=TokenResponse(access_token=access_token))


@router.post("/refresh")
@limiter.limit(_AUTH_LIMIT)
async def refresh_token(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[TokenResponse]:
    if refresh_token is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "No refresh token."},
        )
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    now = datetime.now(UTC)
    stored = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )
    if stored is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or expired refresh token."},
        )
    new_raw, new_hash = create_refresh_token()
    stored.revoked_at = now
    db.add(RefreshToken(
        user_id=stored.user_id,
        token_hash=new_hash,
        expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    await db.commit()
    _set_refresh_cookie(response, new_raw)
    return SuccessResponse(data=TokenResponse(access_token=create_access_token(stored.user_id)))


@router.post("/logout")
@limiter.limit(_AUTH_LIMIT)
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse[dict]:
    if refresh_token is not None:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if stored is not None:
            stored.revoked_at = datetime.now(UTC)
            await db.commit()
    _clear_refresh_cookie(response)
    return SuccessResponse(data={"message": "Logged out."})
