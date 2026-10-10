from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class DeploymentContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base_dir = Path(settings.BASE_DIR)
        cls.frontend_dir = cls.base_dir / "frontend" / "src"
        cls.api_source = (cls.frontend_dir / "api.js").read_text(encoding="utf-8") if (cls.frontend_dir / "api.js").exists() else ""
        cls.vite_source = (cls.base_dir / "frontend" / "vite.config.js").read_text(encoding="utf-8")
        cls.settings_source = (cls.base_dir / "quant_site" / "settings.py").read_text(encoding="utf-8")

    def test_frontend_runtime_api_base_is_environment_aware(self):
        self.assertIn("VITE_API_BASE_URL", self.api_source)
        self.assertIn("import.meta.env.DEV", self.api_source)
        vue_sources = list(self.frontend_dir.rglob("*.vue"))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in vue_sources)
        self.assertNotIn("http://127.0.0.1:8003", combined)

    def test_vite_production_assets_use_django_static_prefix(self):
        self.assertIn("VITE_APP_BASE_URL", self.vite_source)
        self.assertIn("/static/", self.vite_source)

    def test_django_production_settings_are_environment_driven(self):
        for name in (
            "DJANGO_DEBUG",
            "HUNTALPHA_ALLOWED_HOSTS",
            "HUNTALPHA_CSRF_TRUSTED_ORIGINS",
            "HUNTALPHA_DATABASE_PATH",
            "HUNTALPHA_STATIC_ROOT",
            "HUNTALPHA_SESSION_COOKIE_SECURE",
        ):
            self.assertIn(name, self.settings_source)

    def test_health_endpoint_is_public_and_minimal(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_container_entrypoints_are_present(self):
        dockerfile = (self.base_dir / "Dockerfile").read_text(encoding="utf-8") if (self.base_dir / "Dockerfile").exists() else ""
        healthcheck = (self.base_dir / "docker" / "healthcheck.py").read_text(encoding="utf-8") if (self.base_dir / "docker" / "healthcheck.py").exists() else ""
        self.assertIn("gunicorn", dockerfile)
        self.assertIn("healthcheck.py", dockerfile)
        self.assertIn("/healthz/", healthcheck)

    def test_formula_runtime_includes_node(self):
        dockerfile = (self.base_dir / "Dockerfile").read_text(encoding="utf-8") if (self.base_dir / "Dockerfile").exists() else ""
        self.assertIn("nodejs", dockerfile)
        self.assertIn("RUN node --version", dockerfile)
