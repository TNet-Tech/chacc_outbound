from fastapi import APIRouter
from chacc_api import BackboneContext
from typing import Optional

from .routes import router as chacc_notifications_router
from .context_factory import get_context, set_module_context
from .config import get_notification_config
from .adapters import NotificationAdapterRegistry, ConsoleNotificationAdapter, EmailNotificationAdapter
from .service import NotificationService


health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    context = get_module_context()
    config = get_notification_config(context)
    backend = config["EMAIL_BACKEND"]

    return {
        "status": "healthy",
        "module": "chacc_notifications",
        "adapter": backend,
    }


def setup_plugin(context: Optional[BackboneContext] = None):
    _module_context = get_context(context)
    set_module_context(_module_context)

    _module_context.logger.info("chacc_notifications: Setup initiated!")

    config = get_notification_config(_module_context)

    email_backend = config["EMAIL_BACKEND"]
    adapter_name = email_backend
    if email_backend == "console":
        adapter = ConsoleNotificationAdapter()
    else:
        smtp_config = {
            "host": config["EMAIL_SMTP_HOST"],
            "port": config["EMAIL_SMTP_PORT"],
            "username": config["EMAIL_SMTP_USERNAME"],
            "password": config["EMAIL_SMTP_PASSWORD"],
            "from_email": config["EMAIL_SMTP_FROM"],
        }
        adapter = EmailNotificationAdapter(smtp_config=smtp_config if smtp_config["host"] else None)

    registry = NotificationAdapterRegistry()
    registry.register(adapter=adapter, channel="email", name=adapter_name, set_default=True)

    notification_service = NotificationService(
        adapter_registry=registry,
        config=config,
        module_context=_module_context,
    )

    _module_context.register_service("notification_service", notification_service)

    chacc_notifications_router.include_router(health_router)
    return chacc_notifications_router


def get_plugin_info():
    return {
        "name": "chacc_notifications",
        "display_name": "Notifications Module",
        "version": "0.1.0",
        "author": "ChaCC API Team",
        "description": "A ChaCC module providing notification functionality.",
        "status": "enabled",
    }
