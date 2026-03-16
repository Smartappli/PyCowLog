"""Project settings for PyBehaviorLog.

The configuration is intentionally environment-driven so the same codebase can
run in a lightweight local setup (SQLite) or in the recommended container stack
(PostgreSQL 18 + Redis 8 + Granian on ASGI).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.conf import global_settings
from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str | None:
    """Return a raw environment variable value."""
    return os.getenv(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable using common truthy markers."""
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name: str, default: int) -> int:
    """Parse an integer environment variable with a safe default."""
    value = env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_list(name: str, default: str = '') -> list[str]:
    """Parse a comma-separated environment variable into a cleaned list."""
    raw = env(name, default) or ''
    return [item.strip() for item in raw.split(',') if item.strip()]


def build_database_config() -> dict[str, object]:
    """Build a SQLite or PostgreSQL database configuration.

    SQLite remains the zero-config fallback for local work and unit tests.
    PostgreSQL is enabled automatically when DATABASE_URL or PostgreSQL-style
    environment variables are provided.
    """
    if 'test' in sys.argv and not env_bool('PYBEHAVIORLOG_FORCE_EXTERNAL_DB', False):
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }

    database_url = env('DATABASE_URL')
    db_name = env('POSTGRES_DB') or env('DB_NAME')
    if not database_url and not db_name:
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }

    if database_url:
        parsed = urlparse(database_url)
        name = parsed.path.lstrip('/')
        host = parsed.hostname or 'db'
        port = parsed.port or 5432
        user = parsed.username or 'pybehaviorlog'
        password = parsed.password or 'pybehaviorlog'
    else:
        name = db_name or 'pybehaviorlog'
        host = env('POSTGRES_HOST', env('DB_HOST', 'db')) or 'db'
        port = env_int('POSTGRES_PORT', env_int('DB_PORT', 5432))
        user = env('POSTGRES_USER', env('DB_USER', 'pybehaviorlog')) or 'pybehaviorlog'
        password = env('POSTGRES_PASSWORD', env('DB_PASSWORD', 'pybehaviorlog')) or 'pybehaviorlog'

    pool_config: bool | dict[str, int] = {
        'min_size': env_int('POSTGRES_POOL_MIN_SIZE', 2),
        'max_size': env_int('POSTGRES_POOL_MAX_SIZE', 12),
        'timeout': env_int('POSTGRES_POOL_TIMEOUT', 30),
    }
    if env_bool('POSTGRES_POOL_DEFAULTS', False):
        pool_config = True

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': name,
        'USER': user,
        'PASSWORD': password,
        'HOST': host,
        'PORT': port,
        'CONN_MAX_AGE': env_int('DB_CONN_MAX_AGE', 60),
        'OPTIONS': {'pool': pool_config},
    }


SECRET_KEY = env('DJANGO_SECRET_KEY', 'django-insecure-pybehaviorlog-v7-change-me')
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tracker',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.csp.ContentSecurityPolicyMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.template.context_processors.csrf',
                'django.template.context_processors.i18n',
                'django.template.context_processors.static',
                'django.template.context_processors.media',
                'django.template.context_processors.csp',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {'default': build_database_config()}

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Django ships a maintained list of translated locales. Reusing that list keeps
# the language selector aligned with the framework version installed.
LANGUAGE_CODE = env('DJANGO_LANGUAGE_CODE', 'en')
LANGUAGES = global_settings.LANGUAGES
TIME_ZONE = env('DJANGO_TIME_ZONE', 'Europe/Brussels')
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / 'locale']

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'tracker:home'
LOGOUT_REDIRECT_URL = 'login'

SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = env_int('SESSION_COOKIE_AGE', 60 * 60 * 24 * 14)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', not DEBUG)

if 'test' in sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'pybehaviorlog-tests',
        }
    }
else:
    redis_url = env('REDIS_URL', 'redis://redis:6379/1') or 'redis://redis:6379/1'
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': redis_url,
            'TIMEOUT': env_int('CACHE_TIMEOUT', 300),
            'KEY_PREFIX': env('CACHE_KEY_PREFIX', 'pybehaviorlog'),
        }
    }

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

SECURE_CSP = {
    'default-src': [CSP.SELF],
    'base-uri': [CSP.SELF],
    'connect-src': [CSP.SELF],
    'font-src': [CSP.SELF, 'data:'],
    'form-action': [CSP.SELF],
    'frame-ancestors': [CSP.NONE],
    'img-src': [CSP.SELF, 'data:', 'blob:'],
    'media-src': [CSP.SELF, 'blob:'],
    'object-src': [CSP.NONE],
    'script-src': [CSP.SELF, CSP.NONCE, CSP.UNSAFE_INLINE],
    'style-src': [CSP.SELF, CSP.NONCE, CSP.UNSAFE_INLINE],
}
