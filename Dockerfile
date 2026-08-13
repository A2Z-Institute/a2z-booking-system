FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    A2Z_DATABASE=/data/a2z_booking.db \
    A2Z_SECURE_COOKIES=1 \
    A2Z_DEBUG=0

WORKDIR /app

RUN groupadd --system --gid 10001 a2z \
    && useradd --system --uid 10001 --gid a2z --home-dir /app a2z

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=a2z:a2z . .

RUN mkdir -p /data && chown a2z:a2z /data

USER a2z

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=4).read()"]

CMD ["sh", "-c", "test -n \"$A2Z_SECRET_KEY\" || { echo 'A2Z_SECRET_KEY is required'; exit 1; }; test -n \"$A2Z_ADMIN_PASSWORD\" || { echo 'A2Z_ADMIN_PASSWORD is required'; exit 1; }; exec waitress-serve --host=0.0.0.0 --port=${PORT:-8000} wsgi:app"]
