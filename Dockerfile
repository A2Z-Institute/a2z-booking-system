FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    A2Z_HOST=0.0.0.0 \
    A2Z_DATABASE=/data/a2z_booking.db

WORKDIR /app

RUN addgroup --system a2z && adduser --system --ingroup a2z a2z \
    && mkdir -p /data \
    && chown -R a2z:a2z /app /data

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=a2z:a2z . .

USER a2z

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--threads=4", "wsgi:app"]
