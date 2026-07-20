import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from jinja2 import Environment, StrictUndefined

from .models import MessagingTemplate, Messaging, ModuleMessagingMapping, MessagingStatus
from .adapters import MessagingAdapterRegistry
from .exceptions import TemplateNotFoundError, VariableValidationError, AdapterNotFoundError

logger = logging.getLogger(__name__)
jinja_env = Environment(undefined=StrictUndefined)


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
        template_key: str,
        recipient_id: str,
        recipient_contact: str,
        variables: dict,
        module_name: str,
        channel: Optional[str] = None,
        metadata: Optional[dict] = None,
        overrides: Optional[dict] = None,
    ) -> Messaging:
        template = self._get_template_by_key(db, template_key, module_name)
        if not template:
            raise TemplateNotFoundError(template_key)

        self._validate_variables(template, variables)

        effective_channel = channel or template.channel

        mapping = self._get_module_mapping(db, module_name)
        rate_limit = self._apply_overrides(mapping, "rate_limit_per_minute", None, overrides)
        if rate_limit and self.redis:
            key = f"messaging:rate:{module_name}:{effective_channel}"
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, 60)
            if current > rate_limit:
                raise AdapterNotFoundError(effective_channel, f"rate_limit_exceeded:{rate_limit}")

        subject = None
        body = None
        if template.subject_template:
            subject = jinja_env.from_string(template.subject_template).render(**variables)
        body = jinja_env.from_string(template.body_template).render(**variables)

        notification = Messaging(
            template_id=template.id,
            module_name=module_name,
            recipient_id=recipient_id,
            channel=effective_channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            notification_metadata=metadata,
            status=MessagingStatus.PENDING,
        )
        db.add(notification)
        db.flush()

        task = asyncio.create_task(
            self._deliver_async(
                messaging_id=notification.id,
                template=template,
                variables=variables,
                overrides=overrides,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return notification

    async def send_direct(
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
    ) -> Messaging:
        mapping = self._get_module_mapping(db, module_name)
        rate_limit = self._apply_overrides(mapping, "rate_limit_per_minute", None, overrides)
        if rate_limit and self.redis:
            key = f"messaging:rate:{module_name}:{channel}"
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, 60)
            if current > rate_limit:
                raise AdapterNotFoundError(channel, f"rate_limit_exceeded:{rate_limit}")

        notification = Messaging(
            template_id=None,
            module_name=module_name,
            recipient_id=recipient_id,
            channel=channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            notification_metadata=metadata,
            status=MessagingStatus.PENDING,
        )
        db.add(notification)
        db.flush()

        task = asyncio.create_task(
            self._deliver_async(
                messaging_id=notification.id,
                template=None,
                variables=None,
                adapter_name=adapter_name,
                overrides=overrides,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        return notification

    async def _deliver_async(
        self,
        messaging_id: int,
        template: Optional[MessagingTemplate] = None,
        variables: Optional[dict] = None,
        adapter_name: Optional[str] = None,
        overrides: Optional[dict] = None,
    ) -> None:
        context = self.module_context
        db = None
        try:
            if context:
                db = await context.get_db().__anext__()
            else:
                return

            messaging = db.get(Messaging, messaging_id)
            if not messaging:
                return

            mapping = self._get_module_mapping(db, messaging.module_name)
            max_retries = self._apply_overrides(mapping, "max_retry_attempts", 3, overrides)
            backoff = self._apply_overrides(mapping, "retry_backoff_seconds", 300, overrides)

            effective_adapter_name = adapter_name or (template.adapter_name if template else "console")
            adapter = self.adapters.get(
                channel=messaging.channel,
                adapter_name=effective_adapter_name,
            )

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await adapter.send(
                        messaging_id=str(messaging.id),
                        template=template,
                        recipient_id=messaging.recipient_id,
                        recipient_contact=messaging.recipient_contact,
                        variables=variables or {},
                        metadata=messaging.notification_metadata,
                        subject=messaging.subject,
                        body=messaging.body,
                    )

                    if result.status == "sent":
                        messaging.status = MessagingStatus.SENT
                        messaging.sent_at = datetime.utcnow()
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
                    messaging = db.get(Messaging, messaging_id)
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
        default: int,
        overrides: Optional[dict],
    ) -> int:
        if overrides and key in overrides:
            return overrides[key]
        if mapping and hasattr(mapping, key) and getattr(mapping, key) is not None:
            return getattr(mapping, key)
        return default

    async def create_template(
        self,
        db,
        template_key: str,
        module_name: str,
        channel: str,
        adapter_name: str,
        subject_template: Optional[str],
        body_template: str,
        email_type: Optional[str] = None,
        variables_schema: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> MessagingTemplate:
        existing = self._get_template_by_key(db, template_key, module_name)
        if existing:
            raise ValueError(
                f"Template '{template_key}' already exists for module '{module_name}'"
            )

        template = MessagingTemplate(
            template_key=template_key,
            module_name=module_name,
            channel=channel,
            adapter_name=adapter_name,
            subject_template=subject_template,
            body_template=body_template,
            email_type=email_type,
            variables_schema=variables_schema or {},
            description=description,
        )

        db.add(template)
        db.flush()
        return template

    def list_templates(self, db, module_name: Optional[str] = None):
        stmt = select(MessagingTemplate)
        if module_name:
            stmt = stmt.where(MessagingTemplate.module_name == module_name)
        result = db.execute(stmt)
        return result.scalars().all()

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
        default_template_key: Optional[str] = None,
        default_channels: Optional[list] = None,
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
            if default_template_key is not None:
                mapping.default_template_key = default_template_key
            if default_channels is not None:
                mapping.default_channels = default_channels
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
                default_template_key=default_template_key,
                default_channels=default_channels or ["email"],
                max_retry_attempts=max_retry_attempts or 3,
                retry_backoff_seconds=retry_backoff_seconds or 300,
                rate_limit_per_minute=rate_limit_per_minute,
                is_active=is_active if is_active is not None else True,
                description=description,
            )
            db.add(mapping)
        db.flush()
        return mapping

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

    def _get_template(self, db, template_key: str) -> Optional[MessagingTemplate]:
        result = db.execute(
            select(MessagingTemplate).where(
                MessagingTemplate.template_key == template_key,
                MessagingTemplate.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    def _get_template_by_key(
        self, db, template_key: str, module_name: str
    ) -> Optional[MessagingTemplate]:
        result = db.execute(
            select(MessagingTemplate).where(
                MessagingTemplate.template_key == template_key,
                MessagingTemplate.module_name == module_name,
                MessagingTemplate.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    def _validate_variables(self, template: MessagingTemplate, variables: dict) -> None:
        schema = template.variables_schema or {}

        for var_name, var_spec in schema.items():
            if var_spec.get("required", False) and var_name not in variables:
                raise VariableValidationError(f"Missing required variable: {var_name}")

        for var_name in variables:
            if var_name not in schema:
                logger.warning(f"Unknown variable in template: {var_name}")
