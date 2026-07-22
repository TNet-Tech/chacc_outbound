import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select

from .models import Messaging, ModuleMessagingMapping, MessagingStatus
from .adapters import MessagingAdapterRegistry
from .exceptions import AdapterNotFoundError

logger = logging.getLogger(__name__)


class MessagingService:
    def __init__(
        self,
        adapter_registry: MessagingAdapterRegistry,
        config: dict,
        module_context=None,
        redis=None,
    ):
        self.adapters = adapter_registry
        self.config = config
        self.module_context = module_context
        self.redis = redis
        self._tasks: set = set()

    async def send(
        self,
        db,
        recipient_id: str,
        recipient_contact: str,
        body: str,
        module_name: str,
        subject: Optional[str] = None,
        channel: str = "email",
        adapter_name: str = "console",
        metadata: Optional[dict] = None,
        overrides: Optional[dict] = None,
        content_type: str = "text/plain",
    ) -> Messaging:
        """
        Send a notification and enqueue async delivery.

        Returns the created Messaging ORM instance. All internal async
        delivery and status updates use uuid. The id column is kept for
        internal DB operations only and is never exposed in API responses.

        The returned object must be serialized before JSON response:
            - str(message.uuid) for UUID
            - message.status.value for enum
            - message.sent_at.isoformat() if sent_at
            - message.messaging_metadata for metadata
        """
        mapping = self.get_module_mapping(db, module_name)
        rate_limit = self._apply_overrides(mapping, "rate_limit_per_minute", None, overrides)
        if rate_limit and self.redis:
            key = f"messaging:rate:{module_name}:{channel}"
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, 60)
            if current > rate_limit:
                raise AdapterNotFoundError(channel, f"rate_limit_exceeded:{rate_limit}")

        messaging_notification = Messaging(
            module_name=module_name,
            recipient_id=recipient_id,
            channel=channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            messaging_metadata=metadata,
            status=MessagingStatus.PENDING,
        )
        db.add(messaging_notification)
        db.flush()

        task = asyncio.create_task(
            self._deliver_async(
                messaging_uuid=messaging_notification.uuid,
                adapter_name=adapter_name,
                overrides=overrides,
                content_type=content_type,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return messaging_notification

    async def _deliver_async(
        self,
        messaging_uuid: str,
        adapter_name: Optional[str] = None,
        overrides: Optional[dict] = None,
        content_type: str = "text/plain",
    ) -> None:
        context = self.module_context
        db = None
        try:
            if context:
                db = await context.get_db().__anext__()
            else:
                return

            messaging = db.execute(
                select(Messaging).where(Messaging.uuid == messaging_uuid)
            ).scalar_one_or_none()
            if not messaging:
                return

            mapping = self.get_module_mapping(db, messaging.module_name)
            max_retries = self._apply_overrides(mapping, "max_retry_attempts", 3, overrides)
            backoff = self._apply_overrides(mapping, "retry_backoff_seconds", 300, overrides)

            effective_adapter_name = adapter_name or mapping.default_adapter_name if mapping else "console"
            try:
                adapter = self.adapters.get(
                    channel=messaging.channel,
                    adapter_name=effective_adapter_name,
                )
            except AdapterNotFoundError as e:
                messaging.status = MessagingStatus.FAILED
                messaging.last_error = str(e)
                db.commit()
                return

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await adapter.send(
                        messaging_uuid=str(messaging.uuid),
                        recipient_id=messaging.recipient_id,
                        recipient_contact=messaging.recipient_contact,
                        metadata=messaging.messaging_metadata,
                        subject=messaging.subject,
                        body=messaging.body,
                        content_type=content_type,
                    )

                    if result.status == "sent":
                        messaging.status = MessagingStatus.SENT
                        messaging.sent_at = datetime.now(timezone.utc)
                        messaging.attempts = attempt
                        if result.error_message:
                            messaging.last_error = result.error_message
                        db.commit()
                        return

                    last_error = result.error_message or "Unknown error"
                    messaging.status = MessagingStatus.RETRYING
                    messaging.last_error = last_error
                    messaging.attempts = attempt
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except Exception as e:
                    last_error = str(e)
                    messaging.status = MessagingStatus.RETRYING
                    messaging.last_error = last_error
                    messaging.attempts = attempt
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

            messaging.status = MessagingStatus.FAILED
            messaging.last_error = last_error or "Max retries exceeded"
            db.commit()

        except Exception as e:
            if db:
                try:
                    messaging = db.execute(
                        select(Messaging).where(Messaging.uuid == messaging_uuid)
                    ).scalar_one_or_none()
                    if messaging:
                        messaging.status = MessagingStatus.FAILED
                        messaging.last_error = str(e)
                        db.commit()
                except Exception:
                    pass
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def _apply_overrides(
        self,
        mapping: Optional[ModuleMessagingMapping],
        key: str,
        default: Optional[int],
        overrides: Optional[dict],
    ) -> Optional[int]:
        if overrides and key in overrides:
            return overrides[key]
        if mapping and hasattr(mapping, key) and getattr(mapping, key) is not None:
            return getattr(mapping, key)
        return default

    def get_notification(self, db, notification_uuid: str) -> Optional[Messaging]:
        result = db.execute(
            select(Messaging).where(Messaging.uuid == notification_uuid)
        )
        return result.scalar_one_or_none()

    async def get_status(self, db, notification_uuid: str) -> Optional[MessagingStatus]:
        notification = self.get_notification(db, notification_uuid)
        if notification:
            return notification.status
        return None

    def get_module_mapping(self, db, module_name: str) -> Optional[ModuleMessagingMapping]:
        result = db.execute(
            select(ModuleMessagingMapping).where(
                ModuleMessagingMapping.module_name == module_name
            )
        )
        return result.scalar_one_or_none()

    def create_or_update_module_mapping(
        self,
        db,
        module_name: str,
        default_adapter_name: Optional[str] = None,
        default_channel: Optional[str] = None,
        max_retry_attempts: Optional[int] = None,
        retry_backoff_seconds: Optional[int] = None,
        rate_limit_per_minute: Optional[int] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> ModuleMessagingMapping:
        mapping = self.get_module_mapping(db, module_name)
        if mapping:
            if default_adapter_name is not None:
                mapping.default_adapter_name = default_adapter_name
            if default_channel is not None:
                mapping.default_channel = default_channel
            if max_retry_attempts is not None:
                mapping.max_retry_attempts = max_retry_attempts
            if retry_backoff_seconds is not None:
                mapping.retry_backoff_seconds = retry_backoff_seconds
            if rate_limit_per_minute is not None:
                mapping.rate_limit_per_minute = rate_limit_per_minute
            if is_active is not None:
                mapping.is_active = is_active
            if description is not None:
                mapping.description = description
        else:
            mapping = ModuleMessagingMapping(
                module_name=module_name,
                default_adapter_name=default_adapter_name or "console",
                default_channel=default_channel or "email",
                max_retry_attempts=max_retry_attempts or 3,
                retry_backoff_seconds=retry_backoff_seconds or 300,
                rate_limit_per_minute=rate_limit_per_minute,
                is_active=is_active if is_active is not None else True,
                description=description,
            )
            db.add(mapping)
        db.flush()
        return mapping