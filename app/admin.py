import asyncio
import logging
import secrets

import anyio
from markupsafe import Markup, escape
from PIL import UnidentifiedImageError
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqladmin.i18n import I18nConfig
from sqlalchemy import func, select
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import RedirectResponse
from wtforms import MultipleFileField, SelectField

from app import images, login_guard, profile as profile_store
from app.config import BASE_DIR, settings
from app.db import SessionLocal, engine
from app.models import GENRES, LEAD_KINDS, STATUSES, TECHNIQUES, Lead, Painting, Photo, Profile, Review
from app.templating import templates as site_templates
from app.utils import fmt_price

log = logging.getLogger(__name__)


def _same(given: object, expected: str) -> bool:
    # сравниваем байты: compare_digest не принимает строки с кириллицей
    return secrets.compare_digest(str(given or "").encode(), expected.encode())


class AdminAuth(AuthenticationBackend):
    templates = None  # шаблоны админки, выставляются в setup_admin

    async def _login_page(self, request: Request, error: str, status: int, locked: bool = False):
        return await self.templates.TemplateResponse(
            request, "sqladmin/login.html", {"error": error, "locked": locked}, status_code=status
        )

    async def login(self, request: Request):
        ip = request.client.host if request.client else "unknown"  # за nginx — реальный IP (--proxy-headers)
        until = login_guard.blocked_until(ip)
        if until:
            return await self._login_page(
                request, f"Слишком много неудачных попыток. Вход заблокирован до {until:%d.%m.%Y %H:%M}.", 429, locked=True
            )

        form = await request.form()
        ok = _same(form.get("username"), settings.admin_username) & _same(
            form.get("password"), settings.admin_password
        )
        if not ok:
            await asyncio.sleep(1)  # замедляем перебор пароля
            left, until = login_guard.register_failure(ip)
            if until:
                return await self._login_page(
                    request,
                    f"Неверный логин или пароль. Попытки закончились — вход заблокирован до {until:%d.%m.%Y %H:%M}.",
                    429,
                    locked=True,
                )
            return await self._login_page(request, f"Неверный логин или пароль. Осталось попыток: {left}.", 400)

        login_guard.reset(ip)
        request.session["admin"] = True
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


def _choices(d: dict[str, str]) -> list[tuple[str, str]]:
    return list(d.items())


