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

## Deploying to AWS (EC2)

Single EC2 instance running the same `docker compose` stack as above — no
ECS/RDS, mirrors the existing ops model. Requires the AWS CLI configured
(`aws configure`) with an IAM user, not root credentials.

### 1. Provision

```bash
# Security group: SSH from your IP only, API/HTTP/HTTPS open
MYIP=$(curl -s https://checkip.amazonaws.com)
SG=$(aws ec2 create-security-group --group-name avia-server-sg \
  --description "Avia Navigation API server" --vpc-id <VPC_ID> --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 22 --cidr ${MYIP}/32
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 5045 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG --protocol tcp --port 443 --cidr 0.0.0.0/0

# SSH key pair
aws ec2 create-key-pair --key-name avia-key --query KeyMaterial --output text > ~/.ssh/avia-aws.pem
chmod 400 ~/.ssh/avia-aws.pem   # icacls on Windows — grant only your own user Read

# Latest Ubuntu 24.04 LTS AMI
AMI=$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)

# Instance — t3.micro/t3.small; user-data installs Docker + a 2G swap file
aws ec2 run-instances --image-id $AMI --instance-type t3.micro \
  --key-name avia-key --security-group-ids $SG --subnet-id <SUBNET_ID> \
  --user-data file://infra/aws/user-data.sh \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=avia-server}]'

# Elastic IP so the address survives instance stop/start
ALLOC=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id <INSTANCE_ID> --allocation-id $ALLOC
```

Wait for cloud-init to finish before deploying (`user-data.sh` touches
`/var/lib/cloud/instance/bootstrap-done` as its last step):

```bash
until ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "test -f /var/lib/cloud/instance/bootstrap-done && docker --version"; do sleep 15; done
```

### 2. First deploy

```bash
ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "git clone https://github.com/<you>/<repo>.git avia"

# .env is gitignored — create it directly on the box
ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> "cat > avia/.env" <<'EOF'
AUTH_TOKEN=<generate a strong token>
PGPASSWORD=<generate a strong password>
DJANGO_DEBUG=false
EOF
ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> "cat > avia/django_app/.env" <<'EOF'
PGPASSWORD=<same password as above>
EOF

# data/b.csv.gz is gitignored too — the scraper produces it, but a fresh
# clone starts empty, so seed it once from wherever it's currently generated
scp -i ~/.ssh/avia-aws.pem data/b.csv.gz ubuntu@<ELASTIC_IP>:avia/data/b.csv.gz

ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "cd avia && docker compose -f django_app/compose.yaml up -d --build"

ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "cd avia && docker compose -f django_app/compose.yaml exec -T app python django_app/manage.py migrate"
ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "cd avia && docker compose -f django_app/compose.yaml exec -T app python django_app/manage.py import_airports"
```

### 3. Redeploying after changes

```bash
ssh -i ~/.ssh/avia-aws.pem ubuntu@<ELASTIC_IP> \
  "cd avia && git pull && docker compose -f django_app/compose.yaml up -d --build"
```

### Known gaps

- **No TLS/domain yet** — the API is served as plain HTTP on port 5045.
  Once a domain points at the Elastic IP, put a reverse proxy (e.g. Caddy,
  which handles Let's Encrypt automatically) in front of `app` in
  `compose.yaml`.
- **rsync from "Server B"** (`/api/v1/a-big`, `/api/v1/a-small`,
  `m_sectional` diagrams/maps sync) needs the EC2 instance to actually reach
  Server B over SSH — confirm `RSYNC_SOURCE` in `.env` resolves from the new
  network before relying on those endpoints in this environment.
- Postgres runs as a container on the same instance (no RDS) — single point
  of failure for data. `pg_dump` to S3 or an EBS snapshot schedule is worth
  adding before this holds anything you can't regenerate from `import_airports`.
