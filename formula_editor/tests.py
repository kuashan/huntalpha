"""Task 012 regressions: registry-only fixed formulas and server-side tier gate."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import AccountMembership
from core.python_indicators import get_python_indicator
from core.views import formula_run_registry
from .fixed_indicators import is_fixed_indicator_enabled
from .models import FixedIndicatorState, Formula


class FixedFormulaAndEntitlementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.free = User.objects.create_user(username="formula-free", password="Pass123-synthetic")
        self.pro = User.objects.create_user(username="formula-pro", password="Pass123-synthetic")
        self.staff = User.objects.create_user(username="formula-staff", password="Pass123-synthetic", is_staff=True)
        self.admin = User.objects.create_superuser(username="formula-admin", email="admin@example.test", password="Pass123-synthetic")
        AccountMembership.objects.filter(user=self.pro).update(tier="pro")
        self.private = Formula.objects.create(
            code="SYNTHETIC_PRIVATE", name="Synthetic private indicator",
            placement="main", source="PRIVATE_SOURCE_MUST_NEVER_LEAK:MA(C,5);",
        )
        self.client = Client()
        formula_run_registry.clear()

    def catalog(self, user=None):
        self.client.logout()
        if user:
            self.client.force_login(user)
        else:
            self.client.post("/api/auth/guest/")
        response = self.client.get("/api/indicators/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotIn("PRIVATE_SOURCE_MUST_NEVER_LEAK", response.content.decode())
        return {item["code"]: item for item in response.json()["items"]}

    def test_visitor_only_six_common_not_chanlun(self):
        catalog = self.catalog()
        self.assertEqual(set(catalog), {"MA", "MACD", "BOLL", "VOL", "KDJ", "RSI"})
        self.assertEqual(self.client.get("/api/indicator-render/CHANLUN/SH.TEST/").status_code, 403)

    def test_free_can_use_chanlun_but_private_is_locked_in_list_and_render(self):
        catalog = self.catalog(self.free)
        self.assertTrue(catalog["CHANLUN"]["allowed"])
        self.assertFalse(catalog["SYNTHETIC_PRIVATE"]["allowed"])
        with mock.patch("core.views.history_bars") as history:
            result = self.client.get("/api/indicator-render/SYNTHETIC_PRIVATE/SH.TEST/")
            self.assertEqual(result.status_code, 403)
            self.assertEqual(result.json()["code"], "indicator_not_allowed")
            history.assert_not_called()
        self.assertNotIn("PRIVATE_SOURCE_MUST_NEVER_LEAK", result.content.decode())

    def test_pro_can_render_private_and_downgrade_blocks_cached_execution(self):
        catalog = self.catalog(self.pro)
        self.assertTrue(catalog["SYNTHETIC_PRIVATE"]["allowed"])
        bars = [{"time": 1700000000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}]
        output = SimpleNamespace(stdout=json.dumps({
            "lines": [], "sticks": [], "markers": [], "fixedTexts": [], "engine": "tongdaxin",
        }))
        with mock.patch("core.views.history_bars", return_value=(bars, None, None)), \
             mock.patch("core.views.subprocess.run", return_value=output):
            response = self.client.get("/api/indicator-render/SYNTHETIC_PRIVATE/SH.TEST/?period=日线")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertNotIn("PRIVATE_SOURCE_MUST_NEVER_LEAK", response.content.decode())
        self.assertIn("no-store", response.headers["Cache-Control"])
        AccountMembership.objects.filter(user=self.pro).update(tier="free")
        with mock.patch("core.views.history_bars") as history:
            denied = self.client.get("/api/indicator-render/SYNTHETIC_PRIVATE/SH.TEST/")
        self.assertEqual(denied.status_code, 403)
        history.assert_not_called()
        self.assertFalse(self.catalog(self.pro)["SYNTHETIC_PRIVATE"]["allowed"])

    def test_server_fixed_switch_auto_catalog_and_original_formulas_unchanged(self):
        for number in range(3):
            Formula.objects.create(
                code=f"SECONDARY_{number}", name="Synthetic",
                placement="sub", source="SYNTHETIC_ONLY:MA(C,3);",
            )
        before = list(Formula.objects.order_by("pk").values_list("pk", "code", "source"))
        self.assertTrue(is_fixed_indicator_enabled(get_python_indicator("CHANLUN")))
        self.client.force_login(self.admin)
        changelist = reverse("admin:formula_editor_fixedindicatorstate_changelist")
        toggle = reverse("admin:formula_editor_fixedindicatorstate_toggle", args=["CHANLUN"])
        response = self.client.get(changelist)
        self.assertContains(response, "CHANLUN")
        self.assertContains(response, "缠论结构")
        self.assertContains(response, "主图")
        self.assertEqual(self.client.get(toggle).status_code, 405)
        self.assertEqual(self.client.post(toggle).status_code, 302)
        self.assertFalse(is_fixed_indicator_enabled(get_python_indicator("CHANLUN")))
        self.assertNotIn("CHANLUN", self.catalog(self.free))
        self.assertEqual(self.client.get("/api/indicator-render/CHANLUN/SH.TEST/").status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(toggle).status_code, 302)
        self.assertTrue(is_fixed_indicator_enabled(get_python_indicator("CHANLUN")))
        self.assertIn("CHANLUN", self.catalog(self.free))
        self.assertEqual(before, list(Formula.objects.order_by("pk").values_list("pk", "code", "source")))

    def test_unregistered_database_row_never_becomes_executable(self):
        FixedIndicatorState.objects.create(code="UNREGISTERED_CODE", enabled=True)
        self.assertNotIn("UNREGISTERED_CODE", self.catalog(self.pro))
        with mock.patch("core.views.history_bars") as history:
            response = self.client.get("/api/indicator-render/UNREGISTERED_CODE/SH.TEST/")
        self.assertEqual(response.status_code, 404)
        history.assert_not_called()
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse("admin:formula_editor_fixedindicatorstate_toggle", args=["UNREGISTERED_CODE"])
            ).status_code,
            404,
        )

    def test_new_trusted_registry_entry_automatically_shows_but_defaults_off(self):
        definition = replace(
            get_python_indicator("CHANLUN"),
            code="REGISTERED_TEST", identifier="builtin-registered-test",
            name="Synthetic reviewed fixed",
        )
        with mock.patch.dict("core.python_indicators._PYTHON_INDICATORS", {"REGISTERED_TEST": definition}):
            self.client.force_login(self.admin)
            catalog_url = reverse("admin:formula_editor_fixedindicatorstate_changelist")
            toggle = reverse("admin:formula_editor_fixedindicatorstate_toggle", args=["REGISTERED_TEST"])
            self.assertContains(self.client.get(catalog_url), "REGISTERED_TEST")
            self.assertFalse(is_fixed_indicator_enabled(definition))
            self.assertNotIn("REGISTERED_TEST", self.catalog(self.pro))
            self.client.force_login(self.admin)
            self.assertEqual(self.client.post(toggle).status_code, 302)
            self.assertTrue(is_fixed_indicator_enabled(definition))
            self.assertFalse(self.catalog(self.free)["REGISTERED_TEST"]["allowed"])
            self.assertTrue(self.catalog(self.pro)["REGISTERED_TEST"]["allowed"])
            self.assertEqual(self.client.get("/api/indicator-render/REGISTERED_TEST/SH.TEST/").status_code, 403)

    def test_staff_cannot_toggle_fixed_indicator_without_model_permission(self):
        self.client.force_login(self.staff)
        url = reverse("admin:formula_editor_fixedindicatorstate_toggle", args=["CHANLUN"])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(is_fixed_indicator_enabled(get_python_indicator("CHANLUN")))

    def test_mid_calculation_downgrade_cannot_return_a_successful_private_drawing(self):
        self.client.force_login(self.pro)
        bars = [{"time": 1700000000, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}]
        output = SimpleNamespace(stdout=json.dumps({
            "lines": [], "sticks": [], "markers": [], "fixedTexts": [], "engine": "tongdaxin",
        }))
        def downgrade(*args, **kwargs):
            AccountMembership.objects.filter(user=self.pro).update(tier="free")
            return output
        with mock.patch("core.views.history_bars", return_value=(bars, None, None)), \
             mock.patch("core.views.subprocess.run", side_effect=downgrade):
            response = self.client.get("/api/indicator-render/SYNTHETIC_PRIVATE/SH.TEST/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "indicator_not_allowed")
