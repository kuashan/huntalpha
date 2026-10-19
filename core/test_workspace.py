"""Task 005.2: workspace isolation, persistence and irreversible entitlement pruning.

No external market providers, private Formula content or production data needed.
"""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import AccountMembership, AccountWorkspace
from formula_editor.models import Formula


class AccountWorkspaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="workspace-owner", password="test-password")
        self.other = User.objects.create_user(username="workspace-other", password="test-password")
        self.client.force_login(self.owner)
        self.private = Formula.objects.create(
            code="XMA", name="Private chart", placement="main",
            source="SECRET_FORMULA_NEVER_LEAVES_SERVER:MA(C,5);", enabled=True,
        )
        self.private_sub = Formula.objects.create(
            code="PRO_SUB", name="Private sub", placement="sub",
            source="SECRET_SUB_FORMULA:MA(C,3);", enabled=True,
        )

    def workspace(self):
        return self.client.get("/api/account/workspace/")

    def save(self, payload):
        return self.client.put(
            "/api/account/workspace/", json.dumps(payload),
            content_type="application/json",
        )

    def test_initial_state_does_not_create_row_or_import_browser_heights(self):
        response = self.workspace()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"], {
            "main": [], "sub": [], "pane_heights": {},
        })
        self.assertFalse(AccountWorkspace.objects.filter(user=self.owner).exists())

    def test_pro_save_restore_global_order_and_sub_heights(self):
        membership = AccountMembership.objects.get(user=self.owner)
        membership.tier = "pro"
        membership.save(update_fields=["tier"])
        response = self.save({
            "main": ["XMA", "MA", "CHANLUN"], "sub": ["RSI", "MACD"],
            "pane_heights": {"RSI": 120, "MACD": 180},
        })
        self.assertEqual(response.status_code, 200)
        expected = response.json()["workspace"]
        self.assertEqual(expected["main"], ["XMA", "MA", "CHANLUN"])
        self.assertEqual(expected["sub"], ["RSI", "MACD"])
        self.assertEqual(expected["pane_heights"], {"RSI": 120, "MACD": 180})
        self.assertEqual(self.workspace().json()["workspace"], expected)
        self.assertEqual(AccountWorkspace.objects.filter(user=self.owner).count(), 1)
        self.assertNotIn("SECRET_FORMULA", json.dumps(response.json()))

    def test_two_accounts_are_strictly_isolated(self):
        self.assertEqual(self.save({
            "main": ["MA"], "sub": ["MACD"], "pane_heights": {"MACD": 164},
        }).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.workspace().json()["workspace"]["main"], [])
        self.save({"main": ["BOLL"], "sub": [], "pane_heights": {}})
        self.assertEqual(AccountWorkspace.objects.get(user=self.owner).main_indicators, ["MA"])
        self.client.force_login(self.owner)
        self.assertEqual(self.workspace().json()["workspace"]["main"], ["MA"])

    def test_admin_downgrade_deletes_pro_codes_permanently(self):
        membership = AccountMembership.objects.get(user=self.owner)
        membership.tier = "pro"
        membership.save(update_fields=["tier"])
        self.save({
            "main": ["XMA", "MA"], "sub": ["PRO_SUB", "RSI"],
            "pane_heights": {"PRO_SUB": 200, "RSI": 110},
        })
        membership.tier = "free"
        membership.save(update_fields=["tier"])
        row = AccountWorkspace.objects.get(user=self.owner)
        self.assertEqual(row.main_indicators, ["MA"])
        self.assertEqual(row.sub_indicators, ["RSI"])
        self.assertEqual(row.sub_pane_heights, {"RSI": 110})
        membership.tier = "pro"
        membership.save(update_fields=["tier"])
        self.assertEqual(self.workspace().json()["workspace"]["main"], ["MA"])
        self.assertEqual(self.workspace().json()["workspace"]["sub"], ["RSI"])

    def test_query_update_tier_change_prunes_on_next_workspace_read(self):
        AccountMembership.objects.filter(user=self.owner).update(tier="pro")
        self.save({"main": ["XMA", "MA"], "sub": [], "pane_heights": {}})
        AccountMembership.objects.filter(user=self.owner).update(tier="free")
        self.assertEqual(self.workspace().json()["workspace"]["main"], ["MA"])
        AccountMembership.objects.filter(user=self.owner).update(tier="pro")
        self.assertEqual(self.workspace().json()["workspace"]["main"], ["MA"])

    def test_free_post_cannot_resurrect_pro_or_unknown_indicators(self):
        response = self.save({
            "main": ["XMA", "MA", "NOT_REGISTERED"], "sub": ["PRO_SUB", "MACD"],
            "pane_heights": {"MACD": 150, "PRO_SUB": 300},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"], {
            "main": ["MA"], "sub": ["MACD"], "pane_heights": {"MACD": 150},
        })

    def test_disabled_formula_pruned_after_read(self):
        AccountMembership.objects.filter(user=self.owner).update(tier="pro")
        self.save({"main": ["XMA", "MA"], "sub": [], "pane_heights": {}})
        Formula.objects.filter(code="XMA").update(enabled=False)
        self.assertEqual(self.workspace().json()["workspace"]["main"], ["MA"])
        self.assertEqual(AccountWorkspace.objects.get(user=self.owner).main_indicators, ["MA"])

    def test_bad_payload_preserves_existing_valid_record(self):
        original = {"main": ["MA"], "sub": ["RSI"], "pane_heights": {"RSI": 140}}
        self.assertEqual(self.save(original).status_code, 200)
        invalid = [
            {"main": ["MA"], "sub": ["RSI"], "pane_heights": {"RSI": 8000}},
            {"main": "MA", "sub": [], "pane_heights": {}},
            {"main": ["MA"], "sub": ["MACD"], "pane_heights": {}, "extra": 3},
            {"main": [], "sub": [], "pane_heights": {"X": True}},
            [],
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.save(payload).status_code, 400)
                self.assertEqual(self.workspace().json()["workspace"], original)

    def test_subchart_limit_and_placement_validation(self):
        result = self.save({
            "main": ["RSI", "MA", "BOLL"],
            "sub": ["VOL", "MACD", "KDJ", "RSI", "PRO_SUB"],
            "pane_heights": {"VOL": 101, "MACD": 102, "KDJ": 103, "RSI": 104},
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["workspace"]["main"], ["MA", "BOLL"])
        self.assertEqual(result.json()["workspace"]["sub"], ["VOL", "MACD", "KDJ"])
        self.assertEqual(result.json()["workspace"]["pane_heights"], {
            "VOL": 101, "MACD": 102, "KDJ": 103,
        })

    def test_clear_all_is_durable(self):
        self.save({"main": ["MA"], "sub": ["MACD"], "pane_heights": {"MACD": 140}})
        self.save({"main": [], "sub": [], "pane_heights": {}})
        self.assertEqual(self.workspace().json()["workspace"], {
            "main": [], "sub": [], "pane_heights": {},
        })

    def test_guest_and_anonymous_cannot_access_workspace(self):
        guest = Client()
        self.assertEqual(guest.get("/api/account/workspace/").status_code, 403)
        self.assertEqual(guest.put(
            "/api/account/workspace/", data="{}", content_type="application/json",
        ).status_code, 403)
        self.assertEqual(guest.post("/api/auth/guest/").status_code, 200)
        self.assertEqual(guest.get("/api/account/workspace/").status_code, 403)

    def test_csrf_required_for_workspace_writes(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        response = csrf.put(
            "/api/account/workspace/",
            json.dumps({"main": ["MA"], "sub": [], "pane_heights": {}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AccountWorkspace.objects.filter(user=self.owner).exists())
