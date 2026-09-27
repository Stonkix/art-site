from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    debug: bool = False
    base_url: str = "http://127.0.0.1:8000"  # без слеша в конце, нужен для sitemap/OG
    secret_key: str = "change-me"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'site.db').as_posix()}"
    media_dir: Path = BASE_DIR / "media"

    admin_username: str = "admin"
    admin_password: str = "admin"

    # Заявки на почту. Для mail.ru нужен «пароль для внешних приложений», не обычный пароль от ящика
    smtp_host: str = "smtp.mail.ru"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    leads_email: str = ""  # куда слать заявки; пусто — на EMAIL из контактов

    # Данные галереи — выводятся в шапке, подвале, контактах и превью ссылок
    site_name: str = "Галерея картин"
    site_tagline: str = "Оригинальные картины"
    city: str = "Калуга"
    phone: str = "+7 900 000-00-00"
    email: str = "hello@example.com"
    telegram: str = ""  # без @; пусто — ссылка не показывается
    max_url: str = ""  # пусто — ссылка на Max не показывается
    yandex_metrika_id: str = ""

    @property
    def leads_email_to(self) -> str:
        return self.leads_email or self.email

    @property
    def phone_href(self) -> str:
        return "tel:+" + "".join(c for c in self.phone if c.isdigit())


settings = Settings()
