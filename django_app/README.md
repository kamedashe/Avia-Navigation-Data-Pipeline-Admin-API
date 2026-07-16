# Avia Navigation — Django backend

A pure-Django port of the original FastAPI service. It serves aviation data
files from disk and renders the admin dashboard. All public API paths are
identical to the FastAPI version, so existing mobile clients need no changes.

## Layout

```
django_app/
├── manage.py
├── requirements.txt
├── Dockerfile
├── compose.yaml
├── avia_nav/            # Django project (settings, urls, wsgi/asgi)
└── api/                 # The single Django app
    ├── auth.py          # Bearer / Basic token auth for admin endpoints
    ├── urls.py          # All routes (1:1 with the old FastAPI paths)
    ├── dashboard.html   # Admin dashboard markup (served with token injected)
    ├── services/        # safety_check, task_status, file_handlers
    └── views/           # root, files, changes, maps, diagrams, admin_dashboard
```

Data directories (`data/`, `downloaded_data/`, `processed_data/`) and the
`web_scraper/` package live in the **project root** (`apisaero-transfer/`),
one level above `django_app/`, exactly as before. The scraper is still invoked
as a subprocess (`python -m web_scraper.script -<flag>`); it was not rewritten.

## Routes (unchanged from FastAPI)

| Method | Path | Auth |
|--------|------|------|
| GET | `/` | — |
| GET | `/api/b/` … `/api/r/`, `/api/t/` | public |
| GET | `/api/changes/` | public |
| GET | `/api/v1/a-big`, `/api/v1/a-big/{state}`, `/api/v1/a-big/{state}/{code}`, `/api/v1/a-big/download` | public |
| GET | `/api/v1/a-small`, `/api/v1/a-small/{code}`, `/api/v1/a-small/download` | public |
| GET | `/api/v1/maps`, `/api/v1/maps/{file}.mbtiles`, `/api/v1/maps/info`, `/api/v1/maps/info/{file}.json` | public |
| GET | `/api/v1/airports`, `/api/v1/airports/{identifier}` | public (Postgres/ORM) |
| GET | `/admin` | **Basic** (password = `AUTH_TOKEN`) |
| GET | `/api/status`, `/api/task-status` | **Bearer** `AUTH_TOKEN` |
| POST | `/api/run/{flag}` | **Bearer** `AUTH_TOKEN` |

### Auth change vs. the original
The FastAPI app *sent* a Bearer token from the dashboard but never checked it
server-side. This port enforces it:
- `/api/status`, `/api/task-status`, `/api/run/*` require `Authorization: Bearer <AUTH_TOKEN>` (already sent by the dashboard JS).
- `/admin` is gated with HTTP Basic auth so a plain browser navigation can be
  challenged — enter any username and `AUTH_TOKEN` as the password.
- If `AUTH_TOKEN` is unset, auth is **disabled** (a warning is logged), matching
  the original app's tolerance of a missing token.

## Configuration

Uses the same `.env` in the project root as the scraper:

```env
AUTH_TOKEN=your_secure_admin_token
RSYNC_SOURCE=mb@127.0.0.1:/home/mb/faa_vfr

# PostgreSQL (blank falls back to the compose defaults below)
PGHOST=localhost
PGPORT=5432
PGUSER=admin
PGPASSWORD=test_password
PGDATABASE=postgres

# Optional Django knobs
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=*
```

## Run — local dev

```bash
cd django_app
pip install -r requirements.txt

# Start PostgreSQL (or point PG* at your own instance)
docker compose -f compose.yaml up -d db

python manage.py migrate
python manage.py import_airports        # loads data/b.csv.gz into Postgres
python manage.py runserver 0.0.0.0:5045
```

### Data import

`import_airports` unpacks the scraper's denormalized `data/b.csv.gz` (one row
per airport with up to 11 inline runway groups) into `Airport` + `Runway`
rows. It is idempotent — each run replaces the table contents, mirroring how
the scraper regenerates the CSV each cycle.

```bash
python manage.py import_airports --dry-run          # parse & report, no writes
python manage.py import_airports --path other.csv.gz
```

The file-download endpoints (`/api/b/` etc.) still serve the CSVs straight
from disk and do **not** depend on the database.

## Run — production (gunicorn)

```bash
cd django_app
gunicorn --chdir . -w 4 -k gthread --threads 4 --timeout 600 \
    --bind 0.0.0.0:5045 avia_nav.wsgi:application
```

## Run — Docker

```bash
# from the project root
docker compose -f django_app/compose.yaml up -d --build
```

The API is available at `http://your-server-ip:5045`.