class PaintingAdmin(ModelView, model=Painting):
    name = "Картина"
    name_plural = "Картины"
    icon = "fa-solid fa-palette"
    page_size = 50

    column_list = [
        Painting.id,
        Painting.title,
        Painting.author,
        Painting.technique,
        Painting.price,
        Painting.status,
        Painting.is_featured,
        Painting.is_published,
        Painting.created_at,
    ]
    column_searchable_list = [Painting.title, Painting.author]
    column_sortable_list = [Painting.id, Painting.price, Painting.created_at]
    column_default_sort = [(Painting.id, True)]
    column_formatters = {
        Painting.title: lambda m, a: Markup(
            '<img src="{}" style="height:48px;width:48px;object-fit:contain;background:#f3f1ec;border-radius:4px;'
            'margin-right:8px;vertical-align:middle">{}'.format(m.cover.thumb, escape(m.title))
            if m.cover
            else escape(m.title)
        ),
        Painting.technique: lambda m, a: TECHNIQUES.get(m.technique, m.technique),
        Painting.status: lambda m, a: STATUSES.get(m.status, m.status),
        Painting.price: lambda m, a: fmt_price(m.price) if m.price else "по запросу",
    }
    column_formatters_detail = {
        Painting.technique: lambda m, a: TECHNIQUES.get(m.technique, m.technique),
        Painting.genre: lambda m, a: GENRES.get(m.genre, m.genre),
        Painting.status: lambda m, a: STATUSES.get(m.status, m.status),
    }
    column_labels = {
        Painting.title: "Название",
        Painting.author: "Автор (необязательно)",
        Painting.technique: "Техника",
        Painting.genre: "Жанр",
        Painting.base: "Основа (холст на подрамнике, картон, бумага…)",
        Painting.width_cm: "Ширина, см",
        Painting.height_cm: "Высота, см",
        Painting.year: "Год",
        Painting.framed: "В раме",
        Painting.price: "Цена, ₽ (пусто — «по запросу»)",
        Painting.status: "Статус",
        Painting.description: "Описание",
        Painting.is_featured: "На главную",
        Painting.is_published: "Опубликована",
        Painting.created_at: "Добавлена",
        Painting.photos: "Фото",
    }
    form_excluded_columns = [Painting.photos, Painting.created_at, Painting.updated_at]
    form_overrides = {"technique": SelectField, "genre": SelectField, "status": SelectField}
    form_args = {
        "technique": {"choices": _choices(TECHNIQUES), "label": "Техника"},
        "genre": {"choices": _choices(GENRES), "label": "Жанр"},
        "status": {
            "choices": _choices(STATUSES),
            "label": "Статус",
            "description": "Проданные картины уходят из каталога, но остаются на странице «О галерее» в блоке «Уже нашли дом».",
        },
        "description": {"show_chars_count": False},
    }
    form_widget_args = {"description": {"rows": 8}}

    async def scaffold_form(self, rules=None):
        form_class = await super().scaffold_form(rules)
        form_class.photos_upload = MultipleFileField(
            "Фото",
            render_kw={"accept": "image/*", "multiple": True},
        )
        return form_class

    @staticmethod
    def _pop_uploads(data: dict) -> list:
        return [f for f in data.pop("photos_upload", None) or [] if getattr(f, "filename", "")]

    async def insert_model(self, request: Request, data: dict):
        uploads = self._pop_uploads(data)
        obj = await super().insert_model(request, data)
        await self._save_uploads(obj.id, uploads)
        return obj

    async def update_model(self, request: Request, pk: str, data: dict):
        uploads = self._pop_uploads(data)
        obj = await super().update_model(request, pk, data)
        form = await request.form()  # Starlette кэширует разобранную форму, повторного чтения нет
        self._apply_photo_changes(obj.id, str(form.get("photo_order", "")), str(form.get("photo_delete", "")))
        await self._save_uploads(obj.id, uploads)
        return obj

    @staticmethod
    def _apply_photo_changes(painting_id: int, order: str, delete: str) -> None:
        """Порядок и удаление уже загруженных фото — из скрытых полей, которые заполняет admin.js."""
        to_delete = {int(x) for x in delete.split(",") if x.isdigit()}
        ordered = [int(x) for x in order.split(",") if x.isdigit()]
        if not (to_delete or ordered):
            return
        with SessionLocal() as db:
            photos = {ph.id: ph for ph in db.scalars(select(Photo).where(Photo.painting_id == painting_id))}
            for ph_id in to_delete & photos.keys():
                images.delete_photo_files(painting_id, photos[ph_id].name)
                db.delete(photos.pop(ph_id))
            for i, ph_id in enumerate(x for x in ordered if x in photos):
                photos[ph_id].sort = i
            db.commit()

    async def _save_uploads(self, painting_id: int, uploads: list) -> None:
        if not uploads:
            return
        with SessionLocal() as db:
            next_sort = (
                db.scalar(select(func.max(Photo.sort)).where(Photo.painting_id == painting_id)) or 0
            ) + 1
            for i, upload in enumerate(uploads):
                raw = await upload.read()
                try:
                    name, width, height = await anyio.to_thread.run_sync(images.save_photo, painting_id, raw)
                except (UnidentifiedImageError, OSError):
                    log.warning("Пропущен файл, не являющийся изображением: %s", upload.filename)
                    continue
                db.add(Photo(painting_id=painting_id, name=name, width=width, height=height, sort=next_sort + i))
            db.commit()

    async def after_model_delete(self, model: Painting, request: Request) -> None:
        images.delete_painting_files(model.id)


