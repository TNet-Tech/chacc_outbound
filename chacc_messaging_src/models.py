from enum import Enum

from chacc_api import ChaCCBaseModel, register_model
from sqlalchemy import Column, String, Integer, Boolean, Text, JSON, Enum as SQLAEnum, DateTime


class MessagingStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class MessagingTemplate(ChaCCBaseModel):
    __tablename__ = "notification_templates"

    template_key = Column(String(100), nullable=False)
    module_name = Column(String(100), nullable=False)

    channel = Column(String(50), nullable=False)
    adapter_name = Column(String(100), nullable=False)

    subject_template = Column(String(500), nullable=True)
    body_template = Column(Text, nullable=False)

    email_type = Column(String(10), nullable=True)

    variables_schema = Column(JSON, nullable=False, default=dict)

    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class Messaging(ChaCCBaseModel):
    __tablename__ = "notifications"

    template_id = Column(Integer, nullable=True)
    module_name = Column(String(100), nullable=False)
    recipient_id = Column(String(100), nullable=False)
    channel = Column(String(50), nullable=False)

    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=False)
    recipient_contact = Column(String(500), nullable=False)

    notification_metadata = Column(JSON, nullable=True)

    status = Column(SQLAEnum(MessagingStatus), default=MessagingStatus.PENDING, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    attempts = Column(Integer, default=0)
    last_error = Column(String(500), nullable=True)


class ModuleMessagingMapping(ChaCCBaseModel):
    __tablename__ = "module_messaging_mappings"

    module_name = Column(String(100), primary_key=True)

    default_adapter_name = Column(String(50), nullable=False, default="console")
    default_channel = Column(String(20), nullable=False, default="email")
    default_template_key = Column(String(100), nullable=True)
    default_channels = Column(JSON, default=["email"])
    max_retry_attempts = Column(Integer, default=3)
    retry_backoff_seconds = Column(Integer, default=300)
    rate_limit_per_minute = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    description = Column(String(500), nullable=True)
