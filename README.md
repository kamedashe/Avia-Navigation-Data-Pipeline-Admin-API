# ✈️ Avia Navigation Data Pipeline & Admin API

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.x-092e20.svg)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-enabled-2496ed.svg)](https://www.docker.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A robust, enterprise-grade aviation data processing engine. This system automates the acquisition, parsing, and optimization of FAA aeronautical data, providing a high-performance API and a modern administrative dashboard.

<p align="center">
  <img src="assets/dashboard.png" alt="Avia Navigation Admin Dashboard" width="100%" />
</p>

> The backend lives in **[`django_app/`](django_app/README.md)** (Django). The
> data pipeline lives in **`web_scraper/`** and is invoked by the server as a
> subprocess. See `django_app/README.md` for the full API route table and
> deployment details.

---

## ✨ Key Features

### 🛠️ Intelligent Data Scraper
- **Automated Lifecycle**: Periodically fetches and processes FAA 28-day NASR subscriptions.
- **Fail-Soft Architecture**: Each data flag (`-b`, `-f`, `-d`, etc.) runs in isolated try/except blocks.
- **Auto-Cleanup**: Intelligent disk management that preserves only the most recent datasets.
- **Validation**: Strict ZIP integrity checks to prevent data corruption.

### 🖥️ Glassmorphism Admin Dashboard
- **Modern UI**: Sleek, dark-mode administrative panel with real-time task tracking.
- **Monitoring**: Live updates on file sizes, last modification timestamps, and task execution states.
- **Remote Control**: Trigger specific data updates directly from the web interface.

### 🔔 Telegram Alerting System
- **Real-time Notifications**: Instant alerts for processing errors, corrupted files, or system connectivity issues.
- **Actionable Logs**: Direct links and error tracebacks sent straight to your dev group.

### 🗄️ Queryable Airport Database
- **Normalized Schema**: The scraper's denormalized 72-column airport CSV is unpacked into `Airport` + `Runway` tables (19K airports, 23K runways).
- **Idempotent Import**: `manage.py import_airports` reloads the dataset each cycle without duplicating rows.
- **Query API**: Paginated, filterable endpoints served straight from PostgreSQL — additive, so the legacy file downloads keep working unchanged.

---

## 🚀 Technical Stack

- **Core**: Python 3.10+
- **API**: Django (WSGI, served with Gunicorn)
- **Database**: PostgreSQL 16 (via the Django ORM)
- **Data**: Pandas, GeoPandas (Spatial data optimization)
- **UI**: Tailwind CSS, Glassmorphism design system
- **DevOps**: Docker, Docker Compose

---

## 🛠️ Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/aviation-navigation-server.git
cd aviation-navigation-server

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install the server (Django) + scraper dependencies
pip install -r django_app/requirements.txt
```

### 2. Configuration
Create a `.env` file in the root directory based on `sample_env`:
```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
AUTH_TOKEN=your_secure_admin_token

# PostgreSQL — optional locally: left blank, these fall back to the
# credentials of the bundled db service (admin / test_password / postgres).
PGHOST=
PGPORT=
PGUSER=
PGPASSWORD=
PGDATABASE=
```

### 3. Execution
**Start PostgreSQL** (or point the `PG*` vars at your own instance):
```bash
docker compose -f django_app/compose.yaml up -d db
```

**Run the API (Django dev server):**
```bash
cd django_app
python manage.py migrate
python manage.py import_airports   # loads data/b.csv.gz into PostgreSQL
python manage.py runserver 0.0.0.0:5045
```
See [`django_app/README.md`](django_app/README.md) for the production Gunicorn
command and the full API route table.

**Run the Scraper manually:**
```bash
python3 -m web_scraper.script -b # Update Base Airports
```

---

## 🐳 Docker Deployment

The project is fully containerized for seamless server deployment.

The stack bundles the API and a healthchecked PostgreSQL 16 service the app
waits on.

```bash
# Build and start the infrastructure (from the project root)
docker compose -f django_app/compose.yaml up -d --build

# Create the schema and load the airport dataset
docker compose -f django_app/compose.yaml exec app python django_app/manage.py migrate
docker compose -f django_app/compose.yaml exec app python django_app/manage.py import_airports

# View logs
docker compose -f django_app/compose.yaml logs -f
```

The production API will be available at `http://your-server-ip:5045`.

pgAdmin is opt-in via the `tools` profile (then browse to `localhost:8080`):
```bash
docker compose -f django_app/compose.yaml --profile tools up -d pgadmin
```

---

## 📐 Project Structure

```text
├── django_app/        # Django backend (see django_app/README.md)
│   ├── compose.yaml   # API + PostgreSQL (+ optional pgAdmin)
│   ├── avia_nav/      # Project settings, urls, wsgi/asgi
│   └── api/           # Views, services, admin dashboard
│       ├── models.py     # Airport / Runway
│       ├── migrations/
│       └── management/   # import_airports command
├── web_scraper/       # Core scraping & processing logic (run as a subprocess)
│   ├── scraper_utils.py
│   ├── script.py      # Entry point for data processing
│   └── zip_utils.py
├── data/              # Processed CSV results
├── downloaded_data/   # Temporary storage for archives
└── requirements.txt   # Scraper dependencies (server deps in django_app/)
```

---

## 🛡️ Security

Admin endpoints are protected server-side via the `AUTH_TOKEN`: Bearer token on `/api/status`, `/api/task-status` and `/api/run/*`, and HTTP Basic on the `/admin` dashboard. Ensure your `AUTH_TOKEN` in `.env` is a strong, unique string. Public file-download endpoints remain open. See [`django_app/README.md`](django_app/README.md) for the full auth model.

---

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.

---
<p align="center">
  Developed with ❤️ for the Avia Navigation Project
</p>
