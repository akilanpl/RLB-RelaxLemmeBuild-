"""Backend-only encryption and safe presentation of provider credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.core.config import get_settings


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: str
    iv: str
    tag: str


class CredentialService:
    """Encrypts keys with AES-256-GCM; plaintext never leaves this service."""

    def __init__(self, key: str | bytes | None = None):
        raw = key or get_settings().CREDENTIAL_ENCRYPTION_KEY
        if not raw:
            if get_settings().ENVIRONMENT == "production":
                raise ValueError("CREDENTIAL_ENCRYPTION_KEY is required")
            # Development convenience only; production always requires an injected key.
            raw = hashlib.sha256(b"local-development-credential-key").digest()
        if isinstance(raw, str):
            try:
                raw = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            except (ValueError, base64.binascii.Error):
                raw = raw.encode()
        if len(raw) != 32:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes")
        self._key = bytes(raw)

    def encrypt(self, plaintext: str) -> EncryptedSecret:
        iv = secrets.token_bytes(12)
        blob = AESGCM(self._key).encrypt(iv, plaintext.encode(), None)
        return EncryptedSecret(
            ciphertext=base64.urlsafe_b64encode(blob[:-16]).decode(),
            iv=base64.urlsafe_b64encode(iv).decode(),
            tag=base64.urlsafe_b64encode(blob[-16:]).decode(),
        )

    def decrypt(self, secret: EncryptedSecret) -> str:
        iv = base64.urlsafe_b64decode(secret.iv)
        ciphertext = base64.urlsafe_b64decode(secret.ciphertext)
        tag = base64.urlsafe_b64decode(secret.tag)
        return AESGCM(self._key).decrypt(iv, ciphertext + tag, None).decode()

    @staticmethod
    def fingerprint(plaintext: str) -> str:
        digest = hashlib.sha256(plaintext.encode()).hexdigest()[:8]
        prefix = plaintext[:4] if len(plaintext) >= 4 else "****"
        return f"{prefix}...{digest}"

    @staticmethod
    def mask(fingerprint: str) -> str:
        return fingerprint if "..." in fingerprint else "****"
