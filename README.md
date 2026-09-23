# Quietwork

Live programs on Zoom for a (fictional) personal development teacher, Elena Marsh.
A portfolio piece by Andreea Tech. Brand and content rules: [`quietwork-brand.md`](quietwork-brand.md).

**What it does**

- Eight-week programs run as groups (cohorts) with fixed dates and a seat limit, plus a one-evening live workshop.
- Seats are held during Stripe Checkout and locked with `select_for_update()`, so the last seat can't be sold twice.
- Pay in full, or in monthly instalments (a Stripe subscription that stops itself after the last payment).
- The Zoom link is never in the page: `/my/sessions/<id>/join/` redirects to it only for paid members, from 15 minutes before the start.
- Members get a session page per week: exercise, recording (unlisted YouTube), Elena's notes, and "mark as done". The thread fills in as they go.
- After paying, a welcome screen shows the member's seat among the group ("You're 9 of 12") and the first session.
- "Add to calendar" (.ics) for all sessions, with a reminder 15 minutes before. Events link to the session page, never to Zoom.
- Every time is also shown in the visitor's own time zone ("19:00 CET · 13:00 for you").
- Program pages: sessions open to their theme, and a FAQ edited in the admin.
- Waitlist for full groups and workshops; Elena emails everyone once from the admin when a seat opens.
- Private reflections per session, and "Your thread": a drawing of the program shaped by the member, saved as an image.
- Portfolio demo mode: "Explore as a member" opens a throwaway account with sample data, a switch to see the Zoom button open, and a preview of the after-payment screen.
- Elena manages programs, topics, groups, sessions, recordings, notes, FAQ and the waitlist in the Django admin.

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
   `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and the `EMAIL_*` settings (password resets, waitlist emails).
   Set `DEMO_MODE=1` for the portfolio demo; leave it unset for a real client.
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
