"""
Tests for chacc_outbound module.
"""

import asyncio
import os
import sys

import pytest

from ..adapters import (
    ConsoleOutboundAdapter,
    EmailOutboundAdapter,
    OutboundAdapterRegistry,
)
from ..config import get_outbound_config
from ..exceptions import AdapterConfigError, AdapterNotFoundError
from ..models import Outbound, OutboundModuleMapping, OutboundStatus


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
                "EMAIL_BACKEND": "smtp",
                "EMAIL_SMTP_HOST": "smtp.example.com",
                "EMAIL_SMTP_PORT": "465",
                "EMAIL_SMTP_USERNAME": "user",
                "EMAIL_SMTP_PASSWORD": "pass",
                "EMAIL_SMTP_FROM": "alerts@example.com",
            }
            return mapping.get(key, default)

    config = get_outbound_config(MockContext())
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
    adapter = EmailOutboundAdapter(
        smtp_config={"host": "smtp.example.com", "port": 587}
    )
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
    registry.register(
        adapter=adapter, channel="email", name="console", set_default=True
    )
    retrieved = registry.get(channel="email", adapter_name="console")
    assert retrieved is adapter


def test_messaging_adapter_registry_default():
    registry = OutboundAdapterRegistry()
    adapter = ConsoleOutboundAdapter()
    registry.register(
        adapter=adapter, channel="email", name="console", set_default=True
    )
    default = registry.get_default("email")
    assert default is adapter


def test_messaging_adapter_registry_list():
    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )
    registry.register(
        adapter=EmailOutboundAdapter(smtp_config=None), channel="email", name="smtp"
    )
    adapters = registry.list_adapters()
    assert len(adapters) == 2
    assert {
        "name": "console",
        "channel": "email",
        "description": "Prints messages to the console for local testing",
    } in adapters
    assert {
        "name": "smtp",
        "channel": "email",
        "description": "Sends real emails via SMTP",
    } in adapters


def test_messaging_adapter_registry_missing():
    registry = OutboundAdapterRegistry()
    try:
        registry.get(channel="sms")
        assert False, "Expected AdapterNotFoundError"
    except AdapterNotFoundError:
        pass


def test_service_send_returns_serialized_dict():
    from unittest.mock import AsyncMock, MagicMock

    from ..adapters import OutboundAdapterRegistry
    from ..service import OutboundService

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )

    mock_context = MagicMock()
    service = OutboundService(
        config=get_outbound_config(None),
        module_context=mock_context,
        adapter_registry_service=MagicMock(),
    )
    service._deliver_async = AsyncMock()

    async_db = MagicMock()
    async_db.add = MagicMock()
    async_db.flush = AsyncMock()
    async_db.commit = AsyncMock()
    async_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    async def get_db_async():
        yield async_db

    mock_context.get_db_async = get_db_async

    result = asyncio.run(
        service.send(
            recipient_id="user_123",
            recipient_contact="user@example.com",
            body="Direct body",
            module_name="order_service",
            subject="Direct subject",
            channel="email",
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
    async_db.execute.assert_awaited_once()
    async_db.add.assert_called_once()
    async_db.flush.assert_awaited_once()
    async_db.commit.assert_awaited_once()


def test_service_rate_limit_without_redis():
    from unittest.mock import MagicMock

    from ..adapters import OutboundAdapterRegistry
    from ..service import OutboundService

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )

    service = OutboundService(
        config=get_outbound_config(None),
        module_context=MagicMock(),
        adapter_registry_service=MagicMock(),
        redis=None,
    )

    mapping = OutboundModuleMapping(
        module_name="order_service",
        rate_limit_per_minute=10,
    )
    assert service._apply_overrides(mapping, "rate_limit_per_minute", None, None) == 10


def test_service_get_status_returns_status():
    from unittest.mock import AsyncMock, MagicMock

    from ..adapters import OutboundAdapterRegistry
    from ..service import OutboundService

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )

    service = OutboundService(
        config=get_outbound_config(None),
        module_context=MagicMock(),
        adapter_registry_service=MagicMock(),
    )

    mock_db = MagicMock()
    mock_notification = MagicMock()
    mock_notification.status = "SENT"
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_notification)
        )
    )

    status = asyncio.run(service.get_status(mock_db, "test-uuid"))
    assert status == "SENT"


