"""Isolated pre-launch tests: no real provider, account or email delivery."""
import json
import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import AccountMembership, AuthRateLimit, PendingEmailRegistration


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class VerifiedRegistrationTests(TestCase):
    def request_json(self, path, payload, client=None, ip="192.0.2.1"):
        return (client or self.client).post(
            path, json.dumps(payload), content_type="application/json", REMOTE_ADDR=ip,
        )

    def begin(self, email="new@example.com", ip="192.0.2.1"):
        return self.request_json("/api/auth/register/", {
            "email": email, "password": "A-safe-password-42", "name": "New user",
        }, ip=ip)

    def code(self):
        return re.search(r"\b[0-9]{6}\b", mail.outbox[-1].body).group()

    def test_verify_creates_account_and_free_entitlement_only_after_code(self):
        self.assertEqual(self.begin().status_code, 202)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())
        self.assertEqual(self.client.get("/api/auth/session/").status_code, 401)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(self.code(), PendingEmailRegistration.objects.get().code_hash)
        done = self.request_json("/api/auth/verify-email/", {
            "email": "NEW@example.com", "code": self.code(),
        })
        self.assertEqual(done.status_code, 201)
        self.assertEqual(done.json()["tier"], "free")
        user = get_user_model().objects.get(email="new@example.com")
        self.assertTrue(user.check_password("A-safe-password-42"))
        self.assertEqual(AccountMembership.objects.get(user=user).tier, "free")
        self.assertFalse(PendingEmailRegistration.objects.exists())
        self.assertEqual(self.client.get("/api/auth/session/").status_code, 200)
        self.assertEqual(self.request_json("/api/auth/verify-email/", {
            "email": "new@example.com", "code": "123456",
        }).status_code, 400)

    def test_wrong_code_locked_on_fifth_attempt(self):
        self.begin()
        real = self.code()
        wrong = "000000" if real != "000000" else "111111"
        for i in range(5):
            response = self.request_json("/api/auth/verify-email/", {
                "email": "new@example.com", "code": wrong,
            })
            self.assertEqual(response.status_code, 429 if i == 4 else 400)
        self.assertEqual(self.request_json("/api/auth/verify-email/", {
            "email": "new@example.com", "code": real,
        }).status_code, 429)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())

    def test_expired_code_cannot_create_account(self):
        self.begin()
        code = self.code()
        PendingEmailRegistration.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.request_json("/api/auth/verify-email/", {
            "email": "new@example.com", "code": code,
        }).status_code, 400)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())

    def test_resend_cooldown_and_old_code_is_revoked(self):
        self.begin()
        first = self.code()
        self.assertEqual(self.request_json("/api/auth/resend-code/", {"email": "new@example.com"}).status_code, 429)
        PendingEmailRegistration.objects.update(sent_at=timezone.now() - timedelta(seconds=61))
        response = self.request_json("/api/auth/resend-code/", {"email": "new@example.com"})
        self.assertEqual(response.status_code, 200)
        second = self.code()
        self.assertNotEqual(first, second)
        self.assertEqual(self.request_json("/api/auth/verify-email/", {"email": "new@example.com", "code": first}).status_code, 400)
        self.assertEqual(self.request_json("/api/auth/verify-email/", {"email": "new@example.com", "code": second}).status_code, 201)

    def test_register_ip_limit_three_per_ten_minutes(self):
        for i in range(3):
            self.assertEqual(self.begin(f"member{i}@example.com").status_code, 202)
        self.assertEqual(self.begin("member4@example.com").status_code, 429)
        self.assertEqual(len(mail.outbox), 3)
        self.assertFalse(get_user_model().objects.filter(email="member4@example.com").exists())

    def test_failed_email_provider_creates_no_user_or_pending(self):
        with patch("core.account_security._email_code", side_effect=OSError("provider offline")):
            response = self.begin()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PendingEmailRegistration.objects.exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_legacy_pro_is_not_required_to_verify_again(self):
        user = get_user_model().objects.create_user(username="legacy@example.com",
             email="legacy@example.com", password="Strong-password-42")
        AccountMembership.objects.filter(user=user).update(tier="pro")
        self.assertEqual(self.request_json("/api/auth/login/", {
            "email": "legacy@example.com", "password": "Strong-password-42",
        }).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/session/").json()["tier"], "pro")
        self.assertEqual(self.begin("legacy@example.com").status_code, 409)
        self.assertEqual(AccountMembership.objects.get(user=user).tier, "pro")


class LoginRateTests(TestCase):
    def login(self, password="wrong", ip="198.51.100.2"):
        return self.client.post("/api/auth/login/", json.dumps({
            "email": "existing@example.com", "password": password,
        }), content_type="application/json", REMOTE_ADDR=ip)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="existing@example.com", email="existing@example.com",
            password="Correct-password-42",
        )

    def test_five_failures_lock_account_across_ips(self):
        for i in range(5):
            self.assertEqual(self.login(ip=f"198.51.100.{i+1}").status_code, 401)
        self.assertEqual(self.login("Correct-password-42", ip="198.51.100.17").status_code, 429)
        self.assertTrue(self.user.check_password("Correct-password-42"))

    def test_ten_attempts_per_ip_then_429(self):
        for i in range(10):
            self.login(ip="198.51.100.2")
        self.assertEqual(self.login("Correct-password-42").status_code, 429)
        self.assertTrue(AuthRateLimit.objects.exists())

    def test_successful_login_preserves_existing_user(self):
        self.assertEqual(self.login("Correct-password-42").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/session/").status_code, 200)
