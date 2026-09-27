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

from app import admin_password, images, login_guard, profile as profile_store, terms
from app.config import BASE_DIR, settings
from app.db import SessionLocal, engine
from app.models import LEAD_KINDS, STATUSES, Genre, Lead, Painting, Photo, Profile, Review, Technique
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
        password_ok = await anyio.to_thread.run_sync(admin_password.check, str(form.get("password") or ""))
        ok = _same(form.get("username"), settings.admin_username) & password_ok
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
        request.session["pv"] = admin_password.version()
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        # после смены пароля сессии со старой меткой перестают действовать
        return bool(request.session.get("admin")) and request.session.get("pv") == admin_password.version()


def _choices(d: dict[str, str]) -> list[tuple[str, str]]:
    return list(d.items())


class PaintingAdmin(ModelView, model=Painting):
    name = "Картина"
    name_plural = "Картины"
    add_label = "Добавить картину"
    edit_label = "Редактировать картину"
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
        # превью и название в одном блоке с минимальной шириной — текст не наезжает на соседние колонки
        Painting.title: lambda m, a: Markup(
            '<span style="display:inline-flex;align-items:center;gap:10px;min-width:220px;white-space:normal">'
            '{}<span>{}</span></span>'.format(
                '<img src="{}" style="height:48px;width:48px;flex:none;object-fit:contain;background:#f3f1ec;'
                'border-radius:4px">'.format(m.cover.thumb) if m.cover else "",
                escape(m.title),
            )
        ),
        Painting.created_at: lambda m, a: f"{m.created_at:%d.%m.%Y %H:%M}" if m.created_at else "",
        Painting.technique: lambda m, a: m.technique_name,
        Painting.status: lambda m, a: STATUSES.get(m.status, m.status),
        Painting.price: lambda m, a: fmt_price(m.price) if m.price else "по запросу",
    }
    column_formatters_detail = {
        Painting.technique: lambda m, a: m.technique_name,
        Painting.genre: lambda m, a: m.genre_name,
        Painting.status: lambda m, a: STATUSES.get(m.status, m.status),
        Painting.created_at: lambda m, a: f"{m.created_at:%d.%m.%Y %H:%M}" if m.created_at else "",
        Painting.updated_at: lambda m, a: f"{m.updated_at:%d.%m.%Y %H:%M}" if m.updated_at else "",
    }
    column_details_exclude_list = [Painting.photos]  # фото видны в форме редактирования
    column_labels = {
        Painting.title: "Название",
        Painting.author: "Автор",
        Painting.technique: "Техника",
        Painting.genre: "Жанр",
        Painting.base: "Основа",
        Painting.width_cm: "Ширина, см",
        Painting.height_cm: "Высота, см",
        Painting.year: "Год",
        Painting.framed: "В раме",
        Painting.price: "Цена, ₽",
        Painting.status: "Статус",
        Painting.description: "Описание",
        Painting.is_featured: "На главную",
        Painting.is_published: "Опубликована",
        Painting.created_at: "Добавлена",
        Painting.updated_at: "Изменена",
        Painting.photos: "Фото",
    }
    form_excluded_columns = [Painting.photos, Painting.created_at, Painting.updated_at]
    form_overrides = {"technique": SelectField, "genre": SelectField, "status": SelectField}
    form_args = {
        # списки берутся из «Справочников» при каждом открытии формы
        "technique": {"choices": lambda: _choices(terms.get_techniques()), "label": "Техника",
                      "description": "Нет нужной? Добавьте в «Справочники → Техники»."},
        "genre": {"choices": lambda: _choices(terms.get_genres()), "label": "Жанр",
                  "description": "Нет нужного? Добавьте в «Справочники → Жанры»."},
        "status": {
            "choices": _choices(STATUSES),
            "label": "Статус",
            "description": "Проданные картины уходят из каталога, но остаются на странице «О галерее» в блоке «Уже нашли свой дом».",
        },
        "description": {"show_chars_count": False},
        # подсказки — только в форме; в таблице заголовки короткие
        "author": {"description": "Необязательно. Если пусто — на сайте не показывается."},
        "base": {"description": "Например: холст на подрамнике, картон, бумага."},
        "price": {"description": "Пусто — на сайте будет «Цена по запросу»."},
    }
    form_widget_args = {"description": {"rows": 8}}

    async def scaffold_form(self, rules=None):
        form_class = await super().scaffold_form(rules)
        form_class.photos_upload = MultipleFileField(
            "Фото",
            render_kw={"accept": "image/*,.heic,.heif", "multiple": True},
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


class _TermAdmin(ModelView):
    """Общая логика справочников: код для адресов создаётся сам, занятое значение удалить нельзя."""

    category = "Справочники"
    painting_field = ""  # поле Painting, которое ссылается на код
    column_list = ["name", "sort"]
    column_default_sort = [("sort", False), ("name", False)]
    column_labels = {"name": "Название", "sort": "Порядок", "code": "Код в адресе"}
    form_args = {"sort": {"description": "Чем меньше число, тем выше в списках на сайте и в форме картины."}}
    form_columns = ["name", "sort"]

    async def on_model_change(self, data: dict, model, is_created: bool, request: Request):
        data["name"] = (data.get("name") or "").strip()

    async def insert_model(self, request: Request, data: dict):
        # code не входит в форму: создаём запись сами, чтобы сразу выдать уникальный код
        name = (data.get("name") or "").strip()
        with SessionLocal() as db:
            obj = self.model(code=terms.unique_code(db, self.model, name), name=name, sort=data.get("sort") or 100)
            db.add(obj)
            db.commit()
            db.refresh(obj)
        terms.reset_cache()
        return obj

    async def after_model_change(self, data: dict, model, is_created: bool, request: Request):
        terms.reset_cache()

    async def delete_model(self, request: Request, pk):
        with SessionLocal() as db:
            term = db.get(self.model, int(pk))
            used = db.scalar(
                select(func.count()).select_from(Painting).where(getattr(Painting, self.painting_field) == term.code)
            )
        if used:
            raise ValueError(f"«{term.name}» указан у картин: {used}. Сначала поменяйте его в этих картинах.")
        await super().delete_model(request, pk)
        terms.reset_cache()


class TechniqueAdmin(_TermAdmin, model=Technique):
    name = "Техника"
    name_plural = "Техники"
    add_label = "Добавить технику"
    edit_label = "Редактировать технику"
    icon = "fa-solid fa-paintbrush"
    painting_field = "technique"


class GenreAdmin(_TermAdmin, model=Genre):
    name = "Жанр"
    name_plural = "Жанры"
    add_label = "Добавить жанр"
    edit_label = "Редактировать жанр"
    icon = "fa-solid fa-tags"
    painting_field = "genre"


class LeadAdmin(ModelView, model=Lead):
    name = "Заявка"
    name_plural = "Заявки"
    edit_label = "Заявка"
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
    column_formatters = {Lead.kind: lambda m, a: LEAD_KINDS.get(m.kind, m.kind), Lead.created_at: lambda m, a: f"{m.created_at:%d.%m.%Y %H:%M}" if m.created_at else ""}
    column_formatters_detail = column_formatters
    form_columns = [Lead.is_processed, Lead.message]
    form_args = {"message": {"show_chars_count": False}}


class ReviewAdmin(ModelView, model=Review):
    name = "Отзыв"
    name_plural = "Отзывы"
    add_label = "Добавить отзыв"
    edit_label = "Редактировать отзыв"
    icon = "fa-solid fa-comment"

    column_list = [Review.author, Review.caption, Review.is_published, Review.created_at]
    column_labels = {
        Review.author: "Автор",
        Review.text: "Текст",
        Review.caption: "Подпись",
        Review.is_published: "Опубликован",
        Review.created_at: "Дата",
    }
    form_excluded_columns = [Review.created_at]
    form_args = {
        "text": {"show_chars_count": False},
        "caption": {"description": "Необязательно. Например: «Купила „Туман над Окой“» или «Картина на заказ»."},
    }
    column_formatters = {Review.created_at: lambda m, a: f"{m.created_at:%d.%m.%Y %H:%M}" if m.created_at else ""}
    column_formatters_detail = column_formatters


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


class PasswordAdmin(BaseView):
    name = "Смена пароля"
    icon = "fa-solid fa-key"

    @expose("/password", methods=["GET", "POST"])
    async def password(self, request: Request):
        error = None
        if request.method == "POST":
            form = await request.form()
            current, new, repeat = (str(form.get(k, "")) for k in ("current", "new", "repeat"))
            error = await anyio.to_thread.run_sync(admin_password.validate_new, current, new, repeat)
            if not error:
                await anyio.to_thread.run_sync(admin_password.set_password, new)
                request.session["pv"] = admin_password.version()  # текущая сессия остаётся, остальные — нет
                return RedirectResponse(request.url.path + "?saved=1", status_code=303)
        return await self.templates.TemplateResponse(
            request,
            "admin/password.html",
            {"error": error, "saved": request.query_params.get("saved") == "1", "min_length": admin_password.MIN_LENGTH},
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
    for view in (PaintingAdmin, LeadAdmin, ReviewAdmin, TechniqueAdmin, GenreAdmin):
        admin.add_view(view)
    admin.add_base_view(ProfileAdmin)
    admin.add_base_view(PasswordAdmin)
    return admin
