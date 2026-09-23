# Quietwork

Live programs on Zoom for a (fictional) personal development teacher, Elena Marsh.
A portfolio piece by Andreea Tech. Brand and content rules: [`quietwork-brand.md`](quietwork-brand.md).

**What it does**

- Eight-week programs run as groups (cohorts) with fixed dates and a seat limit, plus a one-evening live workshop.
- Seats are held during Stripe Checkout and locked with `select_for_update()`, so the last seat can't be sold twice.
- Pay in full, or in monthly instalments (a Stripe subscription that stops itself after the last payment).
- The Zoom link is never in the page: `/my/sessions/<id>/join/` redirects to it only for paid members, from 15 minutes before the start.
- Members get a session page per week: exercise, recording (unlisted YouTube), Elena's notes, and "mark as done". The thread fills in as they go.
- Elena manages programs, topics, groups, sessions, recordings and notes in the Django admin.

**Stack:** Django 5.2, Django REST Framework, PostgreSQL, Stripe Checkout, WhiteNoise, Gunicorn.

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
createdb quietwork                          # PostgreSQL
export DEBUG=1 DATABASE_URL=postgres://USER:PASS@localhost:5432/quietwork
python manage.py migrate
python manage.py seed_demo                  # Elena's programs, groups and the workshop
python manage.py createsuperuser
python manage.py runserver
```

Payments locally: set `STRIPE_SECRET_KEY` (test mode), then
`stripe listen --forward-to localhost:8000/stripe/webhook/` and set the printed `STRIPE_WEBHOOK_SECRET`.

Tests: `DEBUG=1 python manage.py test`

## Deploy on Render

1. **New → PostgreSQL** and copy its *Internal Database URL*.
2. **New → Web Service** from this repo (Python runtime):
   - Build command: `./build.sh`
   - Start command: `gunicorn config.wsgi:application`
3. Environment variables: `SECRET_KEY` (long random), `DATABASE_URL`, `SITE_URL` (e.g. `https://quietwork.onrender.com`),
   `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and optionally the `EMAIL_*` settings for password-reset emails.
   `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` pick up Render's hostname automatically.
4. In Stripe → Developers → Webhooks, add `https://<your-site>/stripe/webhook/` with these events:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`,
   `checkout.session.expired`, `invoice.paid`, `invoice.payment_failed`.
5. Render Shell: `python manage.py createsuperuser` and, for the demo, `python manage.py seed_demo`.

## API

| Endpoint | Who | What |
|---|---|---|
| `GET /api/programs/` | anyone | Published programs and their next open group |
| `GET /api/cohorts/<id>/availability/` | anyone | Seats left in a group |
| `GET /api/workshops/<slug>/availability/` | anyone | Seats left at a workshop |
| `GET /api/me/next/` | member | Next session or workshop (never the Zoom link) |
| `PUT/DELETE /api/sessions/<id>/completion/` | member | Mark a session done / not done |
