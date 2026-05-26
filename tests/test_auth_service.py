import uuid

import jwt
import pytest

from app.services.auth import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


# --- password hashing ---

def test_verify_password_correct():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("hunter2")
    assert verify_password("wrong", hashed) is False


def test_hash_is_not_plaintext():
    plain = "hunter2"
    assert hash_password(plain) != plain


def test_hash_is_nondeterministic():
    # bcrypt uses per-call salt
    assert hash_password("x") != hash_password("x")


# --- access token ---

def test_access_token_round_trip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    decoded_id = decode_access_token(token)
    assert decoded_id == user_id


def test_decode_garbage_token_raises_auth_error():
    with pytest.raises(AuthError):
        decode_access_token("not.a.token")


def test_decode_wrong_type_raises_auth_error():
    user_id = uuid.uuid4()
    from app.config import settings
    from datetime import UTC, datetime, timedelta
    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=15), "type": "refresh"}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(AuthError, match="type"):
        decode_access_token(token)


def test_decode_expired_token_raises_auth_error():
    user_id = uuid.uuid4()
    from app.config import settings
    from datetime import UTC, datetime, timedelta
    payload = {"sub": str(user_id), "exp": datetime.now(UTC) - timedelta(seconds=1), "type": "access"}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(AuthError):
        decode_access_token(token)


def test_decode_wrong_secret_raises_auth_error():
    user_id = uuid.uuid4()
    token = jwt.encode({"sub": str(user_id), "type": "access"}, "wrong-secret", algorithm="HS256")
    with pytest.raises(AuthError):
        decode_access_token(token)


# --- refresh token ---

def test_refresh_token_raw_hashes_to_stored():
    raw, hashed = create_refresh_token()
    import hashlib
    assert hashlib.sha256(raw.encode()).hexdigest() == hashed


def test_refresh_token_raw_is_not_hashed():
    raw, hashed = create_refresh_token()
    assert raw != hashed


def test_refresh_tokens_are_unique():
    raw1, _ = create_refresh_token()
    raw2, _ = create_refresh_token()
    assert raw1 != raw2


# --- API key ---

def test_api_key_format():
    raw, _ = generate_api_key()
    assert raw.startswith("rnaseq_sk_")
    suffix = raw[len("rnaseq_sk_"):]
    assert len(suffix) == 64
    assert all(c in "0123456789abcdef" for c in suffix)


def test_api_key_hash_differs_from_raw():
    raw, hashed = generate_api_key()
    assert raw != hashed


def test_api_key_hash_is_deterministic():
    raw, _ = generate_api_key()
    assert hash_api_key(raw) == hash_api_key(raw)


def test_api_keys_are_unique():
    raw1, _ = generate_api_key()
    raw2, _ = generate_api_key()
    assert raw1 != raw2


def test_generate_api_key_stored_hash_matches():
    raw, hashed = generate_api_key()
    assert hash_api_key(raw) == hashed
