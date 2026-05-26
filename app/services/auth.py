import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
API_KEY_EXPIRE_DAYS = 90


class AuthError(Exception):
    pass


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": int(expire.timestamp()), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("Token expired")
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc
    if payload.get("type") != "access":
        raise AuthError("Invalid token type")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("Invalid token subject") from exc


def create_refresh_token() -> tuple[str, str]:
    raw = secrets.token_hex(64)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def generate_api_key() -> tuple[str, str]:
    raw = "rnaseq_sk_" + secrets.token_hex(32)
    hashed = hash_api_key(raw)
    return raw, hashed


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
