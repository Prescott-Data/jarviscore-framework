"""
jarviscore.integrations.connectors.email
==========================================
EmailConnector — send emails via SendGrid or SMTP fallback.

Usage:
    from jarviscore.integrations.connectors.email import EmailConnector
    email = EmailConnector()
    email.send_email(to="muyukani@prescottdata.io",
                     subject="Investor Update Ready", body=report_md)
"""
from __future__ import annotations
import logging, os
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class EmailConnector:
    """SendGrid-first email connector, SMTP fallback."""

    def __init__(
        self,
        sendgrid_api_key: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> None:
        self._key = sendgrid_api_key or os.environ.get("SENDGRID_API_KEY")
        self._from = from_email or os.environ.get("SENDGRID_FROM_EMAIL", "agents@prescottdata.io")

    def send_email(self, to: str, subject: str, body: str, html: bool = False) -> Dict[str, Any]:
        """Send a plain text or HTML email."""
        if self._key:
            return self._sendgrid(to, subject, body, html)
        return self._smtp(to, subject, body)

    def _sendgrid(self, to: str, subject: str, body: str, html: bool) -> Dict[str, Any]:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Content
            content_type = "text/html" if html else "text/plain"
            msg = Mail(
                from_email=self._from,
                to_emails=to,
                subject=subject,
                html_content=body if html else None,
                plain_text_content=body if not html else None,
            )
            sg = SendGridAPIClient(self._key)
            resp = sg.send(msg)
            logger.info("[Email] Sent via SendGrid to %s: status %s", to, resp.status_code)
            return {"status": "success", "to": to, "provider": "sendgrid"}
        except ImportError:
            logger.warning("[Email] sendgrid not installed — falling back to SMTP")
            return self._smtp(to, subject, body)
        except Exception as exc:
            logger.error("[Email] SendGrid send failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _smtp(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        import smtplib
        from email.mime.text import MIMEText
        host = os.environ.get("SMTP_HOST", "localhost")
        port = int(os.environ.get("SMTP_PORT", "25"))
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self._from
            msg["To"] = to
            with smtplib.SMTP(host, port) as server:
                server.sendmail(self._from, [to], msg.as_string())
            return {"status": "success", "to": to, "provider": "smtp"}
        except Exception as exc:
            logger.error("[Email] SMTP send failed: %s", exc)
            return {"status": "error", "error": str(exc)}
