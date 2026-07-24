import re
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from .base import BaseOutboundAdapter, SendResult
from ..exceptions import AdapterConfigError


class EmailOutboundAdapter(BaseOutboundAdapter):
    name = "smtp"
    channel = "email"
    description = "Sends real emails via SMTP"

    def __init__(self, smtp_config: Optional[dict] = None):
        self.smtp_config = smtp_config

    async def send(
        self,
        messaging_uuid: str,
        recipient_id: str,
        recipient_contact: str,
        metadata: Optional[dict] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        content_type: str = "text/plain",
    ) -> SendResult:
        if not self.smtp_config:
            raise AdapterConfigError(
                adapter_name="smtp",
                reason="SMTP configuration is missing. EMAIL_BACKEND=smtp requires host, port, username, and password.",
            )

        if not await self.validate_contact(recipient_contact):
            raise ValueError("Invalid email address")

        subject = subject or ""
        body = body or ""

        await self._send_email(
            to=recipient_contact,
            subject=subject,
            body=body,
            content_type=content_type,
        )

        return SendResult(
            status="sent",
            message_id=f"smtp_{messaging_uuid}",
            metadata={"recipient": recipient_contact},
        )

    async def validate_contact(self, contact: str) -> bool:
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(email_regex, contact))

    async def _send_email(
        self,
        to: str,
        subject: str,
        body: str,
        content_type: str = "text/plain",
    ) -> None:
        subtype = "plain" if content_type == "text/plain" else content_type

        if subtype == "html":
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.smtp_config.get("from_email", "noreply@example.com")
            msg["To"] = to
            msg.attach(MIMEText(body, subtype))
        else:
            msg = MIMEText(body, subtype)
            msg["Subject"] = subject
            msg["From"] = self.smtp_config.get("from_email", "noreply@example.com")
            msg["To"] = to

        smtp = aiosmtplib.SMTP(
            hostname=self.smtp_config["host"],
            port=self.smtp_config["port"],
            timeout=10,
            use_tls=self.smtp_config.get("use_tls", False),
        )
        async with smtp:
            if self.smtp_config.get("username") and self.smtp_config.get("password"):
                if not self.smtp_config.get("use_tls", False):
                    await smtp.starttls()
                await smtp.login(
                    self.smtp_config["username"],
                    self.smtp_config["password"],
                )
            await smtp.send_message(msg)

    async def health_check(self) -> bool:
        if not self.smtp_config:
            return False
        try:
            smtp = aiosmtplib.SMTP(
                hostname=self.smtp_config["host"],
                port=self.smtp_config["port"],
                timeout=5,
                use_tls=self.smtp_config.get("use_tls", False),
            )
            async with smtp:
                await smtp.connect()
            return True
        except Exception:
            return False