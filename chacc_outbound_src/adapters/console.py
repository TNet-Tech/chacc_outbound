import uuid
from typing import Optional

from .base import BaseOutboundAdapter, SendResult


class ConsoleOutboundAdapter(BaseOutboundAdapter):
    name = "console"
    channel = "email"
    description = "Prints messages to the console for local testing"

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
        subject = subject or ""
        body = body or ""

        print(f"\n{'='*80}")
        print("")
        print(f"Messaging UUID: {messaging_uuid}")
        print(f"Recipient: {recipient_contact}")
        print(f"Subject: {subject}")
        print(f"{'-'*80}")
        print(body)
        print("")
        print(f"{'='*80}\n")

        return SendResult(
            status="sent",
            message_id=f"console_{messaging_uuid}",
        )

    async def validate_contact(self, contact: str) -> bool:
        return True