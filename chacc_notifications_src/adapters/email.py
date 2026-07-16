import re
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from jinja2 import Environment, StrictUndefined

from .base import BaseNotificationAdapter, SendResult


class EmailNotificationAdapter(BaseNotificationAdapter):
    name = "smtp"
    channel = "email"

    def __init__(self, smtp_config: Optional[dict] = None):
        self.smtp_config = smtp_config
        self.jinja_env = Environment(undefined=StrictUndefined)

    async def send(
        self,
        notification_id: str,
        template,
        recipient_id: str,
        recipient_contact: str,
        variables: dict,
        metadata: Optional[dict] = None,
    ) -> SendResult:
        try:
            if not await self.validate_contact(recipient_contact):
                return SendResult(
                    status="failed",
                    error_message="Invalid email address",
                )

            subject_template_obj = self.jinja_env.from_string(
                template.subject_template or ""
            )
            subject = subject_template_obj.render(**variables)

            body_template_obj = self.jinja_env.from_string(
                template.body_template
            )
            body = body_template_obj.render(**variables)

            message_id = await self._send_email(
                to=recipient_contact,
                subject=subject,
                body=body,
                is_html=(template.email_type == "html"),
            )

            return SendResult(
                status="sent",
                message_id=message_id,
                metadata={"recipient": recipient_contact},
            )

        except Exception as e:
            return SendResult(
                status="failed",
                error_message=str(e),
            )

    async def validate_contact(self, contact: str) -> bool:
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_regex, contact))

    async def _send_email(
        self,
        to: str,
        subject: str,
        body: str,
        is_html: bool,
    ) -> str:
        if not self.smtp_config:
            print(f"\n{'='*80}")
            print(f"EMAIL (Console Backend)")
            print(f"{'='*80}")
            print(f"To: {to}")
            print(f"Subject: {subject}")
            print(f"Type: {'HTML' if is_html else 'Text'}")
            print(f"{'-'*80}")
            print(body)
            print(f"{'='*80}\n")
            return f"console_{uuid.uuid4()}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_config.get("from_email", "noreply@example.com")
        msg["To"] = to

        content_type = "html" if is_html else "plain"
        msg.attach(MIMEText(body, content_type))

        with smtplib.SMTP(
            self.smtp_config["host"],
            self.smtp_config["port"],
        ) as server:
            if self.smtp_config.get("username") and self.smtp_config.get("password"):
                server.starttls()
                server.login(
                    self.smtp_config["username"],
                    self.smtp_config["password"],
                )
            server.send_message(msg)

        return f"smtp_{uuid.uuid4()}"

    async def health_check(self) -> bool:
        if not self.smtp_config:
            return True
        try:
            with smtplib.SMTP(
                self.smtp_config["host"],
                self.smtp_config["port"],
                timeout=5,
            ) as server:
                server.ehlo()
            return True
        except Exception:
            return False
