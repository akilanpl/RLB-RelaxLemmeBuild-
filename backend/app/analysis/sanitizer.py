"""Basic secret pattern redaction utility for analysis summaries and metadata."""

import re

# Common sensitive credential patterns to redact
SECRET_PATTERNS = [
    (re.compile(r"\bsk-[a-zA-Z0-9_-]+\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(?:GROQ_|OPENAI_)[A-Z0-9_]+\b"), "[REDACTED_CREDENTIAL]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9._~+/-]+", re.IGNORECASE), "[REDACTED_AUTHORIZATION]"),
    # Generic API Keys (e.g. sk-..., gsk-..., ghp-...)
    (re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(gsk_[a-zA-Z0-9_-]{20,})\b"), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{20,})\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\b(gho_[a-zA-Z0-9]{20,})\b"), "[REDACTED_OAUTH_TOKEN]"),
    # JWT Tokens (eyJ...)
    (re.compile(r"\b(eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,})\b"), "[REDACTED_JWT_TOKEN]"),
    # Password variables (e.g. password = "secret", DB_PASSWORD='...')
    (re.compile(r"""((?:password|passwd|secret|api_key|token)\s*[:=]\s*['"])([^'"]{4,})(['"])""", re.IGNORECASE), r"\1[REDACTED_SECRET]\3"),
    # Private Key blocks
    (re.compile(r"-----BEGIN[ A-Z_-]*PRIVATE KEY-----.*?-----END[ A-Z_-]*PRIVATE KEY-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
]


def redact_secrets(text: str) -> str:
    """Scan and redact known credential and secret patterns from text."""
    if not text:
        return text

    sanitized = text
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized
