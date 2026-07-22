from .base import BaseOutboundAdapter, SendResult, OutboundAdapterRegistry
from .email import EmailOutboundAdapter
from .console import ConsoleOutboundAdapter

__all__ = [
    "BaseOutboundAdapter",
    "SendResult",
    "OutboundAdapterRegistry",
    "EmailOutboundAdapter",
    "ConsoleOutboundAdapter",
]
