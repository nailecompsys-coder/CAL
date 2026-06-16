FROM python:3.11-slim

ARG APP_VERSION=unknown
ARG GIT_COMMIT=unknown
ARG GIT_BRANCH=unknown
ARG GIT_REMOTE=unknown
# IMAGE_VERSION is set at build time from ./scripts/rebuild-cal-api.sh (reads VERSION after bump).
LABEL org.opencontainers.image.title="cal_api" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.source="${GIT_REMOTE}"

ENV CAL_GIT_COMMIT="${GIT_COMMIT}" \
    CAL_GIT_BRANCH="${GIT_BRANCH}" \
    CAL_GIT_REMOTE="${GIT_REMOTE}"

WORKDIR /app

# curl: Docker HEALTHCHECK + Tailwind CLI download; postgresql-client: pg_dump/psql for Wasabi backup/restore
# libpq-dev and gcc are NOT needed — psycopg2-binary ships a pre-compiled wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Download Tailwind CSS standalone CLI (v3, no Node.js required)
RUN curl -sLo /tmp/tailwindcss \
    https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-linux-x64 \
    && chmod +x /tmp/tailwindcss

COPY VERSION ./VERSION
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tailwind.config.js .
COPY app/ ./app/

# Compile Tailwind CSS from all templates — output served as /static/css/tailwind.css
RUN /tmp/tailwindcss -c tailwind.config.js \
      -i app/static/css/input.css \
      -o app/static/css/tailwind.css --minify \
    && rm /tmp/tailwindcss

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

EXPOSE 3005

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:3005/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3005", "--workers", "2"]
