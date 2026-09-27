from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Painting

router = APIRouter()

STATIC_PAGES = [("/", "1.0"), ("/catalog", "0.9"), ("/how-to-buy", "0.5"), ("/about", "0.6")]


@router.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    base = settings.base_url
    urls = [f"<url><loc>{base}{path}</loc><priority>{prio}</priority></url>" for path, prio in STATIC_PAGES]
    for p in db.scalars(select(Painting).where(Painting.is_published.is_(True))):
        prio = "0.5" if p.is_sold else "0.8"
        urls.append(
            f"<url><loc>{escape(base + p.url)}</loc>"
            f"<lastmod>{p.updated_at.date().isoformat()}</lastmod><priority>{prio}</priority></url>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(xml, media_type="application/xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Disallow: /lead\n"
        "Clean-param: sort&page /catalog\n"  # директива Яндекса против дублей
        f"\nSitemap: {settings.base_url}/sitemap.xml\n"
    )
