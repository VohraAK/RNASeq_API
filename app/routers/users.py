import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.api_key import APIKey
from app.models.user import User
from app.schemas.base import SuccessResponse
from app.schemas.users import (
    APIKeyCreateRequest,
    APIKeyCreatedResponse,
    APIKeyResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth import API_KEY_EXPIRE_DAYS, generate_api_key, hash_password

router = APIRouter(prefix="/users", tags=["users"])

_MAX_API_KEYS = 10


def _user_response(user: User) -> SuccessResponse[UserResponse]:
    return SuccessResponse(data=UserResponse(
        user_id=user.id,
        email=user.email,
        created_at=user.created_at,
        updated_at=user.updated_at,
    ))


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[UserResponse]:
    return _user_response(current_user)


@router.patch("/me")
async def update_me(
    body: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[UserResponse]:
    if body.email is not None and body.email != current_user.email:
        conflict = await db.scalar(select(User).where(User.email == body.email))
        if conflict is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "VALIDATION_ERROR", "message": "Email already in use."},
            )
        current_user.email = body.email

    if body.password is not None:
        current_user.password_hash = hash_password(body.password)

    await db.commit()
    await db.refresh(current_user)
    return _user_response(current_user)


@router.get("/me/api-keys")
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[list[APIKeyResponse]]:
    keys = await db.scalars(
        select(APIKey)
        .where(APIKey.user_id == current_user.id, APIKey.revoked_at.is_(None))
        .order_by(APIKey.created_at.desc())
    )
    return SuccessResponse(data=[
        APIKeyResponse(
            key_id=k.id,
            name=k.name,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
        )
        for k in keys
    ])


@router.post("/me/api-keys", status_code=201)
async def create_api_key(
    body: APIKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[APIKeyCreatedResponse]:
    active_count = await db.scalar(
        select(func.count())
        .select_from(APIKey)
        .where(APIKey.user_id == current_user.id, APIKey.revoked_at.is_(None))
    )
    if active_count >= _MAX_API_KEYS:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": f"Maximum of {_MAX_API_KEYS} active API keys allowed."},
        )

    raw_key, key_hash = generate_api_key()
    key = APIKey(
        user_id=current_user.id,
        name=body.name,
        key_hash=key_hash,
        expires_at=datetime.now(UTC) + timedelta(days=API_KEY_EXPIRE_DAYS),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return SuccessResponse(data=APIKeyCreatedResponse(
        key_id=key.id,
        name=key.name,
        raw_key=raw_key,
        created_at=key.created_at,
        expires_at=key.expires_at,
    ))


@router.delete("/me/api-keys/{key_id}", status_code=200)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[APIKeyResponse]:
    key = await db.scalar(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id)
    )
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"API key {key_id} does not exist or is not owned by you."},
        )
    if key.revoked_at is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "VALIDATION_ERROR", "message": "API key already revoked."},
        )
    key.revoked_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(key)
    return SuccessResponse(data=APIKeyResponse(
        key_id=key.id,
        name=key.name,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
    ))
