"""Доступ к портфолио риелтора с коротким кэшем: страница сайта не ходит в БД на каждый вывод цифр."""

import time

from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Profile

CACHE_SECONDS = 5  # у каждого воркера свой кэш — после сохранения обновится максимум через 5 с
_cached: tuple[float, Profile] | None = None


def get_profile() -> Profile:
    global _cached
    now = time.monotonic()
    if _cached and now - _cached[0] < CACHE_SECONDS:
        return _cached[1]
    with SessionLocal() as db:
        profile = db.get(Profile, 1)
        if profile is None:
            profile = Profile(id=1)
            db.add(profile)
            try:
                db.commit()
            except IntegrityError:  # запись одновременно создал соседний воркер
                db.rollback()
                profile = db.get(Profile, 1)
    _cached = (now, profile)
    return profile


def reset_cache() -> None:
    global _cached
    _cached = None
