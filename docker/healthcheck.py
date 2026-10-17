"""Minimal container health probe; it never reads application data."""

import json
import sys
from urllib.request import urlopen


try:
    with urlopen("http://127.0.0.1:8000/healthz/", timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if response.status != 200 or payload != {"status": "ok"}:
        raise RuntimeError("health endpoint returned an unexpected status")
except Exception as exc:  # pragma: no cover - executed by Docker, not Django tests
    print(f"healthcheck failed: {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)
