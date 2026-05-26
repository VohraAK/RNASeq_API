import hashlib

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.services.auth import AuthError, decode_access_token


def _get_user_or_ip(request: Request) -> str:
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()}"
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            user_id = decode_access_token(auth[7:])
            return f"user:{user_id}"
        except AuthError:
            pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=_get_user_or_ip,
    default_limits=["100/minute"],
    storage_uri=settings.REDIS_URL,
)