def test_service_get_status_returns_none_when_not_found():
    from unittest.mock import AsyncMock, MagicMock

    from ..adapters import OutboundAdapterRegistry
    from ..service import OutboundService

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )

    service = OutboundService(
        config=get_outbound_config(None),
        module_context=MagicMock(),
        adapter_registry_service=MagicMock(),
    )

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    status = asyncio.run(service.get_status(mock_db, "missing-uuid"))
    assert status is None


def test_service_get_status_failed():
    from unittest.mock import AsyncMock, MagicMock

    from ..adapters import OutboundAdapterRegistry
    from ..service import OutboundService

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConsoleOutboundAdapter(),
        channel="email",
        name="console",
        set_default=True,
    )

    service = OutboundService(
        config=get_outbound_config(None),
        module_context=MagicMock(),
        adapter_registry_service=MagicMock(),
    )

    mock_db = MagicMock()
    mock_notification = MagicMock()
    mock_notification.status = "FAILED"
    mock_db.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=mock_notification)
        )
    )

    status = asyncio.run(service.get_status(mock_db, "test-uuid"))
    assert status == "FAILED"


def test_service_adapter_config_error_skips_retry():
    from unittest.mock import AsyncMock, MagicMock

    from ..adapter_service import OutboundAdapterRegistryService
    from ..adapters import BaseOutboundAdapter, OutboundAdapterRegistry
    from ..service import OutboundService

    class ConfigErrorAdapter(BaseOutboundAdapter):
        name = "smtp"
        channel = "email"

        async def send(self, *args, **kwargs):
            raise AdapterConfigError(adapter_name="smtp", reason="Missing host")

        async def validate_contact(self, contact: str) -> bool:
            return True

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=ConfigErrorAdapter(), channel="email", name="smtp", set_default=True
    )
    adapter_registry_service = OutboundAdapterRegistryService(registry=registry)

    mock_context = MagicMock()
    mock_db = MagicMock()

    async def get_db_async():
        yield mock_db

    mock_context.get_db_async = get_db_async

    service = OutboundService(
        config=get_outbound_config(None),
        module_context=mock_context,
        adapter_registry_service=adapter_registry_service,
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

    mock_db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_outbound)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_mapping)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=mock_outbound)),
        ]
    )
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

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


def test_service_delivery_success_uses_short_async_sessions():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from ..adapter_service import OutboundAdapterRegistryService
    from ..service import OutboundService

    active_sessions = 0
    created_sessions = []

    def make_session_generator(db):
        async def generate():
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield db
            finally:
                active_sessions -= 1

        return generate()

    message = MagicMock()
    message.uuid = "message-uuid"
    message.module_name = "menu"
    message.channel = "email"
    message.recipient_id = "user-1"
    message.recipient_contact = "user@example.com"
    message.subject = "Subject"
    message.body = "Body"
    message.messaging_metadata = None
    message.status = OutboundStatus.PENDING
    message.attempts = 0

    def result(value):
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    read_db = MagicMock()
    read_db.execute = AsyncMock(side_effect=[result(message), result(None)])
    read_db.rollback = AsyncMock()

    write_db = MagicMock()
    write_db.execute = AsyncMock(return_value=result(message))
    write_db.flush = AsyncMock()
    write_db.commit = AsyncMock()
    write_db.rollback = AsyncMock()

    context = MagicMock()

    def get_db_async():
        db = read_db if not created_sessions else write_db
        created_sessions.append(db)
        return make_session_generator(db)

    context.get_db_async = get_db_async

    class SessionCheckingAdapter:
        async def send(self, **kwargs):
            assert active_sessions == 0
            return SimpleNamespace(status="sent", error_message=None)

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=SessionCheckingAdapter(),
        channel="email",
        name="test",
        set_default=True,
    )
    service = OutboundService(
        config=get_outbound_config(None),
        module_context=context,
        adapter_registry_service=OutboundAdapterRegistryService(registry),
    )

    asyncio.run(service._deliver_async("message-uuid", adapter_name="test"))

    assert message.status == OutboundStatus.SENT
    assert message.attempts == 1
    assert len(created_sessions) == 2
    assert active_sessions == 0
    write_db.commit.assert_awaited_once()


