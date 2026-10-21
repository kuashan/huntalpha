# Reproducible ARM64-compatible runtime for the accepted SiftAlpha web tree.
FROM node:22-bookworm-slim AS frontend-apt-https-check
# CA must already be present in the official base image, before APT switches to HTTPS.
# Fail closed if certificates or Debian APT source configuration are missing.
RUN set -eu; \
    test -s /etc/ssl/certs/ca-certificates.crt; \
    dpkg-query -W -f='${Status}\n' ca-certificates | grep -qx 'install ok installed'; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sources=/etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sources=/etc/apt/sources.list; \
    else \
        echo "Debian APT sources not found" >&2; exit 1; \
    fi; \
    grep -Eq 'http://(deb|security)\.debian\.org' "$sources"; \
    sed -i \
        -e 's|http://deb.debian.org|https://deb.debian.org|g' \
        -e 's|http://security.debian.org|https://security.debian.org|g' \
        "$sources"; \
    ! grep -Eq 'http://(deb|security)\.debian\.org' "$sources"; \
    apt-get update -o APT::Update::Error-Mode=any

FROM frontend-apt-https-check AS frontend-build
WORKDIR /src/frontend
RUN apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global url."https://github.com/".insteadOf "git+ssh://git@github.com/" \
    && git config --global url."https://github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global url."https://github.com/".insteadOf "git@github.com:"
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_APP_BASE_URL=/static/
RUN npm run build

FROM python:3.11-slim-trixie AS runtime-apt-https-check
# CA must already be present in the official base image, before APT switches to HTTPS.
# Fail closed if certificates or Debian APT source configuration are missing.
RUN set -eu; \
    test -s /etc/ssl/certs/ca-certificates.crt; \
    dpkg-query -W -f='${Status}\n' ca-certificates | grep -qx 'install ok installed'; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sources=/etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sources=/etc/apt/sources.list; \
    else \
        echo "Debian APT sources not found" >&2; exit 1; \
    fi; \
    grep -Eq 'http://(deb|security)\.debian\.org' "$sources"; \
    sed -i \
        -e 's|http://deb.debian.org|https://deb.debian.org|g' \
        -e 's|http://security.debian.org|https://security.debian.org|g' \
        "$sources"; \
    ! grep -Eq 'http://(deb|security)\.debian\.org' "$sources"; \
    apt-get update -o APT::Update::Error-Mode=any

FROM runtime-apt-https-check AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get install -y --no-install-recommends build-essential libjpeg62-turbo-dev zlib1g-dev ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from longbridge.openapi import Config; print('longbridge: import ok')"
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
