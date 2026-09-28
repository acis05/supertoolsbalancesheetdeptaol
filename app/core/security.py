from __future__ import annotations
import base64
import hashlib
import secrets
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.urlsafe_b64encode(salt).decode("ascii") + "$" + base64.urlsafe_b64encode(digest).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = password_hash.split("$", 2)
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=len(expected))
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def _valid_fernet_key(raw: str) -> bool:
    """Return True only for a canonical Fernet key (32 url-safe bytes encoded to base64)."""
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
        return len(decoded) == 32
    except Exception:
        return False


def _fernet_key() -> bytes:
    """Build a stable Fernet key from Railway environment values.

    Production may provide a real Fernet key. If the value is a normal random
    secret/string instead (a common Railway setup mistake), hash it to 32 bytes
    and convert it to the exact Fernet representation. This prevents OAuth from
    crashing with: 'Fernet key must be 32 url-safe base64-encoded bytes'.

    IMPORTANT: changing TOKEN_ENCRYPTION_KEY later invalidates previously
    encrypted OAuth tokens/sessions. Users then need to reconnect AOL.
    """
    configured = (settings.token_encryption_key or "").strip()
    if configured and _valid_fernet_key(configured):
        return configured.encode("ascii")

    # If TOKEN_ENCRYPTION_KEY is present but is not Fernet-formatted, deliberately
    # use it as key material rather than rejecting it. If empty, fall back to the
    # application's SECRET_KEY. Either way the result is a valid, stable Fernet key.
    material = configured or settings.secret_key or "supertools-development-fallback"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(_fernet_key())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY berubah/tidak cocok dengan token yang tersimpan. "
            "Silakan hubungkan ulang Accurate Online."
        ) from exc


def csrf_token(session: dict) -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf(session: dict, supplied: str | None) -> bool:
    current = session.get("csrf_token", "")
    return bool(current and supplied and secrets.compare_digest(current, supplied))


def utcnow() -> datetime:
    return datetime.utcnow()
