FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=3)); assert data.get('status') == 'ok'"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--blocking-threads", "4", "config.asgi:application"]
