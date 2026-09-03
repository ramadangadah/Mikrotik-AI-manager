"""
Symmetric encryption for anything sensitive we persist: management-router
and CPE passwords, PPPoE secrets, LLM API keys. We use Fernet (AES-128-CBC +
HMAC) via the `cryptography` package.

The key is read from settings.ENCRYPTION_KEY if set; otherwise a key is
generated on first boot and stashed in DATA_DIR/secret.key so it survives
restarts of the same container/volume. Losing this file means losing the
ability to decrypt stored credentials, so back it up along with your DB.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet

from app.core.config import get_settings

_settings = get_settings()
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    if _settings.ENCRYPTION_KEY:
        return _settings.ENCRYPTION_KEY.encode()

    os.makedirs(_settings.DATA_DIR, exist_ok=True)
    key_path = os.path.join(_settings.DATA_DIR, "secret.key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(value: str) -> str:
    if value is None:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if token is None:
        return token
    return _get_fernet().decrypt(token.encode()).decode()
