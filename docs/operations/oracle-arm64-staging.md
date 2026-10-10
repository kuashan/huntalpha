# Oracle ARM64 staging runbook

This runbook describes the isolated SiftAlpha staging image prepared by Task
009. It does not change the existing Coolify projects, Cloudflare Tunnel,
WireGuard, Xray service, agent, or production data.

## Image and runtime boundary

- Build from the task branch with the repository `Dockerfile`.
- Use one Gunicorn worker. The realtime registry is process-local and must not
  be duplicated by a multi-worker deployment.
- Mount a dedicated staging data directory at `/data`; never mount the formal
  local database or a production volume.
- Set `HUNTALPHA_DATABASE_PATH=/data/db.sqlite3` and run migrations only on
  that newly created staging database.
- Inject `DJANGO_SECRET_KEY`, `HUNTALPHA_ALLOWED_HOSTS`,
  `HUNTALPHA_CSRF_TRUSTED_ORIGINS`, and `HUNTALPHA_CORS_ALLOWED_ORIGINS`
  through the deployment secret/environment interface.

## Build and health check

```sh
docker build -t siftalpha-task009:<commit> .
docker run --rm --name siftalpha-task009 \
  -p 127.0.0.1:19091:8000 \
  -e DJANGO_SECRET_KEY=<injected-secret> \
  -e DJANGO_DEBUG=0 \
  -e HUNTALPHA_ALLOWED_HOSTS=127.0.0.1,localhost \
  -e HUNTALPHA_DATABASE_PATH=/data/db.sqlite3 \
  -v /srv/siftalpha/task009-data:/data \
  siftalpha-task009:<commit>
```

The container exposes `/healthz/` without authentication and returns only
`{"status":"ok"}`. The frontend build uses `/static/` for its assets and
same-origin API/SSE requests unless `VITE_API_BASE_URL` is explicitly set for
local development.

## HTTPS and rollback boundary

HTTPS termination and public routing must be created as a separate, reviewed
Coolify/Traefik or Cloudflare route. Do not edit the existing tunnel route as
part of this task. Stop and remove only the uniquely named staging container,
and retain its dedicated data directory until the staging result is accepted
or explicitly discarded. A production release must have a separately
versioned image and a reversible route/volume change.

The current Oracle audit found sufficient CPU, memory, disk, Docker and
Coolify capacity for an isolated test, but no approved public hostname or
new tunnel route for SiftAlpha staging. Therefore mobile-browser HTTPS
acceptance remains pending until a safe route is explicitly configured.
