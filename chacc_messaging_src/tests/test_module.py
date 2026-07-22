"""
Tests for chacc_messaging module.
"""
import pytest
import asyncio
import sys
import os

from ..models import Messaging, ModuleMessagingMapping, MessagingStatus
from ..exceptions import AdapterNotFoundError
from ..config import get_messaging_config
from ..adapters import ConsoleMessagingAdapter, EmailMessagingAdapter, MessagingAdapterRegistry


def test_models_import():
    assert Messaging is not None
    assert ModuleMessagingMapping is not None
    assert MessagingStatus is not None


def test_messaging_status_enum():
    assert MessagingStatus.PENDING == "PENDING"
    assert MessagingStatus.SENT == "SENT"
    assert MessagingStatus.FAILED == "FAILED"
    assert MessagingStatus.RETRYING == "RETRYING"


def test_messaging_creation():
    messaging = Messaging(
        module_name="order_service",
        recipient_id="user_123",
        channel="email",
        recipient_contact="user@example.com",
        body="Order shipped",
        status=MessagingStatus.PENDING,
    )
    assert messaging.recipient_id == "user_123"
    assert messaging.channel == "email"
    assert messaging.status == MessagingStatus.PENDING


def test_module_messaging_mapping_creation():
    mapping = ModuleMessagingMapping(
        module_name="order_service",
        max_retry_attempts=3,
        retry_backoff_seconds=300,
    )
    assert mapping.module_name == "order_service"
    assert mapping.max_retry_attempts == 3


def test_module_messaging_mapping_defaults():
    mapping = ModuleMessagingMapping(
        module_name="order_service",
    )
    assert mapping.module_name == "order_service"
    assert mapping.default_adapter_name == "console"
    assert mapping.default_channel == "email"
    assert mapping.max_retry_attempts == 3
    assert mapping.retry_backoff_seconds == 300
    assert mapping.rate_limit_per_minute is None
    assert mapping.is_active is True


def test_exceptions_exist():
    assert AdapterNotFoundError is not None


def test_router_exists():
    from ..routes import router
    assert router is not None
    assert hasattr(router, "routes")


def test_get_messaging_config_without_context():
    config = get_messaging_config(None)
    assert config["EMAIL_BACKEND"] == "console"
    assert config["EMAIL_SMTP_HOST"] == ""
    assert config["EMAIL_SMTP_PORT"] == 587
    assert config["EMAIL_SMTP_FROM"] == "noreply@example.com"


def test_get_messaging_config_with_context():
    class MockContext:
        def get_module_config(self, key, module_name, default=None):
            mapping = {
                "ENVIRONMENT": "production",
                "EMAIL_BACKEND": "smtp",
                "EMAIL_SMTP_HOST": "smtp.example.com",
                "EMAIL_SMTP_PORT": "465",
                "EMAIL_SMTP_USERNAME": "user",
                "EMAIL_SMTP_PASSWORD": "pass",
                "EMAIL_SMTP_FROM": "alerts@example.com",
            }
            return mapping.get(key, default)

    config = get_messaging_config(MockContext())
    assert config["ENVIRONMENT"] == "production"
    assert config["EMAIL_BACKEND"] == "smtp"
    assert config["EMAIL_SMTP_HOST"] == "smtp.example.com"
    assert config["EMAIL_SMTP_PORT"] == 465
    assert config["EMAIL_SMTP_USERNAME"] == "user"
    assert config["EMAIL_SMTP_PASSWORD"] == "pass"
    assert config["EMAIL_SMTP_FROM"] == "alerts@example.com"


def test_console_adapter_send_direct():
    adapter = ConsoleMessagingAdapter()
    result = asyncio.run(
        adapter.send(
            messaging_uuid="test-uuid-1",
            recipient_id="user_123",
            recipient_contact="user@example.com",
            subject="Direct subject",
            body="Direct body",
            content_type="text/plain",
        )
    )
    assert result.status == "sent"
    assert result.message_id == "console_test-uuid-1"


def test_email_adapter_validate_contact():
    adapter = EmailMessagingAdapter(smtp_config=None)
    assert asyncio.run(adapter.validate_contact("user@example.com")) is True
    assert asyncio.run(adapter.validate_contact("invalid")) is False


