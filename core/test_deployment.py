"""Regression contracts for the reproducible, non-business web runtime."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class FrontendEntrypointContractTests(SimpleTestCase):
    """The deployed Django process must serve every Vue history entry itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.temp_dir = TemporaryDirectory()
        cls.dist_dir = Path(cls.temp_dir.name) / "dist"
        assets_dir = cls.dist_dir / "assets"
        assets_dir.mkdir(parents=True)
        (cls.dist_dir / "index.html").write_text(
            '<!doctype html><script type="module" src="/static/assets/app.js"></script>',
            encoding="utf-8",
        )
        (assets_dir / "app.js").write_text("window.siftAlphaRuntime = true;", encoding="utf-8")
        cls.static_root = Path(cls.temp_dir.name) / "staticfiles"
        cls.settings_override = override_settings(
            ALLOWED_HOSTS=["testserver"],
            FRONTEND_DIST_DIR=cls.dist_dir,
            STATICFILES_DIRS=[cls.dist_dir],
            STATIC_ROOT=cls.static_root,
        )
        cls.settings_override.enable()
        call_command("collectstatic", interactive=False, verbosity=0)

    @classmethod
    def tearDownClass(cls):
        cls.settings_override.disable()
        cls.temp_dir.cleanup()
        super().tearDownClass()

    @staticmethod
    def response_body(response):
        return b"".join(response.streaming_content) if response.streaming else response.content

    def test_root_and_account_history_entries_serve_the_same_built_shell(self):
        """Removing any SPA route would otherwise break a direct browser visit."""
        for path in ("/", "/account", "/account/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "text/html")
                self.assertIn(b"/static/assets/app.js", self.response_body(response))

    def test_built_static_asset_is_served_from_the_static_prefix(self):
        """The production shell must not rely on a Vite development server."""
        response = self.client.get("/static/assets/app.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"siftAlphaRuntime", self.response_body(response))


class ProductionRuntimeContractTests(SimpleTestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parents[1]

    def test_debug_off_requires_explicit_allowed_hosts(self):
        """A production import must reject an empty host allow-list."""
        environment = os.environ.copy()
        environment.update({
            "DJANGO_SECRET_KEY": "test-secret",
            "DJANGO_DEBUG": "0",
        })
        environment.pop("HUNTALPHA_ALLOWED_HOSTS", None)
        result = subprocess.run(
            [sys.executable, "-c", "import quant_site.settings"],
            cwd=self.base_dir,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HUNTALPHA_ALLOWED_HOSTS", result.stderr)

    def test_container_artifacts_have_operational_runtime_contracts(self):
        """The image must run Gunicorn and check Django without migrations."""
        dockerfile = (self.base_dir / "deployment" / "web" / "Dockerfile").read_text(encoding="utf-8")
        healthcheck = (self.base_dir / "docker" / "healthcheck.py").read_text(encoding="utf-8")
        self.assertIn("gunicorn", dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)
        self.assertIn("nodejs", dockerfile)
        self.assertNotIn("migrate", dockerfile.lower())
        self.assertIn("/healthz/", healthcheck)
