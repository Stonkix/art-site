import os
import tempfile
from io import BytesIO

_tmp = tempfile.mkdtemp()
os.environ.update(DEBUG="true", DATABASE_URL=f"sqlite:///{_tmp}/test.db", MEDIA_DIR=f"{_tmp}/media")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app import images  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Lead, Painting, Photo  # noqa: E402
from app.utils import normalize_phone  # noqa: E402


def _jpeg(color="red", size=(1200, 900)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        with SessionLocal() as db:
            p = Painting(title="Туман над Окой", author="Ирина Соколова", technique="oil", genre="landscape", base="Холст",
                         width_cm=60, height_cm=40, price=38000, is_featured=True)
            db.add(p)
            db.add(Painting(title="Проданная", genre="landscape", width_cm=30, height_cm=30, price=9000, status="sold"))
            db.add(Painting(title="Большая абстракция", technique="acrylic", genre="abstract", width_cm=120, height_cm=80))
            db.add(Painting(title="Скрытая", width_cm=20, height_cm=20, is_published=False))
            db.commit()
            name, w, h = images.save_photo(p.id, _jpeg(size=(3000, 2000)))
            db.add(Photo(painting_id=p.id, name=name, width=w, height=h))
            db.commit()
        yield c


def _login(client):
    from app.config import settings

    r = client.post("/admin/login", data={"username": settings.admin_username, "password": settings.admin_password},
                    follow_redirects=False)
    assert r.status_code == 302


@pytest.mark.parametrize("url", ["/", "/catalog", "/how-to-buy", "/about", "/privacy", "/consent", "/sitemap.xml", "/robots.txt"])
def test_pages_ok(client, url):
    assert client.get(url).status_code == 200


def test_home_shows_featured_and_price_on_request(client):
    home = client.get("/").text
    assert "Туман над Окой" in home and "Избранные работы" in home
    assert "Цена по запросу" in home  # у абстракции нет цены
    assert "Проданная" not in home


def test_catalog_filters(client):
    full = client.get("/catalog?genre=landscape&size=medium&price_max=40 000")
    assert "Туман над Окой" in full.text and "Проданная" not in full.text and "<html" in full.text

    assert "Большая абстракция" in client.get("/catalog?size=large").text
    assert "Туман над Окой" not in client.get("/catalog?size=large").text
    assert "Проданная" in client.get("/catalog?sold=1").text

    partial = client.get("/catalog?technique=pastel", headers={"HX-Request": "true"})
    assert "<html" not in partial.text and "Ничего не найдено" in partial.text


def test_painting_page(client):
    r = client.get("/catalog/1-tuman", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/catalog/1"
    page = client.get("/catalog/1").text
    assert "VisualArtwork" in page and "_og.jpg" in page and "Ирина Соколова" in page
    assert "Примерить" not in page and "Самозан" not in page
    assert "38\u202f000" in page
    assert client.get("/catalog/4").status_code == 404  # не опубликована
    assert client.get("/contacts", follow_redirects=False).headers["location"] == "/about#contacts"


def test_photo_processing(client):
    with SessionLocal() as db:
        ph = db.query(Photo).first()
    folder = images.painting_dir(ph.painting_id)
    full = Image.open(folder / f"{ph.name}_full.webp")
    assert full.format == "WEBP" and max(full.size) == images.WEBP_SIZES["full"] and (ph.width, ph.height) == full.size
    og = Image.open(folder / f"{ph.name}_og.jpg")
    assert og.size == images.OG_SIZE and og.getpixel((5, 5))[0] > 230  # картина на светлом фоне, не обрезана


def test_lead_and_email(client, monkeypatch):
    from app import mailer
    from app.config import settings

    sent = []
    monkeypatch.setattr(settings, "smtp_user", "site@example.com")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(mailer, "_smtp_send", sent.append)
    h = {"HX-Request": "true"}
    assert "Проверьте номер" in client.post("/lead", data={"name": "И", "phone": "1", "consent": "true"}, headers=h).text
    r = client.post("/lead", data={"name": "Мария\r\nBcc: x@evil.com", "phone": "8 912 000-11-22", "consent": "true",
                                   "kind": "buy", "painting_id": "1"}, headers=h)
    assert "заявка отправлена" in r.text
    with SessionLocal() as db:
        lead = db.query(Lead).order_by(Lead.id.desc()).first()
    assert lead.phone == "+79120001122" and lead.painting_id == 1 and lead.kind == "buy"
    msg = sent[-1]
    assert "Покупка картины" in msg["Subject"] and "\n" not in msg["Subject"] and msg["Bcc"] is None
    assert "«Туман над Окой», Ирина Соколова" in msg.get_body(("plain",)).get_content()


def test_admin_painting_photos(client):
    _login(client)
    assert client.get("/admin/painting/create").status_code == 200
    data = {"title": "Новая работа", "technique": "oil", "genre": "flowers", "width_cm": "40", "height_cm": "50",
            "status": "available", "is_published": "y", "save": "Сохранить"}
    r = client.post("/admin/painting/create", data=data, follow_redirects=False,
                    files=[("photos_upload", ("a.jpg", _jpeg("blue"), "image/jpeg")),
                           ("photos_upload", ("b.jpg", _jpeg("green"), "image/jpeg")),
                           ("photos_upload", ("x.txt", b"not image", "text/plain"))])
    assert r.status_code == 302
    with SessionLocal() as db:
        p = db.query(Painting).filter_by(title="Новая работа").one()
        ids = [ph.id for ph in p.photos]
    assert len(ids) == 2
    r = client.post(f"/admin/painting/edit/{p.id}", data=data | {"photo_order": f"{ids[1]},{ids[0]}", "photo_delete": str(ids[0])},
                    files=[("photos_upload", ("", b"", "application/octet-stream"))], follow_redirects=False)
    assert r.status_code == 302
    with SessionLocal() as db:
        assert [ph.id for ph in db.get(Painting, p.id).photos] == [ids[1]]
    assert client.get(f"/catalog/{p.id}").status_code == 200


def test_profile_admin(client):
    _login(client)
    r = client.post("/admin/profile", data={"about": "Первый абзац.\r\n\r\nВторой."},
                    files={"photo": ("me.jpg", _jpeg(size=(800, 1000)), "image/jpeg")}, follow_redirects=False)
    assert r.status_code == 303
    about = client.get("/about").text
    assert '<p class="lead">Первый абзац.</p>' in about and "/media/profile/gallery_" in about


def test_login_lockout(client):
    from app import login_guard

    try:
        for left in (4, 3, 2, 1):
            r = client.post("/admin/login", data={"username": "admin", "password": "wrong"})
            assert r.status_code == 400 and f"Осталось попыток: {left}" in r.text
        assert client.post("/admin/login", data={"username": "admin", "password": "wrong"}).status_code == 429
    finally:
        login_guard.reset()
    _login(client)


def test_utils():
    assert normalize_phone("+7 (900) 123-45-67") == "+79001234567"
    assert normalize_phone("12345") is None


def test_admin_terms_add_technique(client):
    _login(client)
    r = client.post("/admin/technique/create", data={"name": "Карандаш", "sort": "5", "save": "Сохранить"}, follow_redirects=False)
    assert r.status_code == 302
    from app.models import Technique

    with SessionLocal() as db:
        t = db.query(Technique).filter_by(name="Карандаш").one()
    assert t.code == "karandash"
    assert '<option value="karandash"' in client.get("/catalog").text  # новая техника — в фильтре каталога
    assert 'value="karandash"' in client.get("/admin/painting/create").text  # и в форме картины

    with SessionLocal() as db:
        db.add(Painting(title="Эскиз", technique="karandash", genre="other", width_cm=20, height_cm=30))
        db.commit()
    assert "Карандаш" in client.get("/catalog?technique=karandash").text

    # занятую технику удалить нельзя, картины не остаются с «висящим» кодом
    client.delete("/admin/technique/delete", params={"pks": str(t.id)})
    with SessionLocal() as db:
        assert db.get(Technique, t.id) is not None


def test_admin_password_change(client):
    from app import admin_password
    from app.config import settings

    _login(client)
    try:
        bad = client.post("/admin/password", data={"current": "wrong", "new": "новый-пароль-1", "repeat": "новый-пароль-1"})
        assert "Текущий пароль указан неверно" in bad.text
        short = client.post("/admin/password", data={"current": settings.admin_password, "new": "123", "repeat": "123"})
        assert "не короче" in short.text
        r = client.post("/admin/password", data={"current": settings.admin_password, "new": "новый-пароль-1", "repeat": "новый-пароль-1"},
                        follow_redirects=False)
        assert r.status_code == 303
        assert client.get("/admin/painting/list", follow_redirects=False).status_code == 200  # текущая сессия жива

        other = TestClient(app)  # «другое устройство»: старый пароль больше не подходит
        assert other.post("/admin/login", data={"username": settings.admin_username, "password": settings.admin_password}).status_code == 400
        assert other.post("/admin/login", data={"username": settings.admin_username, "password": "новый-пароль-1"},
                          follow_redirects=False).status_code == 302
    finally:
        admin_password.reset()
        from app import login_guard

        login_guard.reset()
    _login(client)


def test_heic_upload(client):
    """Фото с iPhone (HEIC) принимаются и конвертируются в WebP."""
    _login(client)
    buf = BytesIO()
    Image.new("RGB", (1600, 1200), "purple").save(buf, "HEIF")
    data = {"title": "С айфона", "technique": "oil", "genre": "flowers", "width_cm": "30", "height_cm": "40",
            "status": "available", "is_published": "y", "save": "Сохранить"}
    r = client.post("/admin/painting/create", data=data, follow_redirects=False,
                    files=[("photos_upload", ("IMG_0001.HEIC", buf.getvalue(), "image/heic"))])
    assert r.status_code == 302
    with SessionLocal() as db:
        p = db.query(Painting).filter_by(title="С айфона").one()
        assert len(p.photos) == 1
        ph = p.photos[0]
    assert Image.open(images.painting_dir(p.id) / f"{ph.name}_full.webp").format == "WEBP"


def test_admin_selects_empty_by_default(client):
    import re

    _login(client)
    form = client.get("/admin/painting/create").text
    for field in ("technique", "genre", "status"):
        select = re.search(rf'<select[^>]*name="{field}"[^>]*>(.*?)</select>', form, re.S).group(1)
        assert re.search(r'<option selected value="">— Выберите —</option>', select), field  # ничего не выбрано заранее
    r = client.post("/admin/painting/create", data={"title": "Без техники", "width_cm": "10", "height_cm": "10",
                                                    "technique": "", "genre": "", "status": "", "save": "Сохранить"})
    assert "Выберите значение из списка" in r.text
    with SessionLocal() as db:
        assert db.query(Painting).filter_by(title="Без техники").count() == 0
    edit = client.get("/admin/painting/edit/1").text  # у существующей картины — её значение
    assert re.search(r'<option selected value="oil">', edit)
