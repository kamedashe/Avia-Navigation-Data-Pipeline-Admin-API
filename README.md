# ✈️ Avia Navigation Data Pipeline & Admin API

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.x-092e20.svg)](https://www.djangoproject.com/)
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

---

## 🚀 Technical Stack

- **Core**: Python 3.10+
- **API**: Django (WSGI, served with Gunicorn)
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
```

### 3. Execution
**Run the API (Django dev server):**
```bash
cd django_app
python manage.py runserver 0.0.0.0:5045
```
No `migrate` is needed — the API touches no database. See
[`django_app/README.md`](django_app/README.md) for the production Gunicorn command.

**Run the Scraper manually:**
```bash
python3 -m web_scraper.script -b # Update Base Airports
```

---

## 🐳 Docker Deployment

The project is fully containerized for seamless server deployment.

```bash
# Build and start the infrastructure (from the project root)
docker compose -f django_app/compose.yaml up -d --build

# View logs
docker compose -f django_app/compose.yaml logs -f
```

The production API will be available at `http://your-server-ip:5045`.

---

## 📐 Project Structure

```text
├── django_app/        # Django backend (see django_app/README.md)
│   ├── avia_nav/      # Project settings, urls, wsgi/asgi
│   └── api/           # Views, services, admin dashboard
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