def test_email_adapter_send_console_backend_html():
    adapter = EmailMessagingAdapter(smtp_config=None)
    result = asyncio.run(
        adapter.send(
            messaging_uuid="test-uuid-2",
            recipient_id="user_123",
            recipient_contact="user@example.com",
            subject="Test",
            body="<h1>Hello</h1>",
            content_type="html",
        )
    )
    assert result.status == "sent"
    assert result.message_id.startswith("console_")


def test_email_adapter_send_console_backend_text():
    adapter = EmailMessagingAdapter(smtp_config=None)
    result = asyncio.run(
        adapter.send(
            messaging_uuid="test-uuid-3",
            recipient_id="user_123",
            recipient_contact="user@example.com",
            subject="Test",
            body="Plain text",
            content_type="text/plain",
        )
    )
    assert result.status == "sent"
    assert result.message_id.startswith("console_")


def test_messaging_adapter_registry_register_and_get():
    registry = MessagingAdapterRegistry()
    adapter = ConsoleMessagingAdapter()
    registry.register(adapter=adapter, channel="email", name="console", set_default=True)
    retrieved = registry.get(channel="email", adapter_name="console")
    assert retrieved is adapter


def test_messaging_adapter_registry_default():
    registry = MessagingAdapterRegistry()
    adapter = ConsoleMessagingAdapter()
    registry.register(adapter=adapter, channel="email", name="console", set_default=True)
    default = registry.get_default("email")
    assert default is adapter


def test_messaging_adapter_registry_list():
    registry = MessagingAdapterRegistry()
    registry.register(adapter=ConsoleMessagingAdapter(), channel="email", name="console", set_default=True)
    registry.register(adapter=EmailMessagingAdapter(smtp_config=None), channel="email", name="smtp")
    adapters = registry.list_adapters()
    assert "email" in adapters
    assert len(adapters["email"]) == 2


def test_messaging_adapter_registry_missing():
    registry = MessagingAdapterRegistry()
    try:
        registry.get(channel="sms")
        assert False, "Expected AdapterNotFoundError"
    except AdapterNotFoundError:
        pass


def test_service_send_creates_notification():
    from ..service import MessagingService
    from ..adapters import MessagingAdapterRegistry
    from unittest.mock import MagicMock

    registry = MessagingAdapterRegistry()
    registry.register(adapter=ConsoleMessagingAdapter(), channel="email", name="console", set_default=True)

    mock_context = MagicMock()
    mock_context.get_db.return_value.__aiter__ = lambda self: self
    mock_context.get_db.return_value.__anext__ = MagicMock(side_effect=StopAsyncIteration)

    service = MessagingService(
        adapter_registry=registry,
        config=get_messaging_config(None),
        module_context=mock_context,
    )

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = MagicMock()

    notification = asyncio.run(
        service.send(
            db=mock_db,
            recipient_id="user_123",
            recipient_contact="user@example.com",
            body="Direct body",
            module_name="order_service",
            subject="Direct subject",
            channel="email",
            adapter_name="console",
            content_type="text/plain",
        )
    )
    assert notification.module_name == "order_service"
    assert notification.recipient_id == "user_123"
    assert notification.channel == "email"
    assert notification.subject == "Direct subject"
    assert notification.body == "Direct body"


def test_service_rate_limit_without_redis():
    from ..service import MessagingService
    from ..adapters import MessagingAdapterRegistry
    from unittest.mock import MagicMock

    registry = MessagingAdapterRegistry()
    registry.register(adapter=ConsoleMessagingAdapter(), channel="email", name="console", set_default=True)

    service = MessagingService(
        adapter_registry=registry,
        config=get_messaging_config(None),
        module_context=MagicMock(),
        redis=None,
    )

    mock_db = MagicMock()
    mapping = ModuleMessagingMapping(
        module_name="order_service",
        rate_limit_per_minute=10,
    )
    assert service._apply_overrides(mapping, "rate_limit_per_minute", None, None) == 10


def run_module_tests():
    import subprocess
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_root = os.path.dirname(tests_dir)
    venv_python = os.path.join(plugin_root, "..", ".venv", "bin", "python")
    python = str(venv_python if os.path.exists(venv_python) else sys.executable)
    result = subprocess.run(
        [python, "-m", "pytest", tests_dir, "-v", "--tb=short"],
        cwd=tests_dir,
        env={**os.environ, "PYTHONPATH": plugin_root},
    )
    if result.returncode == 0:
        return {"status": "passed", "message": "All tests passed"}
    return {"status": "failed", "message": "Tests failed", "details": result.stdout + result.stderr}