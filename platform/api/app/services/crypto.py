"""Symmetric encryption for stored git tokens.

Fernet key derived from settings.secret_key via SHA-256, so any string works
as SECRET_KEY. Tokens are decryptable (git needs the cleartext to fetch) but
never leave the API: responses only ever expose whether a token is set.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token_enc: str) -> str:
    """Raises ValueError when SECRET_KEY changed since the token was stored."""
    try:
        return _fernet().decrypt(token_enc.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored git token cannot be decrypted — SECRET_KEY changed?") from e
