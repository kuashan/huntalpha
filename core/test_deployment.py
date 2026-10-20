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

    def test_debug_runtime_uses_non_manifest_static_storage(self):
        """Local/test admin templates must not require a prebuilt production manifest."""
        environment = os.environ.copy()
        environment.update({
            "DJANGO_SECRET_KEY": "test-secret",
            "DJANGO_DEBUG": "1",
        })
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from django.conf import settings; print(settings.STORAGES['staticfiles']['BACKEND'])",
            ],
            cwd=self.base_dir,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "django.contrib.staticfiles.storage.StaticFilesStorage")

    def test_container_artifacts_have_operational_runtime_contracts(self):
        """The image must run Gunicorn and check Django without migrations."""
        dockerfile = (self.base_dir / "deployment" / "web" / "Dockerfile").read_text(encoding="utf-8")
        healthcheck = (self.base_dir / "docker" / "healthcheck.py").read_text(encoding="utf-8")
        self.assertIn("gunicorn", dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)
        self.assertIn("nodejs", dockerfile)
        self.assertNotIn("migrate", dockerfile.lower())
        self.assertIn("/healthz/", healthcheck)

    def test_arm64_runtime_uses_python_trixie_for_longbridge_5_2(self):
        """The ARM64 runtime must use the distribution that exposes the retained SDK pin."""
        dockerfile = (self.base_dir / "deployment" / "web" / "Dockerfile").read_text(encoding="utf-8")
        requirements = (self.base_dir / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("FROM python:3.11-slim-trixie AS runtime", dockerfile)
        self.assertNotIn("FROM python:3.11-slim-bookworm AS runtime", dockerfile)
        self.assertIn("from longbridge.openapi import Config", dockerfile)
        self.assertIn("longbridge==5.2.0", requirements)


class ReleaseWorkflowContractTests(SimpleTestCase):
    def test_release_workflow_verifier_accepts_only_the_safe_arm64_pipeline(self):
        """A changed workflow must retain its no-deploy release-build boundary."""
        base_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/verify_web_release_workflow.py"],
            cwd=base_dir,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


    def test_release_workflow_verifier_rejects_automatic_triggers(self):
        """The retained Actions fallback must not start on push, PR or schedule."""
        import importlib.util
        from unittest.mock import patch

        base_dir = Path(__file__).resolve().parents[1]
        verifier_path = base_dir / "scripts" / "verify_web_release_workflow.py"
        spec = importlib.util.spec_from_file_location("release_workflow_check", verifier_path)
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        original = verifier.WORKFLOW.read_text(encoding="utf-8")
        for event, additional_trigger in (
            ("push", "  push:\\n"),
            ("pull_request", "  pull_request:\\n"),
            ("schedule", "  schedule:\\n"),
        ):
            with self.subTest(event=event), TemporaryDirectory() as temporary_directory:
                candidate = Path(temporary_directory) / "release.yml"
                candidate.write_text(
                    original.replace(
                        "  workflow_dispatch:\\n",
                        "  workflow_dispatch:\\n" + additional_trigger.replace("\\n", "\n"),
                        1,
                    ),
                    encoding="utf-8",
                )
                with patch.object(verifier, "WORKFLOW", candidate):
                    with self.assertRaisesRegex(ValueError, "manual-only"):
                        verifier.main()


class WebReleaseRunbookContractTests(SimpleTestCase):
    def test_runbook_requires_immutable_provenance_and_explicit_approval(self):
        """Operators must not treat a registry label or tag as deployment authority."""
        base_dir = Path(__file__).resolve().parents[1]
        runbook = (base_dir / "docs" / "operations" / "siftalpha-web-releases.md").read_text(encoding="utf-8")
        required_phrases = (
            "GitHub Actions Run",
            "build manifest",
            "BuildKit OCI provenance",
            "buildkit-oci-slsa",
            "provenance is not GitHub official encrypted signature proof",
            "OCI labels are only a locator",
            "separate user deployment approval",
            "preflight",
            "sqlite3.Connection.backup()",
            "first-adoption",
            "legacy",
            "Compose",
            "different container names",
            "does not run migrations",
            "does not restore the database automatically",
            "rollback only with separate approval",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, runbook)
        self.assertNotIn("latest", runbook.lower())
