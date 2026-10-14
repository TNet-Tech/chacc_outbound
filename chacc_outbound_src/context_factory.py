from typing import Optional

from fastapi import HTTPException
from fastapi.params import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .service import OutboundService
from .config import get_outbound_config


_module_context = None

security = HTTPBearer(auto_error=False)


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

async def get_async_db():
    """Get async database session from module context.

    Delegates to the backbone's get_async_db which handles session lifecycle
    (creation, rollback on exception, cleanup).
    """
    context = get_module_context()
    if context is None:
        raise HTTPException(status_code=500, detail="Module not initialized")
    
    gen = context.get_db_async()
    db = await anext(gen)
    try:
        yield db
    finally:
        await gen.aclose()


def get_outbound_service():
    context = get_module_context()
    if context:
        return context.get_service("outbound_service")
    raise RuntimeError("Outbound service not initialized")

async def get_current_user(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    context = get_module_context()

    if context is None:
        return None

    get_current_user_func = context.get_service("get_current_user")

    if get_current_user_func:
        current_user = await get_current_user_func(credentials)
        if not current_user:
            raise HTTPException(status_code=401, detail="User not authenticated")
        return current_user
    
    return None