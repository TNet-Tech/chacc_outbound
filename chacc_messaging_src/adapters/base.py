from abc import ABC, abstractmethod
from typing import Optional

from ..exceptions import AdapterNotFoundError


class SendResult:
    """Result of a send attempt."""

    def __init__(
        self,
        status: str,
        message_id: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.status = status
        self.message_id = message_id
        self.error_message = error_message
        self.metadata = metadata or {}


class BaseMessagingAdapter(ABC):
    """
    Abstract base for messaging adapters.

    Each adapter handles one channel (email, sms, push).
    All use Jinja2 for template variable substitution.
    """

    name: str = "base"
    channel: str = "unknown"

    @abstractmethod
    async def send(
        self,
        messaging_id: str,
        template,
        recipient_id: str,
        recipient_contact: str,
        variables: dict,
        metadata: Optional[dict] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
    ) -> SendResult:
        """Send notification via this adapter's channel."""
        pass

    @abstractmethod
    async def validate_contact(self, contact: str) -> bool:
        """Validate contact is valid for this channel."""
        pass

    async def health_check(self) -> bool:
        """Check if adapter can operate."""
        return True


class MessagingAdapterRegistry:
    """Manages registered adapters by channel."""

    def __init__(self):
        self._adapters: dict = {}
        self._defaults: dict = {}

    def register(
        self,
        adapter: BaseMessagingAdapter,
        channel: str,
        name: Optional[str] = None,
        set_default: bool = False,
    ):
        """Register adapter for a channel."""
        adapter_name = name or adapter.name
        key = f"{channel}:{adapter_name}"
        self._adapters[key] = adapter

        if set_default or channel not in self._defaults:
            self._defaults[channel] = adapter_name

    def get(
        self,
        channel: str,
        adapter_name: Optional[str] = None,
    ) -> BaseMessagingAdapter:
        """Get adapter by channel and optional name."""
        name = adapter_name or self._defaults.get(channel)
        if not name:
            raise AdapterNotFoundError(channel, adapter_name)

        key = f"{channel}:{name}"
        if key not in self._adapters:
            raise AdapterNotFoundError(channel, name)

        return self._adapters[key]

    def list_adapters(self) -> dict:
        """List all registered adapters."""
        result = {}
        for key, adapter in self._adapters.items():
            channel, name = key.split(":", 1)
            if channel not in result:
                result[channel] = []
            result[channel].append({"name": name, "class": adapter.__class__.__name__})
        return result

    def get_default(self, channel: str) -> Optional[BaseMessagingAdapter]:
        """Get the default adapter for a channel."""
        name = self._defaults.get(channel)
        if not name:
            return None
        key = f"{channel}:{name}"
        return self._adapters.get(key)