def test_service_delivery_retries_and_persists_each_transition():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from ..adapter_service import OutboundAdapterRegistryService
    from ..service import OutboundService

    active_sessions = 0
    created_sessions = []

    def make_session_generator(db):
        async def generate():
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield db
            finally:
                active_sessions -= 1

        return generate()

    message = MagicMock()
    message.uuid = "message-uuid"
    message.module_name = "menu"
    message.channel = "email"
    message.recipient_id = "user-1"
    message.recipient_contact = "user@example.com"
    message.subject = "Subject"
    message.body = "Body"
    message.messaging_metadata = None
    message.status = OutboundStatus.PENDING
    message.attempts = 0

    def result(value):
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    read_db = MagicMock()
    read_db.execute = AsyncMock(side_effect=[result(message), result(None)])
    read_db.rollback = AsyncMock()

    write_dbs = []
    for _ in range(3):
        write_db = MagicMock()
        write_db.execute = AsyncMock(return_value=result(message))
        write_db.flush = AsyncMock()
        write_db.commit = AsyncMock()
        write_db.rollback = AsyncMock()
        write_dbs.append(write_db)

    context = MagicMock()

    def get_db_async():
        db = read_db if not created_sessions else write_dbs[len(created_sessions) - 1]
        created_sessions.append(db)
        return make_session_generator(db)

    context.get_db_async = get_db_async

    class RetryAdapter:
        async def send(self, **kwargs):
            assert active_sessions == 0
            return SimpleNamespace(status="retry", error_message="temporary")

    registry = OutboundAdapterRegistry()
    registry.register(
        adapter=RetryAdapter(), channel="email", name="test", set_default=True
    )
    service = OutboundService(
        config=get_outbound_config(None),
        module_context=context,
        adapter_registry_service=OutboundAdapterRegistryService(registry),
    )

    asyncio.run(
        service._deliver_async(
            "message-uuid",
            adapter_name="test",
            overrides={"max_retry_attempts": 2, "retry_backoff_seconds": 0},
        )
    )

    assert message.status == OutboundStatus.FAILED
    assert message.attempts == 2
    assert message.last_error == "temporary"
    assert len(created_sessions) == 4
    assert [db.commit.await_count for db in write_dbs] == [1, 1, 1]
    assert active_sessions == 0


def test_send_with_real_async_session_persists_and_delivers():
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ..adapter_service import OutboundAdapterRegistryService
    from ..service import OutboundService

    async def run_test():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync_connection: Outbound.__table__.create(sync_connection)
            )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        def get_db_async():
            async def generate():
                async with session_factory() as session:
                    yield session

            return generate()

        context = MagicMock()
        context.get_db_async = get_db_async
        registry = OutboundAdapterRegistry()
        registry.register(
            adapter=ConsoleOutboundAdapter(),
            channel="email",
            name="console",
            set_default=True,
        )
        service = OutboundService(
            config=get_outbound_config(None),
            module_context=context,
            adapter_registry_service=OutboundAdapterRegistryService(registry),
        )
        service.get_module_mapping = AsyncMock(return_value=None)

        try:
            result = await service.send(
                recipient_id="user-1",
                recipient_contact="user@example.com",
                subject="Async test",
                body="Message body",
                module_name="menu",
            )
            await asyncio.gather(*service._tasks)
            async with session_factory() as verify_session:
                outbound = await service.get_message(verify_session, result["uuid"])

            assert result["status"] == "PENDING"
            assert outbound.status == OutboundStatus.SENT
            assert outbound.attempts == 1
            assert outbound.sent_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run_test())


def test_send_route_uses_async_database_dependency_and_service():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ..context_factory import get_current_user, get_outbound_service
    from ..routes import router

    service = MagicMock()
    service.send = AsyncMock(
        return_value={
            "uuid": "message-uuid",
            "module_name": "menu",
            "recipient_id": "user-1",
            "recipient_contact": "user@example.com",
            "channel": "email",
            "subject": "Subject",
            "body": "Body",
            "outbound_metadata": None,
            "status": "PENDING",
            "sent_at": None,
            "attempts": 0,
            "last_error": None,
        }
    )

    async def override_user():
        return SimpleNamespace(id=1)

    app = FastAPI()
    app.include_router(router, prefix="/outbound")
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_outbound_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            "/outbound/send",
            json={
                "module_name": "menu",
                "recipient_id": "user-1",
                "recipient_contact": "user@example.com",
                "subject": "Subject",
                "body": "Body",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    service.send.assert_awaited_once()
    assert "db" not in service.send.await_args.kwargs


def _create_outbound_test_client(db, service):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ..context_factory import get_async_db, get_current_user, get_outbound_service
    from ..routes import router

    async def override_db():
        yield db

    async def override_user():
        return SimpleNamespace(id=1)

    app = FastAPI()
    app.include_router(router, prefix="/outbound")
    app.dependency_overrides[get_async_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_outbound_service] = lambda: service
    return TestClient(app)


def test_list_outbounds_awaits_async_query():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    message = SimpleNamespace(
        uuid="message-uuid",
        module_name="menu",
        recipient_id="user-1",
        channel="email",
        subject="Subject",
        body="Body",
        recipient_contact="user@example.com",
        messaging_metadata=None,
        status=OutboundStatus.SENT,
        sent_at=None,
        attempts=1,
        last_error=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [message])
        )
    )
    with _create_outbound_test_client(db, MagicMock()) as client:
        response = client.get("/outbound/messages?paging=false")

    assert response.status_code == 200
    assert response.json()["data"][0]["uuid"] == "message-uuid"
    db.execute.assert_awaited_once()