class LeadAdmin(ModelView, model=Lead):
    name = "Заявка"
    name_plural = "Заявки"
    icon = "fa-solid fa-envelope"
    can_create = False

    column_list = [Lead.created_at, Lead.kind, Lead.name, Lead.phone, Lead.painting, Lead.is_processed]
    column_default_sort = [(Lead.created_at, True)]
    column_labels = {
        Lead.created_at: "Дата",
        Lead.kind: "Тип",
        Lead.name: "Имя",
        Lead.phone: "Телефон",
        Lead.message: "Сообщение",
        Lead.painting: "Картина",
        Lead.is_processed: "Обработана",
    }
    column_formatters = {Lead.kind: lambda m, a: LEAD_KINDS.get(m.kind, m.kind)}
    column_formatters_detail = column_formatters
    form_columns = [Lead.is_processed, Lead.message]
    form_args = {"message": {"show_chars_count": False}}


class ReviewAdmin(ModelView, model=Review):
    name = "Отзыв"
    name_plural = "Отзывы"
    icon = "fa-solid fa-comment"

    column_list = [Review.author, Review.caption, Review.is_published, Review.created_at]
    column_labels = {
        Review.author: "Автор",
        Review.text: "Текст",
        Review.caption: "Подпись (например, «Купила „Туман над Окой“»)",
        Review.is_published: "Опубликован",
        Review.created_at: "Дата",
    }
    form_excluded_columns = [Review.created_at]
    form_args = {"text": {"show_chars_count": False}}


class ProfileAdmin(BaseView):
    name = "О галерее"
    icon = "fa-solid fa-store"

    @expose("/profile", methods=["GET", "POST"])
    async def profile(self, request: Request):
        with SessionLocal() as db:
            prof = db.get(Profile, 1)
            if prof is None:
                prof = Profile(id=1)
                db.add(prof)
                db.commit()
            errors: dict[str, str] = {}
            values = {"about": prof.about}

            if request.method == "POST":
                form = await request.form()
                values = {"about": str(form.get("about", "")).strip()}
                if not values["about"]:
                    errors["about"] = "Напишите пару предложений о галерее"

                new_photo = None
                upload = form.get("photo")
                if isinstance(upload, UploadFile) and upload.filename:
                    try:
                        new_photo = await anyio.to_thread.run_sync(images.save_profile_photo, await upload.read())
                    except (UnidentifiedImageError, OSError):
                        errors["photo"] = "Не удалось открыть файл — загрузите JPG, PNG или WebP"

                if errors:
                    images.delete_profile_photo(new_photo)
                else:
                    prof.about = values["about"].replace("\r\n", "\n")
                    if new_photo or form.get("photo_remove"):
                        images.delete_profile_photo(prof.photo)
                        prof.photo = new_photo
                    db.commit()
                    profile_store.reset_cache()
                    # PRG: после сохранения — GET, чтобы F5 не отправлял форму повторно
                    return RedirectResponse(request.url.path + "?saved=1", status_code=303)

            return await self.templates.TemplateResponse(
                request,
                "admin/profile.html",
                {"prof": prof, "values": values, "errors": errors, "saved": request.query_params.get("saved") == "1"},
            )


def setup_admin(app) -> Admin:
    auth = AdminAuth(secret_key=settings.secret_key, https_only=not settings.debug)
    admin = Admin(
        app,
        engine,
        title="Панель управления сайтом",
        templates_dir=str(BASE_DIR / "app" / "templates"),  # переопределения в templates/sqladmin/
        authentication_backend=auth,
        i18n_config=I18nConfig(default_locale="ru"),
    )
    auth.templates = admin.templates
    admin.templates.env.globals["settings"] = settings
    admin.templates.env.globals["static_v"] = site_templates.env.globals["static_v"]
    for view in (PaintingAdmin, LeadAdmin, ReviewAdmin):
        admin.add_view(view)
    admin.add_base_view(ProfileAdmin)
    return admin
