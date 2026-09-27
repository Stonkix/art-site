from datetime import datetime, timedelta

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

TECHNIQUES = {
    "oil": "Масло",
    "acrylic": "Акрил",
    "watercolor": "Акварель",
    "gouache": "Гуашь",
    "pastel": "Пастель",
    "graphics": "Графика",
    "mixed": "Смешанная техника",
}
GENRES = {
    "landscape": "Пейзаж",
    "cityscape": "Городской пейзаж",
    "still_life": "Натюрморт",
    "portrait": "Портрет",
    "flowers": "Цветы",
    "animals": "Анималистика",
    "abstract": "Абстракция",
    "other": "Другое",
}
STATUSES = {"available": "В наличии", "reserved": "Забронирована", "sold": "Продана"}
# Размер по большей стороне — так покупателю проще представить картину на стене
SIZE_GROUPS = {"small": ("Небольшие, до 40 см", 0, 40), "medium": ("Средние, 41–80 см", 41, 80), "large": ("Крупные, от 81 см", 81, 10_000)}
LEAD_KINDS = {
    "buy": "Хочу купить картину",
    "question": "Вопрос",
    "commission": "Картина на заказ",
    "callback": "Обратный звонок",
}

NEW_BADGE_DAYS = 21


class Painting(Base):
    __tablename__ = "paintings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str | None] = mapped_column(String(120), default=None, index=True)  # художник; пусто — не показывается
    technique: Mapped[str] = mapped_column(String(20), default="oil", index=True)
    genre: Mapped[str] = mapped_column(String(20), default="landscape", index=True)
    base: Mapped[str | None] = mapped_column(String(80), default=None)  # холст на подрамнике, картон, бумага…
    width_cm: Mapped[int] = mapped_column()
    height_cm: Mapped[int] = mapped_column()
    year: Mapped[int | None] = mapped_column(default=None)
    framed: Mapped[bool] = mapped_column(default=False)
    price: Mapped[int | None] = mapped_column(default=None, index=True)  # пусто — «Цена по запросу»
    status: Mapped[str] = mapped_column(String(20), default="available", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_featured: Mapped[bool] = mapped_column(default=False)  # показывать на главной
    is_published: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)

    photos: Mapped[list["Photo"]] = relationship(
        back_populates="painting",
        order_by="Photo.sort",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Поле загрузки фото в админке не хранится в БД; атрибут нужен sqladmin при редактировании
    photos_upload = None

    def __str__(self) -> str:
        return f"#{self.id} «{self.title}»"

    @property
    def url(self) -> str:
        return f"/catalog/{self.id}"

    @property
    def cover(self) -> "Photo | None":
        return self.photos[0] if self.photos else None

    @property
    def size_label(self) -> str:
        return f"{self.width_cm} × {self.height_cm} см"

    @property
    def size_group(self) -> str:
        longest = max(self.width_cm, self.height_cm)
        return next(code for code, (_, lo, hi) in SIZE_GROUPS.items() if lo <= longest <= hi)

    @property
    def is_sold(self) -> bool:
        return self.status == "sold"

    @property
    def is_new(self) -> bool:
        return self.created_at is not None and datetime.now() - self.created_at < timedelta(days=NEW_BADGE_DAYS)

    @property
    def medium(self) -> str:
        """«Масло, холст на подрамнике»."""
        tech = TECHNIQUES.get(self.technique, "")
        if self.base:
            return f"{tech}, {self.base.lower()}" if tech else self.base
        return tech

    @property
    def subtitle(self) -> str:
        """«Масло, холст · 60 × 80 см · 2024» — строка под названием."""
        parts = [self.medium, self.size_label, str(self.year) if self.year else ""]
        return " · ".join(p for p in parts if p)


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    painting_id: Mapped[int] = mapped_column(ForeignKey("paintings.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))  # базовое имя файлов без суффикса
    width: Mapped[int] = mapped_column(default=0)  # размеры full-версии: браузер резервирует место без скачков
    height: Mapped[int] = mapped_column(default=0)
    sort: Mapped[int] = mapped_column(default=0)

    painting: Mapped[Painting] = relationship(back_populates="photos")

    def __str__(self) -> str:
        return f"Фото {self.name}"

    def _url(self, size: str, ext: str = "webp") -> str:
        return f"/media/paintings/{self.painting_id}/{self.name}_{size}.{ext}"

    @property
    def thumb(self) -> str:
        return self._url("thumb")

    @property
    def full(self) -> str:
        return self._url("full")

    @property
    def og(self) -> str:
        return self._url("og", "jpg")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="callback")
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, default="")
    painting_id: Mapped[int | None] = mapped_column(
        ForeignKey("paintings.id", ondelete="SET NULL"), default=None
    )
    is_processed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    painting: Mapped[Painting | None] = relationship()

    def __str__(self) -> str:
        return f"{self.name} {self.phone}"


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    author: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    caption: Mapped[str | None] = mapped_column(String(150), default=None)  # «Купила „Туман над Окой“»
    is_published: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    def __str__(self) -> str:
        return self.author


DEFAULT_ABOUT = (
    "Мы собираем оригинальные картины современных художников: пейзажи, цветы, натюрморты и абстракцию — "
    "работы, в которых хочется задержаться взглядом.\n\n"
    "Каждая картина существует в единственном экземпляре. Ответим на вопросы, пришлём дополнительные фото "
    "и поможем подобрать картину под ваш интерьер."
)


class Profile(Base):
    """О галерее — одна строка (id=1), редактируется в панели управления «О галерее»."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    photo: Mapped[str | None] = mapped_column(String(64), default=None)  # файл в media/profile/
    about: Mapped[str] = mapped_column(Text, default=DEFAULT_ABOUT)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)

    @property
    def photo_url(self) -> str:
        return f"/media/profile/{self.photo}" if self.photo else "/static/img/gallery.svg"

    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.about.split("\n\n") if p.strip()]


class LoginAttempt(Base):
    """Неудачные попытки входа в админку по IP (см. app/login_guard.py)."""

    __tablename__ = "login_attempts"

    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    last_failure_at: Mapped[datetime | None] = mapped_column(default=None)
    blocked_until: Mapped[datetime | None] = mapped_column(default=None)
