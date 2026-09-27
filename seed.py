"""Демо-данные для локальной разработки: python seed.py (повторный запуск очищает картины, заявки и отзывы).

Картинки рисуются программно — это заглушки, настоящие фото работ загружаются через панель управления.
"""

import random
from datetime import datetime, timedelta
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from sqlalchemy import delete, select

from app import images, terms
from app.db import Base, SessionLocal, engine
from app.models import Lead, Painting, Photo, Review

random.seed(11)
PX_PER_CM = 18


def _lerp(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _gradient(size, top, bottom):
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        d.line([(0, y), (size[0], y)], fill=_lerp(top, bottom, y / max(size[1] - 1, 1)))
    return img


def _strokes(img, palette, count, length, width, alpha=110):
    """Мазки кистью: цвет берётся из холста под мазком с небольшим сдвигом, изредка — из палитры."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = img.size
    px = img.load()
    for _ in range(count * 3):
        x, y = random.randrange(w), random.randrange(h)
        base = px[x, y] if random.random() > 0.12 else random.choice(palette)
        color = tuple(max(0, min(255, c + random.randint(-14, 14))) for c in base)
        dx, dy = random.randint(-length, length), random.randint(-length // 5, length // 5)
        d.line([(x, y), (x + dx, y + dy)], fill=(*color, alpha), width=random.randint(max(width // 2, 1), width))
    layer = layer.filter(ImageFilter.GaussianBlur(max(w / 700, 0.8)))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _canvas_texture(img):
    noise = Image.effect_noise(img.size, 22).convert("RGB")
    return ImageChops.blend(img, ImageChops.multiply(img, ImageChops.invert(noise).point(lambda v: 200 + v // 5)), 0.35)


def landscape(size, sky, land, sun=None, water=False):
    w, h = size
    img = _gradient(size, sky[0], sky[1])
    d = ImageDraw.Draw(img)
    if sun:
        r = w // 12
        d.ellipse([w * 0.68 - r, h * 0.28 - r, w * 0.68 + r, h * 0.28 + r], fill=sun)
    horizon = int(h * (0.62 if water else 0.55))
    for i, color in enumerate(land):
        base = horizon + i * h // 10
        pts = [(0, h)] + [(x, base - int(h * 0.08 * random.random()) - (i == 0) * int(h * 0.05)) for x in range(0, w + 60, 60)] + [(w, h)]
        d.polygon(pts, fill=color)
    if water:
        water_img = _gradient((w, h - horizon - h // 8), _lerp(sky[1], (255, 255, 255), .2), sky[0])
        img.paste(water_img, (0, horizon + h // 8))
    img = img.filter(ImageFilter.GaussianBlur(w / 300))
    return _strokes(img, [*land, *sky], count=w // 2, length=w // 18, width=max(w // 90, 3))


def flowers(size, bg, petals, leaves, vase):
    w, h = size
    img = _gradient(size, bg, _lerp(bg, (40, 36, 30), .25))
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * .78), w, h], fill=_lerp(bg, (120, 100, 80), .45))
    vx = w // 2
    d.polygon([(vx - w * .12, h * .82), (vx + w * .12, h * .82), (vx + w * .08, h * .55), (vx - w * .08, h * .55)], fill=vase)
    for _ in range(9):
        x, y = vx + random.randint(-w // 4, w // 4), random.randint(int(h * .3), int(h * .56))
        d.line([(vx, h * .58), (x, y)], fill=leaves, width=max(w // 120, 2))
    for _ in range(26):
        cx, cy = vx + random.gauss(0, w * .16), random.gauss(h * .3, h * .1)
        r = random.randint(w // 26, w // 14)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=random.choice(petals))
    img = img.filter(ImageFilter.GaussianBlur(w / 260))
    return _strokes(img, [*petals, leaves], count=w, length=w // 25, width=max(w // 80, 3))


def still_life(size, bg, table, objects):
    w, h = size
    img = _gradient(size, bg, _lerp(bg, (20, 18, 15), .35))
    d = ImageDraw.Draw(img)
    d.polygon([(0, h * .62), (w, h * .58), (w, h), (0, h)], fill=table)
    for i, color in enumerate(objects):
        cx = w * (.3 + .22 * i)
        r = w * random.uniform(.09, .14)
        d.ellipse([cx - r, h * .66 - 2 * r, cx + r, h * .66], fill=color)
        d.ellipse([cx - r * .35, h * .66 - 1.7 * r, cx - r * .05, h * .66 - 1.4 * r], fill=_lerp(color, (255, 255, 255), .45))
    img = img.filter(ImageFilter.GaussianBlur(w / 240))
    return _strokes(img, [bg, table, *objects], count=w // 2, length=w // 22, width=max(w // 70, 3))


def abstract(size, colors):
    w, h = size
    img = Image.new("RGB", size, colors[0])
    d = ImageDraw.Draw(img)
    for _ in range(14):
        x, y = random.randrange(w), random.randrange(h)
        rw, rh = random.randint(w // 8, w // 2), random.randint(h // 10, h // 3)
        d.rectangle([x - rw // 2, y - rh // 2, x + rw // 2, y + rh // 2], fill=random.choice(colors[1:]))
    img = img.filter(ImageFilter.GaussianBlur(w / 60))
    return _strokes(img, colors, count=w, length=w // 6, width=max(w // 40, 5), alpha=150)


def render(kind, w_cm, h_cm, **kw):
    size = (min(w_cm * PX_PER_CM, 1800), min(h_cm * PX_PER_CM, 1800))
    img = {"landscape": landscape, "flowers": flowers, "still": still_life, "abstract": abstract}[kind](size, **kw)
    buf = BytesIO()
    _canvas_texture(img).save(buf, "JPEG", quality=92)
    return buf.getvalue()


PAINTINGS = [
    dict(title="Туман над Окой", author="Ирина Соколова", technique="oil", genre="landscape", base="Холст на подрамнике", width_cm=60, height_cm=40, year=2025, price=38000, is_featured=True,
         art=("landscape", dict(sky=((214, 220, 222), (238, 232, 218)), land=[(150, 160, 150), (112, 128, 115), (80, 96, 84)], water=True))),
    dict(title="Сирень в синей вазе", author="Мария Ветрова", technique="oil", genre="flowers", base="Холст на подрамнике", width_cm=50, height_cm=60, year=2024, price=32000, is_featured=True,
         art=("flowers", dict(bg=(236, 228, 214), petals=[(186, 150, 205), (160, 120, 190), (214, 190, 228)], leaves=(92, 120, 78), vase=(60, 88, 150)))),
    dict(title="Утро в Калуге", author="Алексей Громов", technique="acrylic", genre="cityscape", base="Холст на подрамнике", width_cm=70, height_cm=50, year=2025, price=45000,
         art=("landscape", dict(sky=((244, 214, 180), (250, 238, 214)), land=[(196, 160, 132), (150, 110, 90), (110, 80, 70)], sun=(252, 222, 150)))),
    dict(title="Золотая осень", author="Ирина Соколова", technique="oil", genre="landscape", base="Холст на подрамнике", width_cm=80, height_cm=60, year=2024, price=55000, is_featured=True, framed=True,
         art=("landscape", dict(sky=((190, 210, 226), (232, 226, 206)), land=[(214, 168, 70), (184, 120, 50), (120, 80, 40)]))),
    dict(title="Пионы", author="Мария Ветрова", technique="watercolor", genre="flowers", base="Бумага", width_cm=30, height_cm=40, year=2025, price=12000,
         art=("flowers", dict(bg=(246, 240, 234), petals=[(236, 170, 180), (224, 140, 160), (248, 206, 210)], leaves=(120, 150, 110), vase=(210, 204, 196)))),
    dict(title="Ритм", author="Дмитрий Лаптев", technique="acrylic", genre="abstract", base="Холст на подрамнике", width_cm=100, height_cm=80, year=2025, price=None, is_featured=True,
         art=("abstract", dict(colors=[(240, 234, 222), (196, 102, 62), (48, 70, 96), (218, 180, 110), (30, 30, 30)]))),
    dict(title="Натюрморт с гранатом", author="Алексей Громов", technique="oil", genre="still_life", base="Холст на картоне", width_cm=40, height_cm=40, year=2024, price=24000, status="reserved",
         art=("still", dict(bg=(90, 80, 68), table=(150, 120, 92), objects=[(170, 40, 40), (214, 170, 80), (120, 30, 45)]))),
    dict(title="Зимний лес", author="Ирина Соколова", technique="oil", genre="landscape", base="Холст на подрамнике", width_cm=50, height_cm=70, year=2023, price=41000, status="sold",
         art=("landscape", dict(sky=((196, 206, 220), (236, 238, 240)), land=[(226, 230, 236), (150, 160, 172), (70, 84, 90)]))),
    dict(title="Морской бриз", author="Дмитрий Лаптев", technique="acrylic", genre="landscape", base="Холст на подрамнике", width_cm=90, height_cm=60, year=2025, price=62000,
         art=("landscape", dict(sky=((168, 204, 226), (226, 236, 238)), land=[(120, 170, 190), (70, 130, 160)], water=True))),
    dict(title="Лимоны", author="Мария Ветрова", technique="gouache", genre="still_life", base="Картон", width_cm=30, height_cm=30, year=2025, price=9000,
         art=("still", dict(bg=(210, 214, 200), table=(236, 232, 220), objects=[(240, 206, 60), (232, 190, 40)]))),
    dict(title="Васильки", author="Мария Ветрова", technique="pastel", genre="flowers", base="Бумага", width_cm=25, height_cm=35, year=2023, price=8000, status="sold",
         art=("flowers", dict(bg=(240, 236, 220), petals=[(70, 110, 200), (100, 140, 220), (230, 230, 240)], leaves=(110, 140, 90), vase=(190, 170, 140)))),
    dict(title="Закат на Угре", author="Алексей Громов", technique="oil", genre="landscape", base="Холст на подрамнике", width_cm=120, height_cm=80, year=2025, price=95000,
         art=("landscape", dict(sky=((236, 150, 110), (250, 214, 160)), land=[(120, 90, 90), (80, 60, 64), (50, 40, 44)], sun=(255, 228, 170), water=True))),
]

DESCRIPTION = (
    "Работа написана с натуры и доработана в мастерской художника. Много воздуха и мягкого света — "
    "картина хорошо смотрится и в светлой гостиной, и в спальне.\n\n"
    "Красочный слой покрыт защитным лаком. Картина готова к развеске."
)

REVIEWS = [
    ("Ольга", "Купила «Сирень в синей вазе»", "Картина вживую ещё красивее, чем на фото. Упаковано очень бережно, доехала до Москвы за три дня."),
    ("Андрей и Мария", "Картина на заказ", "Заказывали пейзаж для гостиной под размер стены. Подобрали художника, согласовали эскиз, получали фото по ходу работы — результат превзошёл ожидания."),
    ("Елена", "Подарок маме", "Выбирала подарок, помогли подобрать по фото комнаты. Мама в восторге, картина висит на самом видном месте."),
]


def main() -> None:
    Base.metadata.create_all(engine)
    terms.ensure_defaults()  # техники и жанры демо-картин берутся из справочников
    with SessionLocal() as db:
        for pid in db.scalars(select(Painting.id)):
            images.delete_painting_files(pid)
        for model in (Lead, Photo, Painting, Review):
            db.execute(delete(model))

        for i, data in enumerate(PAINTINGS):
            data = dict(data)
            kind, params = data.pop("art")
            p = Painting(description=DESCRIPTION, **data)
            p.created_at = datetime.now() - timedelta(days=i * 6)
            db.add(p)
            db.flush()
            name, w, h = images.save_photo(p.id, render(kind, p.width_cm, p.height_cm, **params))
            db.add(Photo(painting_id=p.id, name=name, width=w, height=h, sort=0))

        for author, caption, text in REVIEWS:
            db.add(Review(author=author, caption=caption, text=text))
        db.commit()
    print(f"Готово: {len(PAINTINGS)} картин, {len(REVIEWS)} отзыва.")


if __name__ == "__main__":
    main()
