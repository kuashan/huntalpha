"""Brevo HTTPS transactional email backend; no SMTP port or new dependency."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.mail.backends.base import BaseEmailBackend


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        api_key = os.environ.get("BREVO_API_KEY", "")
        if not api_key:
            raise OSError("Verification mail provider is not configured")
        sent = 0
        for message in email_messages:
            if len(message.recipients()) != 1:
                raise OSError("Verification mail requires one recipient")
            payload = {
                "sender": {"email": message.from_email, "name": "SiftAlpha"},
                "to": [{"email": message.recipients()[0]}],
                "subject": message.subject,
                "textContent": message.body,
            }
            request = Request(
                "https://api.brevo.com/v3/smtp/email",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"api-key": api_key, "Content-Type": "application/json", "accept": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=10) as response:
                    if response.status not in (200, 201, 202):
                        raise OSError("Verification mail delivery failed")
            except (HTTPError, URLError, TimeoutError) as exc:
                # Never expose provider response text, recipient or API key.
                raise OSError("Verification mail delivery failed") from exc
            sent += 1
        return sent
