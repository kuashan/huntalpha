"""Only the approved pre-launch signup/login protections live here."""
import ipaddress
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import AuthRateLimit, PendingEmailRegistration


class RateLimited(Exception):
    pass


class VerificationUnavailable(Exception):
    pass


def client_ip(request):
    # Only trust Cloudflare's connecting-IP after production explicitly opts in.
    raw = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "HUNTALPHA_TRUST_CLOUDFLARE_IP", False):
        raw = request.META.get("HTTP_CF_CONNECTING_IP") or raw
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return "unknown"


def _key(namespace, value):
    return salted_hmac("siftalpha-auth-limit", f"{namespace}:{value}").hexdigest()


def take_limit(namespace, value, limit, seconds):
    """Atomic database-backed fixed window, shared across Gunicorn workers."""
    key = _key(namespace, value)
    now = timezone.now()
    with transaction.atomic():
        bucket, _ = AuthRateLimit.objects.select_for_update().get_or_create(
            key=key, defaults={"count": 0, "window_ends_at": now + timedelta(seconds=seconds)}
        )
        if bucket.window_ends_at <= now:
            bucket.count = 0
            bucket.window_ends_at = now + timedelta(seconds=seconds)
        if bucket.count >= limit:
            return False
        bucket.count += 1
        bucket.save(update_fields=["count", "window_ends_at"])
    return True


def limit_reached(namespace, value, limit):
    bucket = AuthRateLimit.objects.filter(key=_key(namespace, value)).first()
    return bool(bucket and bucket.window_ends_at > timezone.now() and bucket.count >= limit)


def clear_limit(namespace, value):
    AuthRateLimit.objects.filter(key=_key(namespace, value)).delete()


def _code_hash(email, code):
    return salted_hmac("siftalpha-email-code", f"{email}:{code}").hexdigest()


def _email_code(email, code):
    message = f"您的 SiftAlpha 注册验证码是：{code}。10 分钟内有效，请勿转发。"
    delivered = send_mail(
        "SiftAlpha 邮箱验证", message, settings.DEFAULT_FROM_EMAIL, [email],
        fail_silently=False,
    )
    if delivered != 1:
        raise VerificationUnavailable("email delivery failed")


def issue_signup(email, password, display_name):
    """Store only a password hash and an HMAC of the OTP; never a live User."""
    now = timezone.now()
    existing = PendingEmailRegistration.objects.filter(email=email).first()
    if existing and existing.expires_at > now and (now - existing.sent_at).total_seconds() < 60:
        raise RateLimited()
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _code_hash(email, code)
    PendingEmailRegistration.objects.update_or_create(
        email=email,
        defaults={
            "display_name": display_name,
            "password_hash": make_password(password),
            "code_hash": digest,
            "expires_at": now + timedelta(minutes=10),
            "sent_at": now,
            "failed_attempts": 0,
        },
    )
    try:
        _email_code(email, code)
    except Exception as exc:
        # A failed provider should not reserve an email or create an account.
        PendingEmailRegistration.objects.filter(email=email, code_hash=digest).delete()
        raise VerificationUnavailable() from exc


def resend_signup(email):
    now = timezone.now()
    pending = PendingEmailRegistration.objects.filter(email=email).first()
    if pending is None or pending.expires_at <= now:
        return False
    if pending.failed_attempts >= 5 or (now - pending.sent_at).total_seconds() < 60:
        raise RateLimited()
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _code_hash(email, code)
    old_digest, old_sent_at = pending.code_hash, pending.sent_at
    pending.code_hash, pending.sent_at = digest, now
    pending.save(update_fields=["code_hash", "sent_at"])
    try:
        _email_code(email, code)
    except Exception as exc:
        PendingEmailRegistration.objects.filter(email=email, code_hash=digest).update(
            code_hash=old_digest, sent_at=old_sent_at,
        )
        raise VerificationUnavailable() from exc
    return True


def claim_signup(email, code):
    """Return (user, status); only a successful code creates a real user."""
    now = timezone.now()
    with transaction.atomic():
        pending = PendingEmailRegistration.objects.select_for_update().filter(email=email).first()
        if pending is None or pending.expires_at <= now:
            return None, "expired"
        if pending.failed_attempts >= 5:
            return None, "locked"
        if not (len(code) == 6 and code.isascii() and code.isdigit() and constant_time_compare(
            pending.code_hash, _code_hash(email, code)
        )):
            pending.failed_attempts += 1
            pending.save(update_fields=["failed_attempts"])
            return None, "invalid" if pending.failed_attempts < 5 else "locked"

        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            return None, "exists"
        candidate = User(username=email, email=email, first_name=pending.display_name)
        candidate.password = pending.password_hash
        candidate.save()
        pending.delete()
        return candidate, "verified"
