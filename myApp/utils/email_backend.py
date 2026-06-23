"""Django email backend that delivers via Resend's HTTP API.

Configured by setting EMAIL_BACKEND='myApp.utils.email_backend.ResendEmailBackend'
and providing RESEND_API_KEY (and optionally RESEND_FROM, RESEND_BASE_URL,
RESEND_REPLY_TO) in settings/env.
"""
import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        api_key = (getattr(settings, 'RESEND_API_KEY', '') or '').strip()
        if not api_key:
            if not self.fail_silently:
                raise RuntimeError('RESEND_API_KEY is not configured.')
            return 0
        base_url = (getattr(settings, 'RESEND_BASE_URL', 'https://api.resend.com') or 'https://api.resend.com').rstrip('/')
        default_from = (getattr(settings, 'RESEND_FROM', '') or getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '').strip()
        reply_to = (getattr(settings, 'RESEND_REPLY_TO', '') or '').strip()

        sent = 0
        for msg in email_messages:
            recipients = list(msg.to or []) + list(msg.cc or []) + list(msg.bcc or [])
            if not recipients:
                continue
            payload = {
                'from': msg.from_email or default_from,
                'to': list(msg.to or []),
                'subject': msg.subject or '',
            }
            if msg.cc:
                payload['cc'] = list(msg.cc)
            if msg.bcc:
                payload['bcc'] = list(msg.bcc)

            html_body = None
            for body, mime in getattr(msg, 'alternatives', []) or []:
                if mime == 'text/html':
                    html_body = body
                    break
            if html_body:
                payload['html'] = html_body
                payload['text'] = msg.body or ''
            else:
                payload['text'] = msg.body or ''

            extra_reply_to = list(msg.reply_to or [])
            if extra_reply_to:
                payload['reply_to'] = extra_reply_to[0]
            elif reply_to:
                payload['reply_to'] = reply_to

            try:
                resp = requests.post(
                    f"{base_url}/emails",
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                    },
                    json=payload,
                    timeout=15,
                )
                if resp.status_code >= 400:
                    detail = resp.text
                    try:
                        detail = resp.json()
                    except Exception:
                        pass
                    if not self.fail_silently:
                        raise RuntimeError(f"Resend API {resp.status_code}: {detail}")
                    logger.error("Resend API %s: %s", resp.status_code, detail)
                    continue
                sent += 1
            except Exception as exc:
                if not self.fail_silently:
                    raise
                logger.exception("Resend send failed for %s: %s", payload.get('to'), exc)
        return sent
