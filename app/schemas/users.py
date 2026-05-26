import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    created_at: datetime
    updated_at: datetime


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)


class APIKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class APIKeyCreatedResponse(BaseModel):
    key_id: uuid.UUID
    name: str
    raw_key: str
    created_at: datetime
    expires_at: datetime


class APIKeyResponse(BaseModel):
    key_id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime
