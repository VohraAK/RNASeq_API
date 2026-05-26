import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.api_key import APIKey
from app.models.user import User
from app.services.auth import AuthError, decode_access_token


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "UNAUTHORIZED", "message": "Authentication required."},
    )


async def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if x_api_key is not None:
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        now = datetime.now(UTC)
        api_key = await db.scalar(
            select(APIKey).where(
                APIKey.key_hash == key_hash,
                APIKey.revoked_at.is_(None),
                APIKey.expires_at > now,
            )
        )
        if api_key is None:
            raise _unauthorized()
        api_key.last_used_at = now
        await db.commit()
        user = await db.get(User, api_key.user_id)
        if user is None:
            raise _unauthorized()
        return user

    if authorization is not None and authorization.startswith("Bearer "):
        token = authorization[7:]
        try:
            user_id = decode_access_token(token)
        except AuthError:
            raise _unauthorized()
        user = await db.get(User, user_id)
        if user is None:
            raise _unauthorized()
        return user

    raise _unauthorized()
