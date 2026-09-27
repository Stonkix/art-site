"""Защита входа в админку: 5 неудачных попыток с одного IP — блокировка на 24 часа.

Счётчик хранится в БД, поэтому общий для всех воркеров и переживает перезапуск.
Снять все блокировки (например, если риелтор заблокировал себя):
    .venv/bin/python -m app.login_guard --reset
"""

import sys
from datetime import datetime, timedelta

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import LoginAttempt

MAX_FAILURES = 5
BLOCK_FOR = timedelta(hours=24)
FORGET_AFTER = timedelta(hours=24)  # редкие опечатки не копятся: счётчик обнуляется через сутки тишины


def blocked_until(ip: str) -> datetime | None:
    with SessionLocal() as db:
        row = db.get(LoginAttempt, ip)
        if row and row.blocked_until and row.blocked_until > datetime.now():
            return row.blocked_until
    return None


def register_failure(ip: str) -> tuple[int, datetime | None]:
    """Учитывает неудачную попытку. Возвращает (сколько попыток осталось, до какого времени блок)."""
    now = datetime.now()
    with SessionLocal() as db:
        row = db.get(LoginAttempt, ip)
        if row is None:
            row = LoginAttempt(ip=ip, failures=0)
            db.add(row)
        elif row.last_failure_at and now - row.last_failure_at > FORGET_AFTER:
            row.failures, row.blocked_until = 0, None
        row.failures += 1
        row.last_failure_at = now
        if row.failures >= MAX_FAILURES:
            row.blocked_until = now + BLOCK_FOR
        db.commit()
        return max(MAX_FAILURES - row.failures, 0), row.blocked_until


def reset(ip: str | None = None) -> None:
    with SessionLocal() as db:
        stmt = delete(LoginAttempt)
        if ip is not None:
            stmt = stmt.where(LoginAttempt.ip == ip)
        db.execute(stmt)
        db.commit()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
        print("Все блокировки входа сняты")
    else:
        print(__doc__)
