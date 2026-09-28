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


def _fernet() -> Fernet:
    key = settings.token_encryption_key.strip()
    if not key:
        digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest).decode("ascii")
    return Fernet(key.encode("ascii"))


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
        raise RuntimeError("TOKEN_ENCRYPTION_KEY tidak cocok dengan data token yang tersimpan") from exc


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
