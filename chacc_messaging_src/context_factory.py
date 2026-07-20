from functools import lru_cache
from typing import Optional

from .service import MessagingService


_module_context = None


def get_context(context=None):
    global _module_context
    if context:
        _module_context = context
    return _module_context


def set_module_context(context):
    global _module_context
    _module_context = context


def get_module_context():
    return _module_context


@lru_cache()
def get_messaging_config(module_context) -> dict:
    if module_context is None:
        return {
            "ENVIRONMENT": "development",
            "EMAIL_BACKEND": "console",
            "EMAIL_SMTP_HOST": "",
            "EMAIL_SMTP_PORT": 587,
            "EMAIL_SMTP_USERNAME": "",
            "EMAIL_SMTP_PASSWORD": "",
            "EMAIL_SMTP_FROM": "noreply@example.com",
        }

    return {
        "ENVIRONMENT": module_context.get_module_config("ENVIRONMENT", "chacc_messaging", default="development"),
        "EMAIL_BACKEND": module_context.get_module_config("EMAIL_BACKEND", "chacc_messaging", default="console"),
        "EMAIL_SMTP_HOST": module_context.get_module_config("EMAIL_SMTP_HOST", "chacc_messaging", default=""),
        "EMAIL_SMTP_PORT": int(module_context.get_module_config("EMAIL_SMTP_PORT", "chacc_messaging", default="587")),
        "EMAIL_SMTP_USERNAME": module_context.get_module_config("EMAIL_SMTP_USERNAME", "chacc_messaging", default=""),
        "EMAIL_SMTP_PASSWORD": module_context.get_module_config("EMAIL_SMTP_PASSWORD", "chacc_messaging", default=""),
        "EMAIL_SMTP_FROM": module_context.get_module_config("EMAIL_SMTP_FROM", "chacc_messaging", default="noreply@example.com"),
    }


async def get_db():
    context = get_module_context()
    if context and hasattr(context, "get_db"):
        async for db in context.get_db():
            yield db
    else:
        raise RuntimeError("Database not available")


def get_messaging_service():
    context = get_module_context()
    if context:
        return context.get_service("messaging_service")
    raise RuntimeError("Messaging service not initialized")
