"""
Tests for chacc_outbound module.
"""
import pytest
import asyncio
import sys
import os

from ..models import Outbound, OutboundModuleMapping, OutboundStatus
from ..exceptions import AdapterConfigError, AdapterNotFoundError
from ..config import get_outbound_config
from ..adapters import ConsoleOutboundAdapter, EmailOutboundAdapter, OutboundAdapterRegistry


def test_models_import():
    assert Outbound is not None
    assert OutboundModuleMapping is not None
    assert OutboundStatus is not None


def test_messaging_status_enum():
    assert OutboundStatus.PENDING == "PENDING"
    assert OutboundStatus.SENT == "SENT"
    assert OutboundStatus.FAILED == "FAILED"
    assert OutboundStatus.RETRYING == "RETRYING"


def test_messaging_creation():
    messaging = Outbound(
        module_name="order_service",
        recipient_id="user_123",
        channel="email",
        recipient_contact="user@example.com",
        body="Order shipped",
        status=OutboundStatus.PENDING,
    )
    assert messaging.recipient_id == "user_123"
    assert messaging.channel == "email"
    assert messaging.status == OutboundStatus.PENDING


def test_module_messaging_mapping_creation():
    mapping = OutboundModuleMapping(
        module_name="order_service",
        max_retry_attempts=3,
        retry_backoff_seconds=300,
    )
    assert mapping.module_name == "order_service"
    assert mapping.max_retry_attempts == 3


def test_module_messaging_mapping_defaults():
    mapping = OutboundModuleMapping(
        module_name="order_service",
    )
    assert mapping.module_name == "order_service"
    assert mapping.rate_limit_per_minute is None


def test_exceptions_exist():
    assert AdapterNotFoundError is not None


def test_router_exists():
    from ..routes import router
    assert router is not None
    assert hasattr(router, "routes")


def test_get_messaging_config_without_context():
    config = get_outbound_config(None)
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

    config = get_outbound_config(MockContext())
    assert config["ENVIRONMENT"] == "production"
    assert config["EMAIL_BACKEND"] == "smtp"
    assert config["EMAIL_SMTP_HOST"] == "smtp.example.com"
    assert config["EMAIL_SMTP_PORT"] == 465
    assert config["EMAIL_SMTP_USERNAME"] == "user"
    assert config["EMAIL_SMTP_PASSWORD"] == "pass"
    assert config["EMAIL_SMTP_FROM"] == "alerts@example.com"


def test_console_adapter_send_direct():
    adapter = ConsoleOutboundAdapter()
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
    adapter = EmailOutboundAdapter(smtp_config=None)
    assert asyncio.run(adapter.validate_contact("user@example.com")) is True
    assert asyncio.run(adapter.validate_contact("invalid")) is False


def test_email_adapter_send_requires_smtp_config():
    adapter = EmailOutboundAdapter(smtp_config=None)
    with pytest.raises(AdapterConfigError, match="SMTP configuration is missing"):
        asyncio.run(
            adapter.send(
                messaging_uuid="test-uuid-2",
                recipient_id="user_123",
                recipient_contact="user@example.com",
                subject="Test",
                body="<h1>Hello</h1>",
                content_type="html",
            )
        )


def test_email_adapter_send_invalid_contact():
    adapter = EmailOutboundAdapter(smtp_config={"host": "smtp.example.com", "port": 587})
    with pytest.raises(ValueError, match="Invalid email address"):
        asyncio.run(
            adapter.send(
                messaging_uuid="test-uuid-3",
                recipient_id="user_123",
                recipient_contact="invalid",
                subject="Test",
                body="Plain text",
                content_type="text/plain",
            )
        )


def test_email_adapter_send_smtp():
    adapter = EmailOutboundAdapter(
        smtp_config={
            "host": "smtp.example.com",
            "port": 587,
            "username": "user",
            "password": "pass",
            "from_email": "alerts@example.com",
        }
    )
    async def _mock_send_email(**kwargs):
        return None
    adapter._send_email = _mock_send_email
    result = asyncio.run(
        adapter.send(
            messaging_uuid="test-uuid-4",
            recipient_id="user_123",
            recipient_contact="user@example.com",
            subject="Test",
            body="Plain text",
            content_type="text/plain",
        )
    )
    assert result.status == "sent"
    assert result.message_id == "smtp_test-uuid-4"


def test_messaging_adapter_registry_register_and_get():
    registry = OutboundAdapterRegistry()
    adapter = ConsoleOutboundAdapter()
    registry.register(adapter=adapter, channel="email", name="console", set_default=True)
    retrieved = registry.get(channel="email", adapter_name="console")
    assert retrieved is adapter


def test_messaging_adapter_registry_default():
    registry = OutboundAdapterRegistry()
    adapter = ConsoleOutboundAdapter()
    registry.register(adapter=adapter, channel="email", name="console", set_default=True)
    default = registry.get_default("email")
    assert default is adapter


