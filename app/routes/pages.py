import math
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import SIZE_GROUPS, Painting, Review
from app.terms import get_genres, get_techniques
from app.templating import templates

router = APIRouter()

PAGE_SIZE = 12
SORTS = {
    "new": ("Сначала новые", Painting.created_at.desc()),
    "price_asc": ("Сначала дешевле", Painting.price.asc().nulls_last()),
    "price_desc": ("Сначала дороже", Painting.price.desc().nulls_last()),
}


def published():
    return select(Painting).where(Painting.is_published.is_(True))


def available():
    return published().where(Painting.status != "sold")


def _int(value: str | None) -> int | None:
    try:
        return int(re.sub(r"\s", "", value or ""))
    except ValueError:
        return None


def _size_condition(group: str):
    w, h = Painting.width_cm, Painting.height_cm
    if group == "small":
        return and_(w <= 40, h <= 40)
    if group == "medium":
        return and_(w <= 80, h <= 80, or_(w > 40, h > 40))
    return or_(w > 80, h > 80)


@dataclass
class CatalogFilters:
    technique: str = ""
    genre: str = ""
    size: str = ""
    price_max: int | None = None
    sold: bool = False  # показывать и проданные — как портфолио
    sort: str = "new"
    page: int = 1

    @classmethod
    def from_request(cls, request: Request) -> "CatalogFilters":
        qp = request.query_params
        pick = lambda key, allowed: qp.get(key, "") if qp.get(key, "") in allowed else ""  # noqa: E731
        return cls(
            technique=pick("technique", get_techniques()),
            genre=pick("genre", get_genres()),
            size=pick("size", SIZE_GROUPS),
            price_max=_int(qp.get("price_max")),
            sold=qp.get("sold") == "1",
            sort=qp.get("sort") if qp.get("sort") in SORTS else "new",
            page=max(_int(qp.get("page")) or 1, 1),
        )

    def apply(self, q):
        if not self.sold:
            q = q.where(Painting.status != "sold")
        if self.technique:
            q = q.where(Painting.technique == self.technique)
        if self.genre:
            q = q.where(Painting.genre == self.genre)
        if self.size:
            q = q.where(_size_condition(self.size))
        if self.price_max:
            q = q.where(Painting.price <= self.price_max)
        return q

    def query_string(self, **override) -> str:
        params = {
            "technique": self.technique,
            "genre": self.genre,
            "size": self.size,
            "price_max": self.price_max,
            "sold": "1" if self.sold else None,
            "sort": self.sort if self.sort != "new" else None,
            "page": self.page if self.page > 1 else None,
        } | override
        return urlencode({k: v for k, v in params.items() if v not in (None, "")})


@router.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    featured = db.scalars(
        available().where(Painting.is_featured.is_(True)).order_by(Painting.created_at.desc()).limit(8)
    ).all()
    newest = db.scalars(available().order_by(Painting.created_at.desc()).limit(8)).all()
    hero = next((p for p in [*featured, *newest] if p.cover), None)
    reviews = db.scalars(
        select(Review).where(Review.is_published.is_(True)).order_by(Review.created_at.desc()).limit(3)
    ).all()
    total = db.scalar(select(func.count()).select_from(available().subquery())) or 0
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "hero": hero,
            "featured": featured,
            "newest": newest,
            "reviews": reviews,
            "total": total,
            "genre_counts": _genre_counts(db),
        },
    )


def _genre_counts(db: Session) -> list[tuple[str, int]]:
    rows = db.execute(
        select(Painting.genre, func.count())
        .where(Painting.is_published.is_(True), Painting.status != "sold")
        .group_by(Painting.genre)
        .order_by(func.count().desc())
    ).all()
    genres = get_genres()
    return [(g, n) for g, n in rows if g in genres]


@router.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request, db: Session = Depends(get_db)):
    f = CatalogFilters.from_request(request)
    q = f.apply(published())
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    f.page = min(f.page, pages)
    items = db.scalars(
        q.order_by(SORTS[f.sort][1], Painting.id.desc()).limit(PAGE_SIZE).offset((f.page - 1) * PAGE_SIZE)
    ).all()
    ctx = {"f": f, "items": items, "total": total, "pages": pages, "sorts": SORTS, "genre_counts": _genre_counts(db)}
    # HTMX-запрос от фильтров: отдаём только сетку, без шапки и фильтров
    is_htmx = request.headers.get("HX-Request") == "true" and not request.headers.get("HX-History-Restore-Request")
    response = templates.TemplateResponse(
        request, "partials/catalog_results.html" if is_htmx else "catalog.html", ctx
    )
    response.headers["Vary"] = "HX-Request"
    return response


@router.get("/catalog/{ref}", response_class=HTMLResponse)
def painting_detail(ref: str, request: Request, db: Session = Depends(get_db)):
    painting_id = _int(ref.split("-", 1)[0])
    p = db.get(Painting, painting_id) if painting_id else None
    if not p or not p.is_published:
        raise HTTPException(404)
    if request.url.path != p.url:
        return RedirectResponse(p.url, status_code=301)

    similar = db.scalars(
        available()
        .where(Painting.id != p.id, or_(Painting.genre == p.genre, Painting.technique == p.technique))
        .order_by((Painting.genre == p.genre).desc(), Painting.created_at.desc())
        .limit(4)
    ).all()
    return templates.TemplateResponse(
        request,
        "painting.html",
        {"p": p, "similar": similar, "json_ld": _artwork_json_ld(p)},
    )



def _artwork_json_ld(p: Painting) -> dict:
    url = settings.base_url + p.url
    data: dict = {
        "@context": "https://schema.org",
        "@type": "VisualArtwork",
        "name": p.title,
        "url": url,
        "description": p.description[:500],
        "artform": "Живопись",
        "artMedium": p.technique_name,
        "width": {"@type": "Distance", "name": f"{p.width_cm} см"},
        "height": {"@type": "Distance", "name": f"{p.height_cm} см"},
        "image": [settings.base_url + ph.full for ph in p.photos[:5]],
    }
    if p.author:
        data["creator"] = {"@type": "Person", "name": p.author}
    if p.base:
        data["artworkSurface"] = p.base
    if p.year:
        data["dateCreated"] = str(p.year)
    if p.price:
        data["offers"] = {
            "@type": "Offer",
            "price": p.price,
            "priceCurrency": "RUB",
            "availability": "https://schema.org/SoldOut" if p.is_sold else "https://schema.org/InStock",
            "url": url,
        }
    return data


@router.get("/how-to-buy", response_class=HTMLResponse)
def how_to_buy(request: Request):
    return templates.TemplateResponse(request, "how_to_buy.html")


@router.get("/about", response_class=HTMLResponse)
def about(request: Request, db: Session = Depends(get_db)):
    reviews = db.scalars(
        select(Review).where(Review.is_published.is_(True)).order_by(Review.created_at.desc())
    ).all()
    sold = db.scalars(
        published().where(Painting.status == "sold").order_by(Painting.updated_at.desc()).limit(8)
    ).all()
    return templates.TemplateResponse(request, "about.html", {"reviews": reviews, "sold": sold})


@router.get("/contacts")
def contacts():
    return RedirectResponse("/about#contacts", status_code=301)


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html")


@router.get("/consent", response_class=HTMLResponse)
def consent(request: Request):
    return templates.TemplateResponse(request, "consent.html")


@router.get("/thanks", response_class=HTMLResponse)
def thanks(request: Request):
    return templates.TemplateResponse(request, "thanks.html")

