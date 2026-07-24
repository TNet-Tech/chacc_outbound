from fastapi import APIRouter
from chacc_api import BackboneContext
from typing import Optional

from .routes import router as chacc_outbound_router
from .context_factory import get_context, get_module_context, set_module_context
from .config import get_outbound_config
from .adapters import OutboundAdapterRegistry, ConsoleOutboundAdapter, EmailOutboundAdapter, BaseOutboundAdapter, SendResult
from .service import OutboundService
from .adapter_service import OutboundAdapterRegistryService


health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    context = get_module_context()
    config = get_outbound_config(context)
    backend = config["CHACC_OUTBOUND_EMAIL_BACKEND"]

    return {
        "status": "healthy",
        "module": "chacc_outbound",
        "adapter": backend,
    }


def setup_plugin(context: Optional[BackboneContext] = None):
    _module_context = get_context(context)
    set_module_context(_module_context)

    _module_context.logger.info("chacc_outbound: Setup initiated!")

    config = get_outbound_config(_module_context)

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    smtp_config = {
        "host": config.get("CHACC_OUTBOUND_EMAIL_SMTP_HOST"),
        "port": config.get("CHACC_OUTBOUND_EMAIL_SMTP_PORT"),
        "username": config.get("CHACC_OUTBOUND_EMAIL_SMTP_USERNAME"),
        "password": config.get("CHACC_OUTBOUND_EMAIL_SMTP_PASSWORD"),
        "from_email": config.get("CHACC_OUTBOUND_EMAIL_SMTP_FROM"),
        "use_tls": config.get("CHACC_OUTBOUND_EMAIL_SMTP_USE_TLS", False),
    }
    smtp_adapter = EmailOutboundAdapter(smtp_config=smtp_config if smtp_config["host"] else None)
    registry.register(adapter=smtp_adapter, channel="email", name="smtp")

    adapter_registry_service = OutboundAdapterRegistryService(registry=registry)

    outbound_service = OutboundService(
        config=config,
        module_context=_module_context,
        adapter_registry_service=adapter_registry_service,
    )

    _module_context.register_service("outbound_service", outbound_service)
    _module_context.register_service("outbound_adapter_registry", adapter_registry_service)
    _module_context.register_service("outbound_base_adapter", BaseOutboundAdapter)
    _module_context.register_service("outbound_send_result", SendResult)

    chacc_outbound_router.include_router(health_router)
    return chacc_outbound_router


def get_plugin_info():
    return {
        "name": "chacc_outbound",
        "display_name": "Messaging Module",
        "version": "0.1.0",
        "author": "ChaCC API Team",
        "description": "A ChaCC module providing email and SMS messaging functionality.",
        "status": "enabled",
    }
