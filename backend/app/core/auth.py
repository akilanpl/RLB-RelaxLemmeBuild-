"""Authenticated request context and Supabase JWT verification."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping, Optional
from uuid import UUID

import httpx
import jwt
from fastapi import Header, HTTPException, status

from backend.app.core.config import get_settings


class AuthenticatedUserContext:
    def __init__(self, user_id: UUID, claims: Optional[Mapping[str, Any]] = None):
        self.user_id = user_id
        self.claims = dict(claims or {})


_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_lock = asyncio.Lock()
_ALLOWED_JWT_ALGORITHMS = {"RS256": "RSA", "ES256": "EC"}


def _supabase_auth_url() -> str:
    settings = get_settings()
    if not settings.SUPABASE_URL:
        raise ValueError("SUPABASE_URL is not configured")
    return settings.SUPABASE_URL.rstrip("/") + "/auth/v1"


def _jwks_url() -> str:
    return _supabase_auth_url() + "/.well-known/jwks.json"


async def _fetch_jwks(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise ValueError("Invalid JWKS response")
    return payload


async def _get_jwks(*, force_refresh: bool = False) -> dict[str, Any]:
    url = _jwks_url()
    settings = get_settings()
    now = time.monotonic()
    async with _jwks_lock:
        cached = _jwks_cache.get(url)
        if not force_refresh and cached and now - cached[0] < settings.SUPABASE_JWKS_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            document = await _fetch_jwks(url)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication key service unavailable.",
            ) from exc
        _jwks_cache[url] = (time.monotonic(), document)
        return document


async def _decode_and_verify(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_JWT_ALGORITHMS or not header.get("kid"):
            raise ValueError("Unsupported JWT header")
        document = await _get_jwks()
        key = next((key for key in document["keys"] if key.get("kid") == header["kid"]), None)
        if key is None:
            # Key rotation can make a valid token miss the cached document.
            document = await _get_jwks(force_refresh=True)
            key = next((item for item in document["keys"] if item.get("kid") == header["kid"]), None)
        if key is None:
            raise ValueError("Unknown signing key")
        if key.get("alg") not in (None, algorithm) or key.get("kty") != _ALLOWED_JWT_ALGORITHMS[algorithm]:
            raise ValueError("Signing key metadata does not match token algorithm")
        verification_key = jwt.algorithms.RSAAlgorithm.from_jwk(key) if algorithm == "RS256" else jwt.algorithms.ECAlgorithm.from_jwk(key)
        issuer = settings.SUPABASE_JWT_ISSUER or (_supabase_auth_url())
        claims = jwt.decode(
            token,
            verification_key,
            algorithms=[algorithm],
            audience=settings.SUPABASE_JWT_AUDIENCE,
            issuer=issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        if not isinstance(claims, dict):
            raise ValueError("Invalid claims")
        UUID(str(claims["sub"]))
        return claims
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_authenticated_user(
    authorization: Optional[str] = Header(None),
    x_user_id: Optional[str] = Header(None),
) -> AuthenticatedUserContext:
    """Resolve identity from a verified Supabase bearer token.

    ``x-user-id`` is retained only as an explicit local-development
    compatibility aid. It is never considered in production.
    """
    settings = get_settings()
    if authorization is not None:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
        token = authorization[7:].strip()
        if not token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
        claims = await _decode_and_verify(token)
        return AuthenticatedUserContext(UUID(str(claims["sub"])), claims)

    if settings.ENVIRONMENT != "production" and x_user_id:
        try:
            return AuthenticatedUserContext(UUID(x_user_id), {"development_header": True})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid x-user-id header format; must be UUID.") from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
