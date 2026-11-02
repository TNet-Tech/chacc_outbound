import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .adapter_service import OutboundAdapterRegistryService
from .exceptions import (
    NON_RETRYABLE_EXCEPTIONS,
    RETRYABLE_EXCEPTIONS,
    AdapterConfigError,
    AdapterNotFoundError,
)
from .models import Outbound, OutboundModuleMapping, OutboundStatus

logger = logging.getLogger(__name__)


class OutboundService:
    def __init__(
        self,
        config: dict,
        module_context=None,
        adapter_registry_service: OutboundAdapterRegistryService | None = None,
        redis=None,
    ):
        self.adapter_registry_service = adapter_registry_service
        self.config = config
        self.module_context = module_context
        self.redis = redis
        self._tasks: set = set()

    async def send(
        self,
        recipient_id: str,
        recipient_contact: str,
        body: str,
        module_name: str,
        subject: str | None = None,
        channel: str = "email",
        metadata: dict | None = None,
        overrides: dict | None = None,
        content_type: str = "text/plain",
    ) -> dict:
        """
        Send a notification and enqueue async delivery.

        Returns a serialized dict representation of the created outbound record,
        so callers don't need to manually serialize ORM attributes.
        """
        async with self._database_session() as session:
            mapping = await self.get_module_mapping(session, module_name)
            rate_limit = self._apply_overrides(
                mapping, "rate_limit_per_minute", None, overrides
            )
            resolved_adapter_name = (
                mapping.default_adapter_name if mapping else None
            ) or self.config.get("EMAIL_BACKEND", "console")

        if rate_limit and self.redis:
            key = f"messaging:rate:{module_name}:{channel}"
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, 60)
            if current > rate_limit:
                raise AdapterNotFoundError(channel, f"rate_limit_exceeded:{rate_limit}")

        outbound_message = Outbound(
            module_name=module_name,
            recipient_id=recipient_id,
            channel=channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            messaging_metadata=metadata,
            status=OutboundStatus.PENDING,
            attempts=0,
        )
        async with self._database_session() as session:
            session.add(outbound_message)
            await session.flush()
            await session.commit()
            serialized_message = self._serialize_outbound(outbound_message)

        task = asyncio.create_task(
            self._deliver_async(
                messaging_uuid=outbound_message.uuid,
                adapter_name=resolved_adapter_name,
                overrides=overrides,
                content_type=content_type,
            )
        )
        self._tasks.add(task)

        def _on_task_done(t):
            self._tasks.discard(t)
            if t.exception():
                logger.error(
                    "Background delivery task failed for %s: %s",
                    outbound_message.uuid,
                    t.exception(),
                    exc_info=t.exception(),
                )

        task.add_done_callback(_on_task_done)

        return serialized_message

    def _serialize_outbound(self, n) -> dict:
        return {
            "uuid": str(n.uuid),
            "module_name": n.module_name,
            "recipient_id": n.recipient_id,
            "channel": n.channel,
            "subject": n.subject,
            "body": n.body,
            "recipient_contact": n.recipient_contact,
            "outbound_metadata": n.messaging_metadata,
            "status": n.status.value,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
            "attempts": n.attempts,
            "last_error": n.last_error,
        }

    async def _deliver_async(
        self,
        messaging_uuid: str,
        adapter_name: str | None = None,
        overrides: dict | None = None,
        content_type: str = "text/plain",
    ) -> None:
        context = self.module_context
        try:
            if context is None:
                logger.warning(
                    "No module_context available; cannot deliver outbound message %s",
                    messaging_uuid,
                )
                return

            async with self._database_session() as db:
                messaging = await self.get_message(db, messaging_uuid)
                if messaging is None:
                    logger.warning(
                        "Outbound message %s not found in database", messaging_uuid
                    )
                    return
                message = {
                    "uuid": str(messaging.uuid),
                    "module_name": messaging.module_name,
                    "channel": messaging.channel,
                    "recipient_id": messaging.recipient_id,
                    "recipient_contact": messaging.recipient_contact,
                    "subject": messaging.subject,
                    "body": messaging.body,
                    "metadata": messaging.messaging_metadata,
                }
                mapping = await self.get_module_mapping(db, message["module_name"])
            max_retries = self._apply_overrides(
                mapping, "max_retry_attempts", 3, overrides
            )
            backoff = self._apply_overrides(
                mapping, "retry_backoff_seconds", 300, overrides
            )

            effective_adapter_name = adapter_name
            logger.info(
                "Delivering outbound %s via adapter=%s retries=%s backoff=%s",
                messaging_uuid,
                effective_adapter_name,
                max_retries,
                backoff,
            )
            try:
                adapter = self.adapter_registry_service.get(
                    channel=messaging.channel,
                    adapter_name=effective_adapter_name,
                )
            except AdapterNotFoundError as e:
                logger.error("Adapter not found for outbound %s: %s", messaging_uuid, e)
                await self._update_message(
                    messaging_uuid,
                    status=OutboundStatus.FAILED,
                    last_error=str(e),
                )
                return

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await adapter.send(
                        messaging_uuid=message["uuid"],
                        recipient_id=message["recipient_id"],
                        recipient_contact=message["recipient_contact"],
                        metadata=message["metadata"],
                        subject=message["subject"],
                        body=message["body"],
                        content_type=content_type,
                    )

                    if result.status == "sent":
                        logger.info(
                            "Adapter reported SENT for outbound %s", messaging_uuid
                        )
                        updates = {
                            "status": OutboundStatus.SENT,
                            "sent_at": datetime.now(UTC),
                            "attempts": attempt,
                        }
                        if result.error_message:
                            updates["last_error"] = result.error_message
                        await self._update_message(messaging_uuid, **updates)
                        logger.info("Outbound %s marked as SENT in DB", messaging_uuid)
                        return

                    if result.status == "failed":
                        logger.warning(
                            "Adapter reported FAILED for outbound %s: %s",
                            messaging_uuid,
                            result.error_message,
                        )
                        await self._update_message(
                            messaging_uuid,
                            status=OutboundStatus.FAILED,
                            last_error=result.error_message
                            or "Adapter reported failure",
                            attempts=attempt,
                        )
                        logger.info(
                            "Outbound %s marked as FAILED in DB", messaging_uuid
                        )
                        return

                    last_error = result.error_message or "Unknown error"
                    await self._update_message(
                        messaging_uuid,
                        status=OutboundStatus.RETRYING,
                        last_error=last_error,
                        attempts=attempt,
                    )

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except AdapterConfigError as e:
                    logger.error(
                        "Adapter config error for outbound %s: %s", messaging_uuid, e
                    )
                    await self._update_message(
                        messaging_uuid,
                        status=OutboundStatus.FAILED,
                        last_error=str(e),
                        attempts=attempt,
                    )
                    return

                except RETRYABLE_EXCEPTIONS as e:
                    last_error = str(e)
                    logger.warning(
                        "Retryable error for outbound %s (attempt %s): %s",
                        messaging_uuid,
                        attempt,
                        e,
                    )
                    await self._update_message(
                        messaging_uuid,
                        status=OutboundStatus.RETRYING,
                        last_error=last_error,
                        attempts=attempt,
                    )

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except NON_RETRYABLE_EXCEPTIONS as e:
                    logger.error(
                        "Non-retryable error for outbound %s: %s", messaging_uuid, e
                    )
                    await self._update_message(
                        messaging_uuid,
                        status=OutboundStatus.FAILED,
                        last_error=str(e),
                        attempts=attempt,
                    )
                    return

            logger.warning(
                "Outbound %s failed after %s retries", messaging_uuid, max_retries
            )
            await self._update_message(
                messaging_uuid,
                status=OutboundStatus.FAILED,
                last_error=last_error or "Max retries exceeded",
            )

        except Exception as e:
            logger.error(
                "Outbound delivery failed for %s: %s", messaging_uuid, e, exc_info=True
            )
            try:
                await self._update_message(
                    messaging_uuid,
                    status=OutboundStatus.FAILED,
                    last_error=str(e),
                )
            except Exception as inner_e:
                logger.error(
                    "Failed to mark outbound %s as FAILED: %s",
                    messaging_uuid,
                    inner_e,
                    exc_info=True,
                )

    @asynccontextmanager
    async def _database_session(self):
        context = self.module_context
        if context is None:
            raise RuntimeError("Database context is not available")
        db_generator = context.get_db_async()
        db = None
        try:
            db = await anext(db_generator)
            yield db
        except BaseException:
            if db is not None:
                try:
                    await db.rollback()
                except Exception:
                    logger.exception("Failed to roll back outbound database session")
            raise
        finally:
            await db_generator.aclose()

    async def _update_message(self, messaging_uuid: str, **updates) -> bool:
        async with self._database_session() as db:
            messaging = await self.get_message(db, messaging_uuid)
            if messaging is None:
                logger.warning(
                    "Outbound message %s not found while updating status",
                    messaging_uuid,
                )
                return False
            for field, value in updates.items():
                setattr(messaging, field, value)
            await db.flush()
            await db.commit()
            return True

    def _apply_overrides(
        self,
        mapping: OutboundModuleMapping | None,
        key: str,
        default: int | None,
        overrides: dict | None,
    ) -> int | None:
        if overrides and key in overrides:
            return overrides[key]
        if mapping and hasattr(mapping, key) and getattr(mapping, key) is not None:
            return getattr(mapping, key)
        return default

    async def get_message(
        self, db: AsyncSession, outbound_messaging_uuid: str
    ) -> Outbound | None:
        result = await db.execute(
            select(Outbound).where(Outbound.uuid == outbound_messaging_uuid)
        )
        return result.scalar_one_or_none()

    async def get_status(
        self, db: AsyncSession, outbound_messaging_uuid: str
    ) -> str | None:
        message = await self.get_message(db, outbound_messaging_uuid)
        if message:
            status = message.status
            if hasattr(status, "value"):
                return status.value
            return str(status)
        return None

    async def get_module_mapping(
        self, db: AsyncSession, module_name: str
    ) -> OutboundModuleMapping | None:
        result = await db.execute(
            select(OutboundModuleMapping).where(
                OutboundModuleMapping.module_name == module_name
            )
        )
        return result.scalar_one_or_none()

    async def _create_or_update_module_mapping(
        self,
        db: AsyncSession,
        module_name: str,
        default_adapter_name: str | None = None,
        default_channel: str | None = None,
        max_retry_attempts: int | None = None,
        retry_backoff_seconds: int | None = None,
        rate_limit_per_minute: int | None = None,
        is_active: bool | None = None,
        description: str | None = None,
    ) -> OutboundModuleMapping:
        mapping = await self.get_module_mapping(db, module_name)
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
            mapping = OutboundModuleMapping(
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
        await db.flush()
        return mapping
