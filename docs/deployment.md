# Deployment notes

## Recommended stack

- Python 3.13
- Django 6.0.3
- Granian
- PostgreSQL 18
- Redis 8

## Docker workflow

1. Copy the environment file:

   ```bash
   cp .env.example .env
   ```

2. Adjust secrets and hosts.

3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Create the first administrator:

   ```bash
   docker compose exec web python manage.py createsuperuser
   ```

## Static files

The entrypoint automatically runs:

- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`

## Production hardening checklist

- set `DJANGO_DEBUG=0`
- set a strong `DJANGO_SECRET_KEY`
- configure `DJANGO_ALLOWED_HOSTS`
- configure `DJANGO_CSRF_TRUSTED_ORIGINS`
- set `SESSION_COOKIE_SECURE=1`
- set `CSRF_COOKIE_SECURE=1`
- place the app behind TLS
- use durable PostgreSQL and Redis volumes

## Test and lint commands

```bash
python manage.py test
coverage run manage.py test
coverage report --fail-under=80
pre-commit run --all-files
```
