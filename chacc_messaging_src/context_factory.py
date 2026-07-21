from typing import Optional

from .service import MessagingService
from .config import get_messaging_config


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