def test_messaging_adapter_registry_list():
    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)
    registry.register(adapter=EmailOutboundAdapter(smtp_config=None), channel="email", name="smtp")
    adapters = registry.list_adapters()
    assert "email" in adapters
    assert len(adapters["email"]) == 2


def test_messaging_adapter_registry_missing():
    registry = OutboundAdapterRegistry()
    try:
        registry.get(channel="sms")
        assert False, "Expected AdapterNotFoundError"
    except AdapterNotFoundError:
        pass


def test_service_send_returns_serialized_dict():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry
    from unittest.mock import MagicMock

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    mock_context = MagicMock()
    mock_context.get_db.return_value.__aiter__ = lambda self: self
    mock_context.get_db.return_value.__anext__ = MagicMock(side_effect=StopAsyncIteration)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=mock_context,
    )

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.flush = MagicMock()

    result = asyncio.run(
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
    assert isinstance(result, dict)
    assert result["module_name"] == "order_service"
    assert result["recipient_id"] == "user_123"
    assert result["channel"] == "email"
    assert result["subject"] == "Direct subject"
    assert result["body"] == "Direct body"
    assert result["status"] == "PENDING"
    assert result["outbound_metadata"] is None
    assert result["sent_at"] is None
    assert result["attempts"] == 0
    assert result["last_error"] is None


def test_service_rate_limit_without_redis():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry
    from unittest.mock import MagicMock

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=MagicMock(),
        redis=None,
    )

    mock_db = MagicMock()
    mapping = OutboundModuleMapping(
        module_name="order_service",
        rate_limit_per_minute=10,
    )
    assert service._apply_overrides(mapping, "rate_limit_per_minute", None, None) == 10


def test_service_get_status_returns_status():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry
    from unittest.mock import MagicMock

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=MagicMock(),
    )

    mock_db = MagicMock()
    mock_notification = MagicMock()
    mock_notification.status = "SENT"
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_notification

    status = service.get_status(mock_db, "test-uuid")
    assert status == "SENT"


def test_service_get_status_returns_none_when_not_found():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry
    from unittest.mock import MagicMock

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=MagicMock(),
    )

    mock_db = MagicMock()
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    status = service.get_status(mock_db, "missing-uuid")
    assert status is None


def test_service_get_status_failed():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry
    from unittest.mock import MagicMock

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConsoleOutboundAdapter(), channel="email", name="console", set_default=True)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=MagicMock(),
    )

    mock_db = MagicMock()
    mock_notification = MagicMock()
    mock_notification.status = "FAILED"
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_notification

    status = service.get_status(mock_db, "test-uuid")
    assert status == "FAILED"


def test_service_adapter_config_error_skips_retry():
    from ..service import OutboundService
    from ..adapters import OutboundAdapterRegistry, BaseOutboundAdapter, SendResult
    from unittest.mock import MagicMock, AsyncMock

    class ConfigErrorAdapter(BaseOutboundAdapter):
        name = "smtp"
        channel = "email"

        async def send(self, *args, **kwargs):
            raise AdapterConfigError(adapter_name="smtp", reason="Missing host")

        async def validate_contact(self, contact: str) -> bool:
            return True

    registry = OutboundAdapterRegistry()
    registry.register(adapter=ConfigErrorAdapter(), channel="email", name="smtp", set_default=True)

    class _AsyncDBIter:
        def __init__(self, db):
            self._db = db
            self._done = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._done:
                self._done = True
                return self._db
            raise StopAsyncIteration

    mock_context = MagicMock()
    mock_db = MagicMock()
    mock_context.get_db.return_value = _AsyncDBIter(mock_db)

    service = OutboundService(
        adapter_registry=registry,
        config=get_outbound_config(None),
        module_context=mock_context,
    )

    mock_outbound = MagicMock()
    mock_outbound.uuid = "test-uuid"
    mock_outbound.module_name = "order_service"
    mock_outbound.channel = "email"
    mock_outbound.recipient_id = "user_1"
    mock_outbound.recipient_contact = "user@example.com"
    mock_outbound.subject = "Test"
    mock_outbound.body = "Body"
    mock_outbound.messaging_metadata = None
    mock_outbound.status = "PENDING"
    mock_outbound.attempts = 0
    mock_outbound.last_error = None

    mock_mapping = MagicMock()
    mock_mapping.default_adapter_name = "console"
    mock_mapping.max_retry_attempts = 3
    mock_mapping.retry_backoff_seconds = 300

    mock_db.execute.return_value.scalar_one_or_none.side_effect = [mock_outbound, mock_mapping]

    asyncio.run(
        service._deliver_async(
            messaging_uuid="test-uuid",
            adapter_name="smtp",
            overrides=None,
            content_type="text/plain",
        )
    )

    assert mock_outbound.status == OutboundStatus.FAILED
    assert mock_outbound.attempts == 1
    assert "Missing host" in mock_outbound.last_error


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