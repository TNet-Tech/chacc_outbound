"""
Tests for chacc_notifications module.
"""
import pytest
import sys
import os

from ..models import NotificationTemplate, Notification, ModuleNotificationMapping, NotificationStatus
from ..exceptions import TemplateNotFoundError, AdapterNotFoundError, VariableValidationError
from ..config import get_notification_config


def test_models_import():
    assert NotificationTemplate is not None
    assert Notification is not None
    assert ModuleNotificationMapping is not None
    assert NotificationStatus is not None


def test_notification_status_enum():
    assert NotificationStatus.PENDING == "PENDING"
    assert NotificationStatus.SENT == "SENT"
    assert NotificationStatus.FAILED == "FAILED"
    assert NotificationStatus.RETRYING == "RETRYING"


def test_notification_template_creation():
    template = NotificationTemplate(
        template_key="order_shipped",
        module_name="order_service",
        channel="email",
        adapter_name="console",
        body_template="Order {{order_id}} shipped",
        variables_schema={"order_id": {"type": "string", "required": True}},
    )
    assert template.template_key == "order_shipped"
    assert template.module_name == "order_service"
    assert template.channel == "email"
    assert template.adapter_name == "console"


def test_notification_creation():
    notification = Notification(
        template_id=1,
        module_name="order_service",
        recipient_id="user_123",
        channel="email",
        recipient_contact="user@example.com",
        body="Order shipped",
        status=NotificationStatus.PENDING,
    )
    assert notification.recipient_id == "user_123"
    assert notification.channel == "email"
    assert notification.status == NotificationStatus.PENDING


def test_module_notification_mapping_creation():
    mapping = ModuleNotificationMapping(
        module_name="order_service",
        default_channels=["email"],
        max_retry_attempts=3,
        retry_backoff_seconds=300,
    )
    assert mapping.module_name == "order_service"
    assert mapping.default_channels == ["email"]
    assert mapping.max_retry_attempts == 3


def test_exceptions_exist():
    assert TemplateNotFoundError is not None
    assert AdapterNotFoundError is not None
    assert VariableValidationError is not None


def test_router_exists():
    from ..routes import router
    assert router is not None
    assert hasattr(router, "routes")


def test_get_notification_config_without_context():
    config = get_notification_config(None)
    assert config["EMAIL_BACKEND"] == "console"
    assert config["EMAIL_SMTP_HOST"] == ""
    assert config["EMAIL_SMTP_PORT"] == 587
    assert config["EMAIL_SMTP_FROM"] == "noreply@example.com"


def test_get_notification_config_with_context():
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

    config = get_notification_config(MockContext())
    assert config["ENVIRONMENT"] == "production"
    assert config["EMAIL_BACKEND"] == "smtp"
    assert config["EMAIL_SMTP_HOST"] == "smtp.example.com"
    assert config["EMAIL_SMTP_PORT"] == 465
    assert config["EMAIL_SMTP_USERNAME"] == "user"
    assert config["EMAIL_SMTP_PASSWORD"] == "pass"
    assert config["EMAIL_SMTP_FROM"] == "alerts@example.com"


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
