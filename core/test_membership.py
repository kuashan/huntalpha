"""Task 011: persisted membership and reversible global watchlist freezing."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from django.utils import timezone
from unittest.mock import patch
from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase

from .admin import AccountMembershipForm, AccountMembershipInline, MembershipUserAdmin
from .models import AccountMembership, MarketSymbol, WatchlistEntry
from .membership import DURATION_CHOICES, period_end, grant_pro_period
from .watchlist import resolve_account_tier, resolve_watchlist_limit


class MembershipAndFrozenWatchlistTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(username="member-tier", password="safe-password-123")
        self.staff = User.objects.create_user(username="staff-tier", password="safe-password-123", is_staff=True)
        self.superuser = User.objects.create_superuser(username="admin-tier", password="safe-password-123", email="admin@example.com")
        self.client = Client()
        self.client.force_login(self.member)
        self.symbols = []
        for i in range(23):
            market = ("cn", "hk", "us", "crypto")[i % 4]
            code = f"SH.601{i:03d}" if market == "cn" else f"HK.00{i:03d}" if market == "hk" else f"US.MEM{i:03d}" if market == "us" else f"CC.MEM{i:03d}-USD"
            self.symbols.append(MarketSymbol.objects.create(
                code=code, name=f"Test membership {i:03d}", market=market,
                security_type="CRYPTO_SPOT" if market == "crypto" else "STOCK",
                exchange=market.upper(), provider="test-provider", provider_symbol=code,
                active=True,
            ))

    def add_rows(self, count):
        return [WatchlistEntry.objects.create(user=self.member, symbol=s) for s in self.symbols[:count]]

    def post_code(self, code):
        return self.client.post("/api/watchlist/", data=json.dumps({"code": code}), content_type="application/json")

    def test_all_new_users_get_persisted_free_not_implicit_pro(self):
        for user in (self.member, self.staff, self.superuser):
            self.assertEqual(AccountMembership.objects.get(user=user).tier, "free")
            self.assertEqual(resolve_account_tier(user), "free")
            self.assertEqual(resolve_watchlist_limit(user), 10)
        self.assertIsNone(resolve_account_tier(None))

    def test_login_summary_uses_real_database_membership_after_changes(self):
        before = self.client.get("/api/auth/session/").json()
        self.assertEqual(before["user"]["tier"], "free")
        self.assertEqual(before["watchlist_limit"], 10)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        after = self.client.get("/api/auth/session/").json()
        summary = self.client.get("/api/account/summary/").json()
        self.assertEqual(after["user"]["tier"], "pro")
        self.assertEqual(after["user"]["tier_label"], "PRO")
        self.assertEqual(after["watchlist_limit"], 20)
        self.assertEqual(summary["membership"]["tier"], "pro")
        self.assertEqual(summary["watchlist"]["limit"], 20)
        AccountMembership.objects.filter(user=self.member).update(tier="free")
        self.assertEqual(self.client.get("/api/auth/session/").json()["tier"], "free")

    def test_pro_eighteen_free_ten_freeze_unfreeze_restore_order(self):
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        original = self.add_rows(18)
        self.assertEqual(self.client.get("/api/watchlist/").json()["total"], 18)
        self.assertEqual(self.client.get("/api/watchlist/").json()["remaining"], 2)
        self.assertEqual(self.post_code(self.symbols[18].code).status_code, 201)
        # Leave exactly 18 before downgrade; deletion is explicit, not a freeze action.
        self.client.delete(f"/api/watchlist/{self.symbols[18].code}/")
        AccountMembership.objects.filter(user=self.member).update(tier="free")
        payload = self.client.get("/api/watchlist/").json()
        self.assertEqual(payload["limit"], 10)
        self.assertEqual(payload["total"], 10)
        self.assertEqual(payload["remaining"], 0)
        self.assertEqual([i["code"] for i in payload["items"]], [s.code for s in self.symbols[:10]])
        self.assertEqual(WatchlistEntry.objects.filter(user=self.member).count(), 18)
        self.assertEqual(list(WatchlistEntry.objects.filter(user=self.member).values_list("pk", flat=True)), [row.pk for row in original])

        # Market filter must run *after* the global 10-item active quota.
        hk = self.client.get("/api/watchlist/?market=hk").json()
        self.assertEqual([i["code"] for i in hk["items"]], [s.code for s in self.symbols[:10] if s.market == "hk"])
        frozen_code = self.symbols[10].code
        matching = self.client.get(f"/api/symbol-search/?q={frozen_code}&limit=10&page=1").json()["items"]
        self.assertTrue(matching)
        self.assertFalse(next(i for i in matching if i["code"] == frozen_code)["watchlisted"])
        duplicate = self.post_code(frozen_code)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["code"], "watchlist_limit_reached")
        self.assertEqual(WatchlistEntry.objects.filter(user=self.member).count(), 18)

        removed = self.client.delete(f"/api/watchlist/{self.symbols[0].code}/")
        self.assertEqual(removed.status_code, 200)
        next_page = self.client.get("/api/watchlist/").json()
        self.assertEqual(next_page["total"], 10)
        self.assertEqual([i["code"] for i in next_page["items"]], [s.code for s in self.symbols[1:11]])
        self.assertEqual(WatchlistEntry.objects.filter(user=self.member).count(), 17)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        again = self.client.get("/api/watchlist/").json()
        self.assertEqual(again["limit"], 20)
        self.assertEqual(again["total"], 17)
        self.assertEqual([i["code"] for i in again["items"]], [s.code for s in self.symbols[1:18]])

    def test_free_and_pro_quota_enforced_by_server(self):
        self.add_rows(10)
        denied = self.post_code(self.symbols[10].code)
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()["total"], 10)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        for s in self.symbols[10:20]:
            self.assertEqual(self.post_code(s.code).status_code, 201)
        denied_twenty_one = self.post_code(self.symbols[20].code)
        self.assertEqual(denied_twenty_one.status_code, 409)
        self.assertEqual(denied_twenty_one.json()["limit"], 20)
        self.assertEqual(WatchlistEntry.objects.filter(user=self.member).count(), 20)

    def test_duplicate_does_not_change_existing_original_order(self):
        self.add_rows(2)
        first = WatchlistEntry.objects.get(user=self.member, symbol=self.symbols[0])
        stamp = first.created_at
        duplicate = self.post_code(self.symbols[0].code)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["status"], "already_exists")
        self.assertEqual(WatchlistEntry.objects.get(pk=first.pk).created_at, stamp)

    def test_membership_not_editable_for_staff_even_by_direct_inline_formset(self):
        user_admin = admin.site._registry[get_user_model()]
        self.assertIsInstance(user_admin, MembershipUserAdmin)
        staff_request = RequestFactory().get("/admin/auth/user/")
        staff_request.user = self.staff
        super_request = RequestFactory().get("/admin/auth/user/")
        super_request.user = self.superuser
        self.assertEqual(user_admin.get_inlines(staff_request, self.member), [])
        self.assertEqual(user_admin.get_inlines(staff_request, None), [])
        self.assertEqual(user_admin.get_inlines(super_request, self.member), [AccountMembershipInline])
        self.assertEqual(user_admin.account_tier_display(self.member), "FREE")
        self.assertNotIn(AccountMembership, admin.site._registry)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        self.member.refresh_from_db()  # Clear any cached reverse OneToOne object.
        self.assertEqual(user_admin.account_tier_display(self.member), "PRO")


    def test_actual_admin_edit_grants_pro_only_to_superuser(self):
        url = f"/admin/auth/user/{self.member.pk}/change/"
        membership = AccountMembership.objects.get(user=self.member)
        base = {
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
            "account_membership-0-tier": "pro",
            "_save": "Save",
        }
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)
        promoted = self.client.post(url, base)
        self.assertEqual(promoted.status_code, 302, promoted.content[:1000])
        self.assertEqual(AccountMembership.objects.get(user=self.member).tier, "pro")

        self.staff.user_permissions.add(Permission.objects.get(codename="change_user", content_type__app_label="auth"))
        self.client.force_login(self.staff)
        forged = self.client.post(url, {**base, "account_membership-0-tier": "free"})
        # Staff can modify permitted User fields but forged inline inputs are ignored.
        self.assertIn(forged.status_code, {200, 302, 403})
        self.assertEqual(AccountMembership.objects.get(user=self.member).tier, "pro")

    def test_tier_does_not_change_user_staff_or_superuser_flags(self):
        old = (self.member.is_staff, self.member.is_superuser)
        AccountMembership.objects.filter(user=self.member).update(tier="pro")
        self.member.refresh_from_db()
        self.assertEqual((self.member.is_staff, self.member.is_superuser), old)


class MembershipExpiryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="expiry-user", password="secure-password")
        self.membership = AccountMembership.objects.get(user=self.user)
        self.client.force_login(self.user)

    def test_superuser_admin_grant_and_renewal_form(self):
        start = datetime(2026, 11, 10, 15, tzinfo=dt_timezone.utc)
        with patch("core.membership.timezone.now", return_value=start):
            form = AccountMembershipForm(data={
                "tier": "free", "expires_at": "", "grant_duration": "7d",
            }, instance=self.membership)
            self.assertTrue(form.is_valid(), form.errors)
            saved = form.save()
        self.assertEqual(saved.tier, "pro")
        self.assertEqual(saved.expires_at, start + timedelta(days=7))
        # Django admin submits the existing expiration as well as a new duration.
        with patch("core.membership.timezone.now", return_value=start + timedelta(days=1)):
            renewal = AccountMembershipForm(data={
                "tier": "pro",
                "expires_at": saved.expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                "grant_duration": "1m",
            }, instance=saved)
            self.assertTrue(renewal.is_valid(), renewal.errors)
            extended = renewal.save()
        self.assertEqual(extended.expires_at, datetime(2026, 12, 17, 15, tzinfo=dt_timezone.utc))

    def test_five_calendar_periods_preserve_seconds_and_month_ends(self):
        start = datetime(2027, 1, 31, 15, 12, 34, tzinfo=dt_timezone.utc)
        expected = {
            "7d": datetime(2027, 2, 7, 15, 12, 34, tzinfo=dt_timezone.utc),
            "1m": datetime(2027, 2, 28, 15, 12, 34, tzinfo=dt_timezone.utc),
            "3m": datetime(2027, 4, 30, 15, 12, 34, tzinfo=dt_timezone.utc),
            "6m": datetime(2027, 7, 31, 15, 12, 34, tzinfo=dt_timezone.utc),
            "1y": datetime(2028, 1, 31, 15, 12, 34, tzinfo=dt_timezone.utc),
        }
        self.assertEqual(set(expected), {key for key, _ in DURATION_CHOICES})
        for duration, end in expected.items():
            with self.subTest(duration=duration):
                self.assertEqual(period_end(start, duration), end)
        self.assertEqual(period_end(datetime(2028, 2, 29, 15, tzinfo=dt_timezone.utc), "1y"),
                         datetime(2029, 2, 28, 15, tzinfo=dt_timezone.utc))
        with self.assertRaises(ValueError):
            period_end(start, "invalid")

    def test_legacy_pro_remains_indefinite_then_extend_exactly(self):
        start = datetime(2026, 11, 10, 15, tzinfo=dt_timezone.utc)
        self.membership.tier = "pro"
        self.membership.save()
        self.assertEqual(resolve_account_tier(self.user), "pro")
        self.assertIsNone(self.client.get("/api/account/summary/").json()["membership"]["expires_at"])
        end = grant_pro_period(self.membership, "7d", now=start)
        self.assertEqual(end, start + timedelta(days=7))
        self.membership.save()
        self.assertEqual(self.client.get("/api/account/summary/").json()["membership"]["expires_at"], end.isoformat())
        self.assertEqual(grant_pro_period(self.membership, "1m", now=start + timedelta(days=1)),
                         datetime(2026, 12, 17, 15, tzinfo=dt_timezone.utc))

    def test_expired_pro_is_free_for_all_entitlements_without_deleting_records(self):
        self.membership.tier = "pro"
        self.membership.expires_at = timezone.now() - timedelta(seconds=1)
        self.membership.save()
        self.assertEqual(resolve_account_tier(self.user), "free")
        self.assertEqual(resolve_watchlist_limit(self.user), 10)
        self.assertEqual(self.client.get("/api/auth/session/").json()["user"]["tier"], "free")
        self.assertEqual(self.client.get("/api/account/summary/").json()["membership"],
                         {"tier": "free", "tier_label": "FREE", "expires_at": None})
        items = self.client.get("/api/indicators/").json()["items"]
        self.assertTrue(all(not item["allowed"] for item in items
                            if not item.get("common") and item["code"] != "CHANLUN"))
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.tier, "pro")

    def test_expired_renewal_starts_from_now(self):
        now = datetime(2027, 3, 10, 12, 34, 56, tzinfo=dt_timezone.utc)
        self.membership.tier = "pro"
        self.membership.expires_at = now - timedelta(days=1)
        self.assertEqual(grant_pro_period(self.membership, "7d", now=now), now + timedelta(days=7))
