from fastapi import APIRouter
from chacc_api import BackboneContext
from typing import Optional

from .routes import router as chacc_outbound_router
from .context_factory import get_context, get_module_context, set_module_context
from .config import get_outbound_config
from .adapters import OutboundAdapterRegistry, ConsoleOutboundAdapter, EmailOutboundAdapter
from .service import OutboundService


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

    email_backend = config["CHACC_OUTBOUND_EMAIL_BACKEND"]
    adapter_name = email_backend
    if email_backend == "console":
        adapter = ConsoleOutboundAdapter()
    else:
        smtp_config = {
            "host": config["CHACC_OUTBOUND_EMAIL_SMTP_HOST"],
            "port": config["CHACC_OUTBOUND_EMAIL_SMTP_PORT"],
            "username": config["CHACC_OUTBOUND_EMAIL_SMTP_USERNAME"],
            "password": config["CHACC_OUTBOUND_EMAIL_SMTP_PASSWORD"],
            "from_email": config["CHACC_OUTBOUND_EMAIL_SMTP_FROM"],
            "use_tls": config.get("CHACC_OUTBOUND_EMAIL_SMTP_USE_TLS", False),
        }
        adapter = EmailOutboundAdapter(smtp_config=smtp_config if smtp_config["host"] else None)

    registry = OutboundAdapterRegistry()
    registry.register(adapter=adapter, channel="email", name=adapter_name, set_default=True)

    outbound_service = OutboundService(
        adapter_registry=registry,
        config=config,
        module_context=_module_context,
    )

    _module_context.register_service("outbound_service", outbound_service)

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
