"""Справочники техник и жанров: редактируются в панели управления («Справочники»).

Код (латиница) попадает в адреса каталога: /catalog?genre=landscape — поэтому он задаётся один раз
при создании и потом не меняется, даже если переименовать жанр.
"""

import re
import time

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import DEFAULT_GENRES, DEFAULT_TECHNIQUES, Genre, Technique

CACHE_SECONDS = 5
_cache: dict[type, tuple[float, dict[str, str]]] = {}

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower().translate(_TRANSLIT)).strip("_")[:40] or "item"


def _load(model) -> dict[str, str]:
    now = time.monotonic()
    cached = _cache.get(model)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    with SessionLocal() as db:
        rows = db.execute(select(model.code, model.name).order_by(model.sort, model.name)).all()
    data = {code: name for code, name in rows}
    _cache[model] = (now, data)
    return data


def get_techniques() -> dict[str, str]:
    return _load(Technique)


def get_genres() -> dict[str, str]:
    return _load(Genre)


def reset_cache() -> None:
    _cache.clear()


def unique_code(db, model, name: str) -> str:
    base = slugify(name)
    code, n = base, 2
    while db.scalar(select(func.count()).where(model.code == code)):
        code, n = f"{base}_{n}", n + 1
    return code


def ensure_defaults() -> None:
    """Первый запуск: заполняем справочники стандартными значениями (дальше их правят в панели)."""
    with SessionLocal() as db:
        for model, defaults in ((Technique, DEFAULT_TECHNIQUES), (Genre, DEFAULT_GENRES)):
            if db.scalar(select(func.count()).select_from(model)):
                continue
            for i, (code, name) in enumerate(defaults.items()):
                db.add(model(code=code, name=name, sort=(i + 1) * 10))
        db.commit()
    reset_cache()
