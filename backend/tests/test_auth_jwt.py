"""Deterministic tests for Supabase JWT/JWKS authentication."""

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException

from backend.app.core import auth


@pytest.fixture
def signing_material(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    kid = "test-key"
    settings = type(
        "Settings",
        (),
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_JWT_ISSUER": None,
            "SUPABASE_JWT_AUDIENCE": "authenticated",
            "SUPABASE_JWKS_CACHE_TTL_SECONDS": 3600,
            "ENVIRONMENT": "production",
        },
    )()
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    auth._jwks_cache.clear()
    return private_key, {"keys": [{**json.loads(public_jwk), "kid": kid}]}, kid


@pytest.fixture
def es_signing_material(monkeypatch):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key())
    kid = "test-ec-key"
    settings = type(
        "Settings",
        (),
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_JWT_ISSUER": None,
            "SUPABASE_JWT_AUDIENCE": "authenticated",
            "SUPABASE_JWKS_CACHE_TTL_SECONDS": 3600,
            "ENVIRONMENT": "production",
        },
    )()
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    auth._jwks_cache.clear()
    return private_key, {"keys": [{**json.loads(public_jwk), "kid": kid, "alg": "ES256"}]}, kid


def _token(private_key, kid, user_id=None, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id or uuid4()),
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _es_token(private_key, kid, user_id=None, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id or uuid4()),
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})


@pytest.mark.asyncio
async def test_valid_token_is_verified_and_jwks_is_cached(signing_material, monkeypatch):
    private_key, jwks, kid = signing_material
    calls = 0

    async def fetch(_url):
        nonlocal calls
        calls += 1
        return jwks

    monkeypatch.setattr(auth, "_fetch_jwks", fetch)
    user_id = uuid4()
    token = _token(private_key, kid, user_id)

    first = await auth.get_authenticated_user(f"Bearer {token}")
    second = await auth.get_authenticated_user(f"Bearer {token}")
    assert first.user_id == second.user_id == user_id
    assert calls == 1


@pytest.mark.asyncio
async def test_valid_es256_token_is_verified(es_signing_material, monkeypatch):
    private_key, jwks, kid = es_signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    result = await auth.get_authenticated_user(f"Bearer {_es_token(private_key, kid)}")
    assert isinstance(result.user_id, UUID)


@pytest.mark.asyncio
async def test_unsupported_algorithm_is_rejected(signing_material, monkeypatch):
    private_key, jwks, kid = signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    token = jwt.encode(
        {"sub": str(uuid4()), "iss": "https://example.supabase.co/auth/v1", "aud": "authenticated",
         "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        private_key, algorithm="RS384", headers={"kid": kid},
    )
    with pytest.raises(HTTPException) as error:
        await auth.get_authenticated_user(f"Bearer {token}")
    assert error.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token_overrides",
    [
        {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        {"sub": None},
        {"iss": "https://other.example/auth/v1"},
        {"aud": "other-audience"},
    ],
)
async def test_expired_or_wrong_claims_are_rejected(signing_material, monkeypatch, token_overrides):
    private_key, jwks, kid = signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    token = _token(private_key, kid, **token_overrides)
    with pytest.raises(HTTPException) as error:
        await auth.get_authenticated_user(f"Bearer {token}")
    assert error.value.status_code == 401


async def _async_value(value):
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer", "Bearer not-a-jwt"])
async def test_missing_or_malformed_authentication_is_rejected(signing_material, authorization):
    with pytest.raises(HTTPException) as error:
        await auth.get_authenticated_user(authorization)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected(signing_material, monkeypatch):
    private_key, jwks, kid = signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(other_key, kid)
    with pytest.raises(HTTPException) as error:
        await auth.get_authenticated_user(f"Bearer {token}")
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_es256_signature_is_rejected(es_signing_material, monkeypatch):
    private_key, jwks, kid = es_signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    other_key = ec.generate_private_key(ec.SECP256R1())
    token = _es_token(other_key, kid)
    with pytest.raises(HTTPException) as error:
        await auth.get_authenticated_user(f"Bearer {token}")
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_x_user_id_cannot_impersonate_verified_token(signing_material, monkeypatch):
    private_key, jwks, kid = signing_material
    monkeypatch.setattr(auth, "_fetch_jwks", lambda _url: _async_value(jwks))
    real_user = uuid4()
    result = await auth.get_authenticated_user(
        f"Bearer {_token(private_key, kid, real_user)}",
        str(UUID(int=0)),
    )
    assert result.user_id == real_user
