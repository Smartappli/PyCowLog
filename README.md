# PyBehaviorLog 0.8.3

PyBehaviorLog is an ASGI-first behavioral observation platform built with Django 6.0.3. It is designed for research teams who need video-assisted coding, live observations, structured ethograms, review workflows, and exportable analytics without being locked into a desktop-only workflow.

## What is in this 0.8.3 archive

This version extends the earlier CowLog/BORIS-inspired foundations with:

- projects, role-based memberships, videos, and observation sessions
- point and state behaviors with keyboard bindings
- modifiers, subjects, subject groups, and independent variables
- synchronized videos and live observation sessions
- annotations, review states, and audit trail entries
- JSON, CSV, TSV, XLSX, BORIS-compatible project/session exports, and reproducibility bundles
- project-level analytics, transition summaries, and subject-based statistics
- multilingual interface support limited to English, Arabic, Chinese, Spanish, French, and Russian
- ASGI deployment with Granian
- PostgreSQL 18 + Redis 8 container stack
- Argon2 password hashing
- database-backed sessions
- Django 6 built-in CSP middleware support
- unit tests, coverage gate, pre-commit, and GitHub Actions CI

## Design direction

The user interface deliberately avoids the glossy "generic AI dashboard" style. The visual system uses a field notebook / research console theme: warm paper tones, restrained contrast, dense but readable information blocks, and controls that feel closer to an observation workstation than to a marketing template.

## Runtime stack

- Python 3.13+
- Django 6.0.3
- Granian (ASGI server)
- PostgreSQL 18
- Redis 8
- psycopg 3 with connection pooling
- openpyxl for spreadsheet exports
- argon2-cffi for password hashing

## Quick start (local SQLite fallback)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Quick start with Docker

```bash
cp .env.example .env
docker compose up --build
```

The default Docker stack starts:

- `web`: Django on Granian / ASGI
- `db`: PostgreSQL 18
- `redis`: Redis 8

## Development workflow

```bash
pip install -r requirements-dev.txt
pre-commit install
python manage.py test
coverage run manage.py test
coverage report --fail-under=80
```

## Language support

PyBehaviorLog exposes a focused `LANGUAGES` list in the interface selector limited to the project languages requested for deployment: English, Arabic, Chinese, Spanish, French, and Russian.

The application uses Django's i18n infrastructure (`LocaleMiddleware`, the `set_language` endpoint, locale paths, and translatable templates) so translations can continue to evolve without changing the architecture.

## Repository quality controls

The repository includes:

- `.pre-commit-config.yaml`
- `.github/workflows/ci.yml`
- coverage configuration with an 80% gate on the `tracker` app
- a trimmed dependency set limited to the packages actually used by the project

## Documentation

Additional English documentation is available in:

- `docs/architecture.md`
- `docs/deployment.md`

## License

This repository is marked as **AGPL-3.0-only**.
