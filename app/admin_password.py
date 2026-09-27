"""Пароль входа в панель управления.

Пока пароль не меняли в панели, действует ADMIN_PASSWORD из .env. После смены в разделе
«Смена пароля» в БД хранится хеш scrypt, и он главнее .env.

Забыли пароль — сбросить на ADMIN_PASSWORD из .env:
    .venv/bin/python -m app.admin_password --reset
"""

import hashlib
import hmac
import secrets
import sys

from sqlalchemy import delete

from app.config import settings
from app.db import SessionLocal
from app.models import AdminCredential

MIN_LENGTH = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)


def _stored() -> str | None:
    with SessionLocal() as db:
        row = db.get(AdminCredential, 1)
        return row.password_hash if row else None


def check(password: str) -> bool:
    stored = _stored()
    if stored is None:  # пароль ещё не меняли — сверяем с .env
        return hmac.compare_digest(password.encode(), settings.admin_password.encode())
    salt_hex, hash_hex = stored.split("$", 1)
    return hmac.compare_digest(_hash(password, bytes.fromhex(salt_hex)).hex(), hash_hex)


def set_password(password: str) -> None:
    salt = secrets.token_bytes(16)
    value = f"{salt.hex()}${_hash(password, salt).hex()}"
    with SessionLocal() as db:
        row = db.get(AdminCredential, 1) or AdminCredential(id=1)
        row.password_hash = value
        db.add(row)
        db.commit()


def version() -> str:
    """Метка текущего пароля: хранится в сессии, после смены пароля старые сессии перестают действовать."""
    stored = _stored()
    return stored[:16] if stored else "env"


def validate_new(current: str, new: str, repeat: str) -> str | None:
    if not check(current):
        return "Текущий пароль указан неверно"
    if len(new) < MIN_LENGTH:
        return f"Новый пароль должен быть не короче {MIN_LENGTH} символов"
    if new != repeat:
        return "Новый пароль и повтор не совпадают"
    if new == current:
        return "Новый пароль совпадает с текущим"
    return None


def reset() -> None:
    with SessionLocal() as db:
        db.execute(delete(AdminCredential))
        db.commit()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
        print("Пароль сброшен: снова действует ADMIN_PASSWORD из .env")
    else:
        print(__doc__)
