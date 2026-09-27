import time
from collections import defaultdict, deque

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import mailer
from app.db import get_db
from app.models import LEAD_KINDS, Lead, Painting
from app.templating import templates
from app.utils import normalize_phone

router = APIRouter()

RATE_LIMIT = 5  # заявок
RATE_WINDOW = 600  # за 10 минут с одного IP
_recent: dict[str, deque[float]] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _recent[ip]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False


@router.post("/lead", response_class=HTMLResponse)
def create_lead(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    name: str = Form(""),
    phone: str = Form(""),
    message: str = Form(""),
    kind: str = Form("callback"),
    painting_id: int | None = Form(None),
    consent: bool = Form(False),
    website: str = Form(""),  # honeypot: скрытое поле, люди его не заполняют
):
    is_htmx = request.headers.get("HX-Request") == "true"
    kind = kind if kind in LEAD_KINDS else "callback"
    form = {"name": name, "phone": phone, "message": message, "kind": kind, "painting_id": painting_id}

    def respond(template: str, **ctx):
        if is_htmx:
            return templates.TemplateResponse(request, template, form | ctx)
        return RedirectResponse("/thanks" if template.endswith("success.html") else "/about#contacts", 303)

    if website:
        return respond("partials/lead_success.html")  # боту делаем вид, что всё ок

    normalized = normalize_phone(phone)
    error = None
    if not name.strip():
        error = "Укажите, как к вам обращаться"
    elif not normalized:
        error = "Проверьте номер телефона"
    elif not consent:
        error = "Нужно согласие на обработку персональных данных"
    elif _rate_limited(request.client.host if request.client else "?"):
        error = "Слишком много заявок. Позвоните, пожалуйста, по телефону"
    if error:
        return respond("partials/lead_form.html", error=error)

    painting = db.get(Painting, painting_id) if painting_id else None
    lead = Lead(
        kind=kind,
        name=name.strip()[:100],
        phone=normalized,
        message=message.strip()[:2000],
        painting_id=painting.id if painting else None,
    )
    db.add(lead)
    db.commit()
    background.add_task(mailer.send_lead, lead, painting)
    return respond("partials/lead_success.html")
