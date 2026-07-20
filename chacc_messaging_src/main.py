from fastapi import APIRouter
from chacc_api import BackboneContext
from typing import Optional

from .routes import router as chacc_messaging_router
from .context_factory import get_context, set_module_context
from .config import get_messaging_config
from .adapters import MessagingAdapterRegistry, ConsoleMessagingAdapter, EmailMessagingAdapter
from .service import MessagingService


health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    context = get_module_context()
    config = get_messaging_config(context)
    backend = config["EMAIL_BACKEND"]

    return {
        "status": "healthy",
        "module": "chacc_messaging",
        "adapter": backend,
    }


def setup_plugin(context: Optional[BackboneContext] = None):
    _module_context = get_context(context)
    set_module_context(_module_context)

    _module_context.logger.info("chacc_messaging: Setup initiated!")

    config = get_messaging_config(_module_context)

    email_backend = config["EMAIL_BACKEND"]
    adapter_name = email_backend
    if email_backend == "console":
        adapter = ConsoleMessagingAdapter()
    else:
        smtp_config = {
            "host": config["EMAIL_SMTP_HOST"],
            "port": config["EMAIL_SMTP_PORT"],
            "username": config["EMAIL_SMTP_USERNAME"],
            "password": config["EMAIL_SMTP_PASSWORD"],
            "from_email": config["EMAIL_SMTP_FROM"],
        }
        adapter = EmailMessagingAdapter(smtp_config=smtp_config if smtp_config["host"] else None)

    registry = MessagingAdapterRegistry()
    registry.register(adapter=adapter, channel="email", name=adapter_name, set_default=True)

    messaging_service = MessagingService(
        adapter_registry=registry,
        config=config,
        module_context=_module_context,
    )

    _module_context.register_service("messaging_service", messaging_service)

    chacc_messaging_router.include_router(health_router)
    return chacc_messaging_router


def get_plugin_info():
    return {
        "name": "chacc_messaging",
        "display_name": "Messaging Module",
        "version": "0.1.0",
        "author": "ChaCC API Team",
        "description": "A ChaCC module providing email and SMS messaging functionality.",
        "status": "enabled",
    }
