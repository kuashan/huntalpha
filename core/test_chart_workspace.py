"""Task 005.2 isolated tests: no real accounts, data feeds or formula sources."""
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from formula_editor.models import Formula
from .models import AccountMembership, ChartWorkspace

URL = "/api/account/chart-workspace/"


class ChartWorkspaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="workspace-owner", password="safe-password-123")
        self.other = User.objects.create_user(username="workspace-other", password="safe-password-123")
        self.client.force_login(self.owner)
        self.formula = Formula.objects.create(
            code="WS_PRIVATE", name="Synthetic protected formula",
            placement="main", source="OUT:MA(C,5);", enabled=True,
        )

    def put(self, main=None, sub=None, heights=None, client=None):
        state = {"main": main if main is not None else [],
                 "sub": sub if sub is not None else [],
                 "pane_heights": heights if heights is not None else {}}
        return (client or self.client).put(URL, data=json.dumps(state), content_type="application/json")

    def upgrade(self):
        AccountMembership.objects.filter(user=self.owner).update(tier="pro")

    def test_empty_first_login_does_not_create_account_record_or_copy_browser_data(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"main": [], "sub": [], "pane_heights": {}})
        self.assertFalse(ChartWorkspace.objects.exists())

    def test_save_restore_account_global_order_and_pane_heights(self):
        self.upgrade()
        self.assertEqual(self.put(["MA", "WS_PRIVATE"], ["MACD", "RSI"],
                                  {"MACD": 180, "RSI": 120}).status_code, 200)
        another_device = Client()
        another_device.force_login(self.owner)
        self.assertEqual(another_device.get(URL).json(), {
            "main": ["MA", "WS_PRIVATE"], "sub": ["MACD", "RSI"],
            "pane_heights": {"MACD": 180, "RSI": 120},
        })
        self.assertEqual(ChartWorkspace.objects.count(), 1)
        self.assertNotIn("source", another_device.get(URL).content.decode("utf-8"))
        self.assertEqual(self.put().status_code, 200)  # explicit removal persists
        self.assertEqual(another_device.get(URL).json()["main"], [])
        self.assertEqual(another_device.get(URL).json()["sub"], [])

    def test_two_accounts_are_isolated_even_with_same_machine(self):
        self.assertEqual(self.put(["MA"], ["MACD"], {"MACD": 200}).status_code, 200)
        other_device = Client()
        other_device.force_login(self.other)
        self.assertEqual(other_device.get(URL).json()["main"], [])
        self.assertEqual(self.put(sub=["RSI"], heights={"RSI": 125}, client=other_device).status_code, 200)
        self.assertEqual(self.client.get(URL).json()["main"], ["MA"])
        self.assertEqual(ChartWorkspace.objects.count(), 2)

    def test_no_account_and_guest_cannot_persist(self):
        anon = Client()
        self.assertEqual(anon.get(URL).status_code, 403)
        self.assertEqual(self.put(main=["MA"], client=anon).status_code, 403)
        self.assertFalse(ChartWorkspace.objects.exists())

    def test_server_rejects_pro_codes_as_free_and_stale_device_writes(self):
        self.assertEqual(self.put(main=["WS_PRIVATE"]).status_code, 403)
        self.assertFalse(ChartWorkspace.objects.exists())
        self.upgrade()
        self.assertEqual(self.put(main=["WS_PRIVATE"]).status_code, 200)
        AccountMembership.objects.filter(user=self.owner).update(tier="free")  # bypasses model signal
        self.assertEqual(self.put(main=["WS_PRIVATE"]).status_code, 403)
        self.assertEqual(self.client.get(URL).json()["main"], [])
        self.assertEqual(ChartWorkspace.objects.get(user=self.owner).main, [])
        self.upgrade()
        self.assertEqual(self.client.get(URL).json()["main"], [])  # no resurrection

    def test_admin_membership_save_eagerly_prunes_revoked_main(self):
        self.upgrade()
        self.assertEqual(self.put(main=["MA", "WS_PRIVATE"], sub=["MACD"],
                                  heights={"MACD": 170}).status_code, 200)
        membership = AccountMembership.objects.get(user=self.owner)
        membership.tier = "free"
        membership.save()
        saved = ChartWorkspace.objects.get(user=self.owner)
        self.assertEqual(saved.main, ["MA"])
        self.assertEqual(saved.sub, ["MACD"])
        self.assertEqual(saved.pane_heights, {"MACD": 170})

    def test_fixed_or_private_formula_disabled_prunes_durable_config(self):
        self.upgrade()
        self.assertEqual(self.put(main=["WS_PRIVATE"]).status_code, 200)
        self.formula.enabled = False
        self.formula.save(update_fields=["enabled"])
        self.assertEqual(self.client.get(URL).json()["main"], [])
        self.assertEqual(ChartWorkspace.objects.get(user=self.owner).main, [])

    def test_reject_malformed_input_without_overwriting_previous_record(self):
        self.assertEqual(self.put(main=["MA"], sub=["MACD"], heights={"MACD": 150}).status_code, 200)
        for broken in [
            {"main": ["MA", "MA"], "sub": [], "pane_heights": {}},
            {"main": ["MACD"], "sub": [], "pane_heights": {}},
            {"main": [], "sub": ["MACD", "RSI", "VOL", "KDJ"], "pane_heights": {}},
            {"main": [], "sub": ["MACD"], "pane_heights": {"MACD": True}},
            {"main": [], "sub": ["MACD"], "pane_heights": {"RSI": 170}},
            {"main": [], "sub": ["MA"], "pane_heights": {}},
            {"main": [], "sub": [], "pane_heights": {}, "source": "not-allowed"},
        ]:
            reply = self.client.put(URL, data=json.dumps(broken), content_type="application/json")
            self.assertEqual(reply.status_code, 400, broken)
        self.assertEqual(self.client.get(URL).json(), {
            "main": ["MA"], "sub": ["MACD"], "pane_heights": {"MACD": 150},
        })

    def test_csrf_is_required_for_workspace_writes(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(self.put(main=["MA"], client=csrf_client).status_code, 403)
        csrf_client.get("/api/csrf/")
        token = csrf_client.cookies["csrftoken"].value
        reply = csrf_client.put(URL, data=json.dumps({"main": ["MA"], "sub": [], "pane_heights": {}}),
                                content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(reply.status_code, 200)
