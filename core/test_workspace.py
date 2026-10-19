"""Task 005.2: synthetic account-global workspace and entitlement regression."""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from formula_editor.models import Formula
from .models import AccountMembership, ChartWorkspace


class AccountWorkspaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username="workspace@example.com", email="workspace@example.com", password="test-password",
        )
        self.other = User.objects.create_user(
            username="other-workspace@example.com", email="other-workspace@example.com", password="test-password",
        )
        self.private = Formula.objects.create(
            name="Workspace Private", code="WORKSPACE_PRIVATE", source="PRIVATE:MA(C,5);",
            placement="main", enabled=True,
        )
        self.client.force_login(self.member)
        self.url = "/api/account/workspace/"

    def put(self, payload, client=None):
        return (client or self.client).put(
            self.url, data=json.dumps(payload), content_type="application/json",
        )

    def test_new_user_read_does_not_create_record_or_import_browser_state(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"], {"main": [], "sub": [], "heights": {}})
        self.assertFalse(ChartWorkspace.objects.filter(user=self.member).exists())

    def test_round_trip_cross_session_and_global_scope(self):
        payload = {"main": ["MA"], "sub": ["MACD", "RSI"], "heights": {"MACD": 180, "RSI": 120}}
        response = self.put(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"], payload)
        self.client.logout()
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).json()["workspace"], payload)
        # Workspace is independent of symbol, market, time frame and the browser.
        self.assertEqual(ChartWorkspace.objects.filter(user=self.member).count(), 1)

    def test_user_separation_and_anonymous_and_guest_denied(self):
        self.put({"main": ["MA"], "sub": [], "heights": {}})
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).json()["workspace"]["main"], [])
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.put({"main": ["MA"], "sub": [], "heights": {}}).status_code, 403)
        self.client.post("/api/auth/guest/")
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_free_cannot_save_private_or_disabled_codes(self):
        state = {"main": ["MA", self.private.code, "NOT_INSTALLED"],
                 "sub": ["MACD"], "heights": {"MACD": 200, "RSI": 140}}
        response = self.put(state)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"],
                         {"main": ["MA"], "sub": ["MACD"], "heights": {"MACD": 200}})
        self.assertNotIn(self.private.source, response.content.decode())

    def test_pro_downgrade_is_permanent_and_stale_clients_cannot_resurrect(self):
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        original = {"main": [self.private.code, "MA"], "sub": ["RSI"], "heights": {"RSI": 120}}
        self.assertEqual(self.put(original).json()["workspace"], original)
        AccountMembership.objects.filter(user=self.member).update(tier="free")
        # Also covers direct DB tier updates: the first workspace read prunes in storage.
        after = self.client.get(self.url).json()["workspace"]
        self.assertEqual(after, {"main": ["MA"], "sub": ["RSI"], "heights": {"RSI": 120}})
        self.assertEqual(ChartWorkspace.objects.get(user=self.member).state, after)
        self.assertEqual(self.put(original).json()["workspace"], after)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        self.assertEqual(self.client.get(self.url).json()["workspace"], after)

    def test_disabled_private_formula_is_removed_without_modifying_formula(self):
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        self.put({"main": [self.private.code], "sub": [], "heights": {}})
        Formula.objects.filter(pk=self.private.pk).update(enabled=False)
        self.assertEqual(self.client.get(self.url).json()["workspace"]["main"], [])
        self.private.refresh_from_db()
        self.assertEqual(self.private.source, "PRIVATE:MA(C,5);")

    def test_delete_all_and_bad_payload_fail_without_erasing_previous_state(self):
        good = {"main": ["MA"], "sub": ["MACD"], "heights": {"MACD": 180}}
        self.put(good)
        for invalid in [
            {"main": ["MA", "MA"], "sub": [], "heights": {}},
            {"main": ["MA"], "sub": ["MACD"], "heights": {"MACD": True}},
            {"main": [], "sub": ["VOL", "MACD", "RSI", "KDJ"], "heights": {}},
            {"main": ["MA"], "sub": [], "heights": {}, "extra": "bad"},
            {"main": "MA", "sub": [], "heights": {}},
        ]:
            self.assertEqual(self.put(invalid).status_code, 400)
            self.assertEqual(ChartWorkspace.objects.get(user=self.member).state, good)
        empty = {"main": [], "sub": [], "heights": {}}
        self.assertEqual(self.put(empty).json()["workspace"], empty)
        self.assertEqual(self.client.get(self.url).json()["workspace"], empty)

    def test_csrf_required_for_write_not_read(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.member)
        self.assertEqual(strict.get(self.url).status_code, 200)
        self.assertEqual(self.put({"main": ["MA"], "sub": [], "heights": {}}, strict).status_code, 403)
        strict.get("/api/csrf/")
        token = strict.cookies["csrftoken"].value
        response = strict.put(
            self.url, data=json.dumps({"main": ["MA"], "sub": [], "heights": {}}),
            content_type="application/json", HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)


    def test_admin_downgrade_immediately_removes_revoked_codes_without_login(self):
        User = get_user_model()
        admin_user = User.objects.create_superuser(
            username="workspace-admin@example.com", email="workspace-admin@example.com",
            password="admin-password",
        )
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        self.put({"main": [self.private.code, "MA"], "sub": [], "heights": {}})
        self.assertIn(self.private.code, ChartWorkspace.objects.get(user=self.member).state["main"])

        membership = AccountMembership.objects.get(user=self.member)
        self.client.force_login(admin_user)
        response = self.client.post(
            f"/admin/auth/user/{self.member.pk}/change/",
            {
                "username": self.member.username,
                "email": self.member.email,
                "first_name": self.member.first_name,
                "last_name": self.member.last_name,
                "is_active": "on",
                "date_joined_0": self.member.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": self.member.date_joined.strftime("%H:%M:%S"),
                "account_membership-TOTAL_FORMS": "1",
                "account_membership-INITIAL_FORMS": "1",
                "account_membership-MIN_NUM_FORMS": "0",
                "account_membership-MAX_NUM_FORMS": "1",
                "account_membership-0-id": str(membership.pk),
                "account_membership-0-user": str(self.member.pk),
                "account_membership-0-tier": "free",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AccountMembership.objects.get(user=self.member).tier, "free")
        self.assertEqual(
            ChartWorkspace.objects.get(user=self.member).state,
            {"main": ["MA"], "sub": [], "heights": {}},
        )
