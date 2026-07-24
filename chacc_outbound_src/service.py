import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select

from .models import Outbound, OutboundModuleMapping, OutboundStatus
from .adapter_service import OutboundAdapterRegistryService
from .exceptions import RETRYABLE_EXCEPTIONS, NON_RETRYABLE_EXCEPTIONS, AdapterConfigError, AdapterNotFoundError

logger = logging.getLogger(__name__)


class OutboundService:
    def __init__(
        self,
        config: dict,
        module_context=None,
        adapter_registry_service: Optional[OutboundAdapterRegistryService] = None,
        redis=None,
    ):
        self.adapter_registry_service = adapter_registry_service
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
        metadata: Optional[dict] = None,
        overrides: Optional[dict] = None,
        content_type: str = "text/plain",
    ) -> dict:
        """
        Send a notification and enqueue async delivery.

        Returns a serialized dict representation of the created outbound record,
        so callers don't need to manually serialize ORM attributes.
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

        resolved_adapter_name = (mapping.default_adapter_name if mapping else None) or self.config.get("CHACC_OUTBOUND_EMAIL_BACKEND", "console")

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
        db.add(outbound_message)
        db.flush()
        db.commit()

        resolved_adapter_name = mapping.default_adapter_name or self.config.get("CHACC_OUTBOUND_EMAIL_BACKEND", "console")

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
                logger.error("Background delivery task failed for %s: %s", outbound_message.uuid, t.exception(), exc_info=t.exception())

        task.add_done_callback(_on_task_done)

        return self._serialize_outbound(outbound_message)

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
        adapter_name: Optional[str] = None,
        overrides: Optional[dict] = None,
        content_type: str = "text/plain",
    ) -> None:
        context = self.module_context
        db = None
        db_gen = None
        try:
            if context:
                db_gen = context.get_db()
                db = await db_gen.__anext__()
            else:
                logger.warning("No module_context available; cannot deliver outbound message %s", messaging_uuid)
                return

            messaging = db.execute(
                select(Outbound).where(Outbound.uuid == messaging_uuid)
            ).scalar_one_or_none()
            if not messaging:
                logger.warning("Outbound message %s not found in database", messaging_uuid)
                return

            mapping = self.get_module_mapping(db, messaging.module_name)
            max_retries = self._apply_overrides(mapping, "max_retry_attempts", 3, overrides)
            backoff = self._apply_overrides(mapping, "retry_backoff_seconds", 300, overrides)

            effective_adapter_name = adapter_name or (mapping.default_adapter_name if mapping else self.config.get("EMAIL_BACKEND", "console")) or "console"
            logger.info("Delivering outbound %s via adapter=%s retries=%s backoff=%s", messaging_uuid, effective_adapter_name, max_retries, backoff)
            try:
                adapter = self.adapter_registry_service.get(
                    channel=messaging.channel,
                    adapter_name=effective_adapter_name,
                )
            except AdapterNotFoundError as e:
                logger.error("Adapter not found for outbound %s: %s", messaging_uuid, e)
                messaging.status = OutboundStatus.FAILED
                messaging.last_error = str(e)
                db.flush()
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
                        logger.info("Adapter reported SENT for outbound %s", messaging_uuid)
                        messaging.status = OutboundStatus.SENT
                        messaging.sent_at = datetime.now(timezone.utc)
                        messaging.attempts = attempt
                        if result.error_message:
                            messaging.last_error = result.error_message
                        db.flush()
                        db.commit()
                        logger.info("Outbound %s marked as SENT in DB", messaging_uuid)
                        return

                    if result.status == "failed":
                        logger.warning("Adapter reported FAILED for outbound %s: %s", messaging_uuid, result.error_message)
                        messaging.status = OutboundStatus.FAILED
                        messaging.last_error = result.error_message or "Adapter reported failure"
                        messaging.attempts = attempt
                        db.flush()
                        db.commit()
                        logger.info("Outbound %s marked as FAILED in DB", messaging_uuid)
                        return

                    last_error = result.error_message or "Unknown error"
                    messaging.status = OutboundStatus.RETRYING
                    messaging.last_error = last_error
                    messaging.attempts = attempt
                    db.flush()
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except AdapterConfigError as e:
                    logger.error("Adapter config error for outbound %s: %s", messaging_uuid, e)
                    messaging.status = OutboundStatus.FAILED
                    messaging.last_error = str(e)
                    messaging.attempts = attempt
                    db.flush()
                    db.commit()
                    return

                except RETRYABLE_EXCEPTIONS as e:
                    last_error = str(e)
                    logger.warning("Retryable error for outbound %s (attempt %s): %s", messaging_uuid, attempt, e)
                    messaging.status = OutboundStatus.RETRYING
                    messaging.last_error = last_error
                    messaging.attempts = attempt
                    db.flush()
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except NON_RETRYABLE_EXCEPTIONS as e:
                    logger.error("Non-retryable error for outbound %s: %s", messaging_uuid, e)
                    messaging.status = OutboundStatus.FAILED
                    messaging.last_error = str(e)
                    messaging.attempts = attempt
                    db.flush()
                    db.commit()
                    return

            logger.warning("Outbound %s failed after %s retries", messaging_uuid, max_retries)
            messaging.status = OutboundStatus.FAILED
            messaging.last_error = last_error or "Max retries exceeded"
            db.flush()
            db.commit()

        except Exception as e:
            logger.error("Outbound delivery failed for %s: %s", messaging_uuid, e, exc_info=True)
            if db:
                try:
                    messaging = db.execute(
                        select(Outbound).where(Outbound.uuid == messaging_uuid)
                    ).scalar_one_or_none()
                    if messaging:
                        messaging.status = OutboundStatus.FAILED
                        messaging.last_error = str(e)
                        db.flush()
                        db.commit()
                except Exception as inner_e:
                    logger.error("Failed to mark outbound %s as FAILED: %s", messaging_uuid, inner_e, exc_info=True)
        finally:
            if db_gen is not None:
                try:
                    await db_gen.aclose()
                except Exception:
                    pass
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def _apply_overrides(
        self,
        mapping: Optional[OutboundModuleMapping],
        key: str,
        default: Optional[int],
        overrides: Optional[dict],
    ) -> Optional[int]:
        if overrides and key in overrides:
            return overrides[key]
        if mapping and hasattr(mapping, key) and getattr(mapping, key) is not None:
            return getattr(mapping, key)
        return default

    def get_message(self, db, outbound_messaging_uuid: str) -> Optional[Outbound]:
        result = db.execute(
            select(Outbound).where(Outbound.uuid == outbound_messaging_uuid)
        )
        return result.scalar_one_or_none()

    def get_status(self, db, outbound_messaging_uuid: str) -> Optional[str]:
        message = self.get_message(db, outbound_messaging_uuid)
        if message:
            status = message.status
            if hasattr(status, "value"):
                return status.value
            return str(status)
        return None

    def get_module_mapping(self, db, module_name: str) -> Optional[OutboundModuleMapping]:
        result = db.execute(
            select(OutboundModuleMapping).where(
                OutboundModuleMapping.module_name == module_name
            )
        )
        return result.scalar_one_or_none()

    def _create_or_update_module_mapping(
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
    ) -> OutboundModuleMapping:
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
        db.flush()
        return mapping