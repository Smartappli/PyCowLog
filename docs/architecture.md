# Architecture overview

## Application layers

PyBehaviorLog is intentionally compact. The project keeps one main Django app, `tracker`, because the domain model is tightly connected and easier to understand without artificial fragmentation.

### Core entities

- **Project**: ownership, collaborators, and all observation assets.
- **BehaviorCategory / Behavior / Modifier**: reusable coding vocabulary.
- **Subject / SubjectGroup**: who or what is being observed.
- **ObservationTemplate**: reusable structure for new sessions.
- **ObservationSession**: media-backed or live coding container.
- **ObservationEvent**: point, start, or stop event with optional modifiers and subjects.
- **SessionAnnotation**: free-form timestamped note.
- **ObservationAuditLog**: review and coding traceability.
- **ObservationVariableValue**: typed independent variables attached to sessions.

## Execution model

The project is ASGI-first and is intended to run behind Granian:

- Django application entry point: `config.asgi:application`
- HTTP server: Granian
- static and media files served locally in development, reverse-proxied in production

## Data services

### PostgreSQL 18

PostgreSQL is the recommended production database. The settings module enables psycopg 3 connection pooling when PostgreSQL is configured.

### Redis 8

Redis is used as the default cache backend in non-test environments. Tests fall back to `LocMemCache` to keep the test suite hermetic.

### Sessions

Authentication sessions are stored in the database (`django.contrib.sessions.backends.db`) to avoid losing user sessions on cache eviction.

## Security defaults

- Argon2 is the first password hasher.
- Django 6 CSP middleware is enabled.
- CSRF cookies and session cookies are hardened.
- `X-Frame-Options` is set to `DENY`.
- `SECURE_PROXY_SSL_HEADER` is configured for reverse proxy deployments.

## Internationalization

The project enables:

- `LocaleMiddleware`
- Django's complete built-in language list
- `LOCALE_PATHS`
- language switching through Django's built-in `set_language` endpoint

This means the project is ready for broad locale support even if only part of the custom UI is translated today.
