# Django backend for Avia Navigation.
# Build context MUST be the project root (apisaero-transfer/) so that both
# django_app/ and web_scraper/ are copied into the image.
FROM python:3.12-slim

WORKDIR /code

# Copy the whole project (django_app, web_scraper, data dirs, .env, ...)
COPY . .

# System deps: rsync/ssh for Server B sync, g++/libgdal for geopandas
RUN apt-get update && \
    apt-get install -y rsync openssh-client g++ libgdal-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r django_app/requirements.txt

EXPOSE 5045

# --chdir puts avia_nav on the path; settings resolves PROJECT_ROOT to /code,
# where web_scraper lives (subprocess cwd).
CMD ["gunicorn", "--chdir", "django_app", "-w", "4", "-k", "gthread", "--threads", "4", \
     "--timeout", "600", "--bind", "0.0.0.0:5045", "avia_nav.wsgi:application"]
