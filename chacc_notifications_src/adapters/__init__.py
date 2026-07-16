from .base import BaseNotificationAdapter, SendResult, NotificationAdapterRegistry
from .email import EmailNotificationAdapter
from .console import ConsoleNotificationAdapter

__all__ = [
    "BaseNotificationAdapter",
    "SendResult",
    "NotificationAdapterRegistry",
    "EmailNotificationAdapter",
    "ConsoleNotificationAdapter",
]
