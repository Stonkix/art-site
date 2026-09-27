import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import models  # noqa: F401 — регистрирует таблицы в metadata
from app.admin import setup_admin
from app.config import BASE_DIR, settings
from app.db import Base, engine
from app.routes import leads, pages, seo
from app.templating import templates

logging.basicConfig(level=logging.INFO)

_PLACEHOLDERS = ("change-me", "admin", "сгенерируйте", "длинный-надёжный-пароль")
if not settings.debug and any(
    v in _PLACEHOLDERS or v.startswith(_PLACEHOLDERS[2]) for v in (settings.secret_key, settings.admin_password)
):
    raise RuntimeError("Задайте SECRET_KEY и ADMIN_PASSWORD в .env (или DEBUG=true для локальной разработки)")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Для небольшого сайта хватает create_all; при изменении моделей подключите Alembic
    try:
        Base.metadata.create_all(engine)
    except OperationalError:
        pass  # при первом запуске соседний воркер uvicorn успел создать таблицы
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# В проде /static и /media отдаёт nginx, эти mount'ы работают для локальной разработки
settings.media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

app.include_router(pages.router)
app.include_router(leads.router)
app.include_router(seo.router)
setup_admin(app)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(
        request, "error.html", {"code": exc.status_code}, status_code=exc.status_code
    )
