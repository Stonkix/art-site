# Сайт продажи картин

FastAPI + SQLite + Jinja2 + HTMX + sqladmin. Без Node и сборки фронтенда, шрифты и скрипты лежат в `app/static`.

## Страницы

| Страница | Адрес |
|---|---|
| Главная: первый экран с картиной, избранное, новые поступления, жанры, преимущества, картина на заказ, о галерее, отзывы | `/` |
| Каталог: жанры-чипсы, фильтры по технике, размеру, бюджету, «показать проданные» — без перезагрузки (HTMX) | `/catalog` |
| Картина: фото с увеличением деталей, автор и характеристики, похожие работы | `/catalog/{id}` |
| Покупка и доставка, работа на заказ | `/how-to-buy` |
| О галерее, проданные работы («Уже нашли свой дом»), отзывы, контакты с формой | `/about` |
| Политика ПДн и отдельная страница согласия | `/privacy`, `/consent` |
| Панель управления: картины (фото перетаскиванием, автор — необязательно), заявки, отзывы, «О галерее» | `/admin` |

Под капотом:
- **Фото картин** сжимаются в WebP (900 и 2200 px), EXIF и GPS удаляются. Для превью в мессенджерах картина кладётся целиком на светлый фон, без обрезки краёв.
- **Заявки** («Хочу купить», «Вопрос», «На заказ», «Перезвоните») сохраняются в БД и уходят на почту.
- **Статусы**: «В наличии», «Забронирована», «Продана». Проданные уходят из каталога, но остаются в портфолио.
- **SEO**: Open Graph, `VisualArtwork` (Schema.org), sitemap.
- **Вход в панель**: 5 неверных паролей с одного IP — блокировка на 24 часа (`python -m app.login_guard --reset` снимает).

## Запуск локально

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
echo DEBUG=true> .env
.venv\Scripts\python seed.py
.venv\Scripts\uvicorn app.main:app --reload
```

`seed.py` создаёт 12 демо-картин (картинки нарисованы программно — это заглушки). Тесты: `.venv\Scripts\python -m pytest -q`.

Тексты «Почему покупают здесь», «Покупка и доставка» и условия заказа — заготовки в `app/templates/index.html` и `app/templates/how_to_buy.html`, их стоит сверить с реальными условиями.

## Деплой рядом с другим сайтом на том же VDS

Сайт живёт в `/srv/artsite`, слушает `127.0.0.1:8001`, служба `artsite`. Вместо `DOMAIN` — домен сайта (пока он не куплен, подойдёт поддомен, например `site2.corelms.online` с A-записью на IP сервера).

```bash
git clone https://github.com/Stonkix/art-site.git /srv/artsite
useradd --system --home /srv/artsite --shell /usr/sbin/nologin artsite
cd /srv/artsite && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p data media && chown artsite:artsite data media
cp .env.example .env && nano .env && chown root:artsite .env && chmod 640 .env
cp deploy/artsite.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now artsite
sed 's/DOMAIN/site2.corelms.online/g' deploy/nginx.conf > /etc/nginx/sites-available/artsite
ln -s /etc/nginx/sites-available/artsite /etc/nginx/sites-enabled/ && nginx -t && systemctl reload nginx
certbot --nginx -d site2.corelms.online --redirect
chmod +x deploy/backup.sh  # и строка в crontab: 45 3 * * * /srv/artsite/deploy/backup.sh
```

Обновление: `cd /srv/artsite && git pull && .venv/bin/pip install -r requirements.txt && systemctl restart artsite`.

Переезд на купленный домен: заменить домен в `/etc/nginx/sites-available/artsite` и `BASE_URL` в `.env`, затем `certbot --nginx -d новый-домен.ru` и `systemctl restart artsite`.