def test_create_module_mapping_awaits_service_and_session_operations():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    mapping = SimpleNamespace(
        module_name="menu",
        default_adapter_name="console",
        default_channel="email",
        max_retry_attempts=3,
        retry_backoff_seconds=0,
        rate_limit_per_minute=None,
        is_active=True,
        description="Menu messages",
    )
    service = MagicMock()
    service._create_or_update_module_mapping = AsyncMock(return_value=mapping)
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with _create_outbound_test_client(db, service) as client:
        response = client.post(
            "/outbound/module-mappings",
            json={"module_name": "menu", "retry_backoff_seconds": 0},
        )

    assert response.status_code == 200
    assert response.json()["module_name"] == "menu"
    service._create_or_update_module_mapping.assert_awaited_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(mapping)


def test_message_read_and_status_routes_await_async_service():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    message = SimpleNamespace(
        uuid="message-uuid",
        module_name="menu",
        recipient_id="user-1",
        recipient_contact="user@example.com",
        channel="email",
        subject="Subject",
        body="Body",
        messaging_metadata=None,
        status=OutboundStatus.SENT,
        sent_at=None,
        attempts=1,
        last_error=None,
    )
    service = MagicMock()
    service.get_message = AsyncMock(return_value=message)
    service.get_status = AsyncMock(return_value="SENT")

    path_uuid = "11111111-1111-1111-1111-111111111111"
    with _create_outbound_test_client(MagicMock(), service) as client:
        response = client.get(f"/outbound/messages/{path_uuid}")
        status_response = client.get(f"/outbound/messages/{path_uuid}/status")

    assert response.status_code == 200
    assert response.json()["uuid"] == "message-uuid"
    assert status_response.json() == {"uuid": path_uuid, "status": "SENT"}
    service.get_message.assert_awaited_once()
    service.get_status.assert_awaited_once()


def test_module_mapping_routes_await_async_database_operations():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    mapping = SimpleNamespace(
        module_name="menu",
        default_adapter_name="console",
        default_channel="email",
        max_retry_attempts=3,
        retry_backoff_seconds=0,
        rate_limit_per_minute=None,
        is_active=True,
        description="Menu messages",
    )
    service = MagicMock()
    service.get_module_mapping = AsyncMock(return_value=mapping)
    service._create_or_update_module_mapping = AsyncMock(return_value=mapping)
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar=lambda: 1),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [mapping])),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()

    with _create_outbound_test_client(db, service) as client:
        list_response = client.get("/outbound/module-mappings?paging=true")
        get_response = client.get("/outbound/module-mappings/menu")
        update_response = client.put(
            "/outbound/module-mappings/menu",
            json={"module_name": "menu", "retry_backoff_seconds": 0},
        )
        delete_response = client.delete("/outbound/module-mappings/menu")

    assert list_response.status_code == 200
    assert list_response.json()["data"][0]["module_name"] == "menu"
    assert get_response.status_code == 200
    assert update_response.status_code == 200
    assert delete_response.status_code == 200
    assert db.execute.await_count == 2
    assert service.get_module_mapping.await_count == 3
    assert service._create_or_update_module_mapping.await_count == 1
    assert db.commit.await_count == 2
    db.refresh.assert_awaited_once_with(mapping)
    db.delete.assert_awaited_once_with(mapping)


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
    return {
        "status": "failed",
        "message": "Tests failed",
        "details": result.stdout + result.stderr,
    }
