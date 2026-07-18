import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from jinja2 import Environment, StrictUndefined

from .models import NotificationTemplate, Notification, ModuleNotificationMapping, NotificationStatus
from .adapters import NotificationAdapterRegistry
from .exceptions import TemplateNotFoundError, VariableValidationError, AdapterNotFoundError

logger = logging.getLogger(__name__)
jinja_env = Environment(undefined=StrictUndefined)


class NotificationService:
    def __init__(
        self,
        adapter_registry: NotificationAdapterRegistry,
        config: dict,
        module_context=None,
    ):
        self.adapters = adapter_registry
        self.config = config
        self.module_context = module_context
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
    ) -> Notification:
        template = self._get_template_by_key(db, template_key, module_name)
        if not template:
            raise TemplateNotFoundError(template_key)

        self._validate_variables(template, variables)

        effective_channel = channel or template.channel

        subject = None
        body = None
        if template.subject_template:
            subject = jinja_env.from_string(template.subject_template).render(**variables)
        body = jinja_env.from_string(template.body_template).render(**variables)

        notification = Notification(
            template_id=template.id,
            module_name=module_name,
            recipient_id=recipient_id,
            channel=effective_channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            notification_metadata=metadata,
            status=NotificationStatus.PENDING,
        )
        db.add(notification)
        db.flush()

        task = asyncio.create_task(
            self._deliver_async(
                notification_id=notification.id,
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
    ) -> Notification:
        notification = Notification(
            template_id=None,
            module_name=module_name,
            recipient_id=recipient_id,
            channel=channel,
            recipient_contact=recipient_contact,
            subject=subject,
            body=body,
            notification_metadata=metadata,
            status=NotificationStatus.PENDING,
        )
        db.add(notification)
        db.flush()

        task = asyncio.create_task(
            self._deliver_async(
                notification_id=notification.id,
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
        notification_id: int,
        template: Optional[NotificationTemplate] = None,
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

            notification = db.get(Notification, notification_id)
            if not notification:
                return

            mapping = self._get_module_mapping(db, notification.module_name)
            max_retries = self._apply_overrides(mapping, "max_retry_attempts", 3, overrides)
            backoff = self._apply_overrides(mapping, "retry_backoff_seconds", 300, overrides)

            effective_adapter_name = adapter_name or (template.adapter_name if template else "console")
            adapter = self.adapters.get(
                channel=notification.channel,
                adapter_name=effective_adapter_name,
            )

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await adapter.send(
                        notification_id=str(notification.id),
                        template=template,
                        recipient_id=notification.recipient_id,
                        recipient_contact=notification.recipient_contact,
                        variables=variables or {},
                        metadata=notification.notification_metadata,
                        subject=notification.subject,
                        body=notification.body,
                    )

                    if result.status == "sent":
                        notification.status = NotificationStatus.SENT
                        notification.sent_at = datetime.utcnow()
                        notification.attempts = attempt
                        if result.error_message:
                            notification.last_error = result.error_message
                        db.commit()
                        return

                    last_error = result.error_message or "Unknown error"
                    notification.status = NotificationStatus.RETRYING
                    notification.last_error = last_error
                    notification.attempts = attempt
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

                except Exception as e:
                    last_error = str(e)
                    notification.status = NotificationStatus.RETRYING
                    notification.last_error = last_error
                    notification.attempts = attempt
                    db.commit()

                    if attempt < max_retries:
                        await asyncio.sleep(backoff)
                        backoff = backoff * 2

            notification.status = NotificationStatus.FAILED
            notification.last_error = last_error or "Max retries exceeded"
            db.commit()

        except Exception as e:
            if db:
                try:
                    notification = db.get(Notification, notification_id)
                    if notification:
                        notification.status = NotificationStatus.FAILED
                        notification.last_error = str(e)
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
        mapping: Optional[ModuleNotificationMapping],
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
    ) -> NotificationTemplate:
        existing = self._get_template_by_key(db, template_key, module_name)
        if existing:
            raise ValueError(
                f"Template '{template_key}' already exists for module '{module_name}'"
            )

        template = NotificationTemplate(
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
        stmt = select(NotificationTemplate)
        if module_name:
            stmt = stmt.where(NotificationTemplate.module_name == module_name)
        result = db.execute(stmt)
        return result.scalars().all()

    def get_module_mapping(self, db, module_name: str) -> Optional[ModuleNotificationMapping]:
        result = db.execute(
            select(ModuleNotificationMapping).where(
                ModuleNotificationMapping.module_name == module_name
            )
        )
        return result.scalar_one_or_none()

    def create_or_update_module_mapping(
        self,
        db,
        module_name: str,
        default_channels: Optional[list] = None,
        max_retry_attempts: Optional[int] = None,
        retry_backoff_seconds: Optional[int] = None,
        description: Optional[str] = None,
    ) -> ModuleNotificationMapping:
        mapping = self.get_module_mapping(db, module_name)
        if mapping:
            if default_channels is not None:
                mapping.default_channels = default_channels
            if max_retry_attempts is not None:
                mapping.max_retry_attempts = max_retry_attempts
            if retry_backoff_seconds is not None:
                mapping.retry_backoff_seconds = retry_backoff_seconds
            if description is not None:
                mapping.description = description
        else:
            mapping = ModuleNotificationMapping(
                module_name=module_name,
                default_channels=default_channels or ["email"],
                max_retry_attempts=max_retry_attempts or 3,
                retry_backoff_seconds=retry_backoff_seconds or 300,
                description=description,
            )
            db.add(mapping)
        db.flush()
        return mapping

    def get_notification(self, db, notification_uuid: str) -> Optional[Notification]:
        result = db.execute(
            select(Notification).where(Notification.uuid == notification_uuid)
        )
        return result.scalar_one_or_none()

    async def get_status(self, db, notification_uuid: str) -> Optional[NotificationStatus]:
        notification = self.get_notification(db, notification_uuid)
        if notification:
            return notification.status
        return None

    def _get_template(self, db, template_key: str) -> Optional[NotificationTemplate]:
        result = db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.template_key == template_key,
                NotificationTemplate.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    def _get_template_by_key(
        self, db, template_key: str, module_name: str
    ) -> Optional[NotificationTemplate]:
        result = db.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.template_key == template_key,
                NotificationTemplate.module_name == module_name,
                NotificationTemplate.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    def _validate_variables(self, template: NotificationTemplate, variables: dict) -> None:
        schema = template.variables_schema or {}

        for var_name, var_spec in schema.items():
            if var_spec.get("required", False) and var_name not in variables:
                raise VariableValidationError(f"Missing required variable: {var_name}")

        for var_name in variables:
            if var_name not in schema:
                logger.warning(f"Unknown variable in template: {var_name}")
