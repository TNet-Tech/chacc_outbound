from .base import BaseMessagingAdapter, SendResult, MessagingAdapterRegistry
from .email import EmailMessagingAdapter
from .console import ConsoleMessagingAdapter

__all__ = [
    "BaseMessagingAdapter",
    "SendResult",
    "MessagingAdapterRegistry",
    "EmailMessagingAdapter",
    "ConsoleMessagingAdapter",
]
