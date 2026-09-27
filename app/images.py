"""Обработка фото картин: поворот по EXIF, удаление метаданных (в т.ч. GPS), WebP в двух размерах + JPEG для превью в мессенджерах."""

import secrets
import shutil
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from app.config import settings

WEBP_SIZES = {"thumb": 900, "full": 2200}  # максимальная сторона, px; full — для рассматривания мазков
WEBP_QUALITY = 84  # картинам нужна чуть выше обычного: на градиентах видны артефакты сжатия
OG_SIZE = (1200, 630)  # стандарт Open Graph; WebP мессенджеры понимают плохо, поэтому JPEG
OG_BACKGROUND = (243, 241, 236)  # цвет «стены» сайта: картина целиком, без обрезки


def painting_dir(painting_id: int) -> Path:
    return settings.media_dir / "paintings" / str(painting_id)


def save_photo(painting_id: int, data: bytes) -> tuple[str, int, int]:
    """Сохраняет фото, возвращает (имя, ширина, высота full-версии).
    Бросает PIL.UnidentifiedImageError для не-картинок."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")  # convert отбрасывает EXIF

    name = secrets.token_hex(6)
    target = painting_dir(painting_id)
    target.mkdir(parents=True, exist_ok=True)

    full_size = img.size
    for size, max_side in WEBP_SIZES.items():
        resized = img.copy()
        resized.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        resized.save(target / f"{name}_{size}.webp", "WEBP", quality=WEBP_QUALITY, method=4)
        if size == "full":
            full_size = resized.size

    # Превью ссылки: картина целиком на светлом фоне — обрезать края произведения нельзя
    og = Image.new("RGB", OG_SIZE, OG_BACKGROUND)
    inner = img.copy()
    inner.thumbnail((OG_SIZE[0] - 120, OG_SIZE[1] - 80), Image.Resampling.LANCZOS)
    og.paste(inner, ((OG_SIZE[0] - inner.width) // 2, (OG_SIZE[1] - inner.height) // 2))
    og.save(target / f"{name}_og.jpg", "JPEG", quality=85, optimize=True, progressive=True)
    return name, *full_size


PROFILE_MAX_SIDE = 1200


def save_profile_photo(data: bytes) -> str:
    """Фото автора для сайта: WebP до 1200px. Возвращает имя файла в media/profile/."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    img.thumbnail((PROFILE_MAX_SIDE, PROFILE_MAX_SIDE), Image.Resampling.LANCZOS)
    target = settings.media_dir / "profile"
    target.mkdir(parents=True, exist_ok=True)
    name = f"artist_{secrets.token_hex(6)}.webp"
    img.save(target / name, "WEBP", quality=85, method=4)
    return name


def delete_profile_photo(name: str | None) -> None:
    if name:
        (settings.media_dir / "profile" / name).unlink(missing_ok=True)


def delete_photo_files(painting_id: int, name: str) -> None:
    for f in painting_dir(painting_id).glob(f"{name}_*"):
        f.unlink(missing_ok=True)


def delete_painting_files(painting_id: int) -> None:
    shutil.rmtree(painting_dir(painting_id), ignore_errors=True)
