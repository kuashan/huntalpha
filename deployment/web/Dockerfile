# Reproducible ARM64-compatible runtime for the accepted SiftAlpha web tree.
FROM node:22-bookworm-slim AS frontend-build
WORKDIR /src/frontend
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global url."https://github.com/".insteadOf "git+ssh://git@github.com/" \
    && git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global url."https://github.com/".insteadOf "git@github.com:"
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_APP_BASE_URL=/static/
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libjpeg62-turbo-dev zlib1g-dev ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./
COPY --from=frontend-build /src/frontend/dist ./frontend/dist
RUN DJANGO_SECRET_KEY=build-only-secret \
    DJANGO_DEBUG=0 \
    HUNTALPHA_ALLOWED_HOSTS=127.0.0.1,localhost \
    python manage.py collectstatic --noinput
RUN node --version
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "docker/healthcheck.py"]
CMD ["gunicorn", "quant_site.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
