import uuid
from typing import Optional
from jinja2 import Environment, StrictUndefined

from .base import BaseNotificationAdapter, SendResult


class ConsoleNotificationAdapter(BaseNotificationAdapter):
    name = "console"
    channel = "email"

    def __init__(self):
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
        subject_tmpl = self.jinja_env.from_string(template.subject_template or "")
        body_tmpl = self.jinja_env.from_string(template.body_template)

        subject = subject_tmpl.render(**variables)
        body = body_tmpl.render(**variables)

        print(f"\n{'='*80}")
        print(f"NOTIFICATION (Console Backend)")
        print(f"{'='*80}")
        print(f"Notification ID: {notification_id}")
        print(f"Template: {template.template_key}")
        print(f"Recipient: {recipient_contact}")
        print(f"Subject: {subject}")
        print(f"{'-'*80}")
        print(body)
        print(f"{'='*80}\n")

        return SendResult(
            status="sent",
            message_id=f"console_{notification_id}",
        )

    async def validate_contact(self, contact: str) -> bool:
        return True
