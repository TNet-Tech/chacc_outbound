import uuid
from typing import Optional
from jinja2 import Environment, StrictUndefined

from .base import BaseMessagingAdapter, SendResult


class ConsoleMessagingAdapter(BaseMessagingAdapter):
    name = "console"
    channel = "email"

    def __init__(self):
        self.jinja_env = Environment(undefined=StrictUndefined)

    async def send(
        self,
        messaging_id: str,
        template,
        recipient_id: str,
        recipient_contact: str,
        variables: dict,
        metadata: Optional[dict] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> SendResult:
        if template:
            subject_tmpl = self.jinja_env.from_string(template.subject_template or "")
            subject = subject_tmpl.render(**variables)
            body_tmpl = self.jinja_env.from_string(template.body_template)
            body = body_tmpl.render(**variables)
        else:
            subject = subject or ""
            body = body or ""

        print(f"\n{'='*80}")
        print(f"NOTIFICATION (Console Backend)")
        print(f"{'='*80}")
        print(f"Messaging ID: {messaging_id}")
        if template:
            print(f"Template: {template.template_key}")
        else:
            print(f"Template: (direct send)")
        print(f"Recipient: {recipient_contact}")
        print(f"Subject: {subject}")
        print(f"{'-'*80}")
        print(body)
        print(f"{'='*80}\n")

        return SendResult(
            status="sent",
            message_id=f"console_{messaging_id}",
        )

    async def validate_contact(self, contact: str) -> bool:
        return True
