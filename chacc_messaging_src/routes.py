from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from .context_factory import get_db, get_module_context, get_messaging_service
from .models import Messaging, ModuleMessagingMapping, MessagingStatus
from .service import MessagingService
from .adapters import MessagingAdapterRegistry
from .exceptions import AdapterNotFoundError


router = APIRouter()


class SendNotificationRequest(BaseModel):
    module_name: str = Field(..., description="Module name sending the notification")
    recipient_id: str = Field(..., description="User/entity identifier")
    recipient_contact: str = Field(..., description="Email address or phone number")
    subject: Optional[str] = Field(default=None, description="Message subject (required for email, ignored for SMS)")
    body: str = Field(..., description="Message body content")
    channel: str = Field(default="email", description="Channel to use")
    adapter_name: str = Field(default="console", description="Adapter to use")
    content_type: str = Field(default="text/plain", description="Content type: text/plain for SMS/text, html for HTML email")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Module-specific tracking data")

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        if v not in ("text/plain", "html"):
            raise ValueError('content_type must be "text/plain" or "html"')
        return v


class MessagingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    module_name: str
    recipient_id: str
    channel: str
    subject: Optional[str]
    body: str
    recipient_contact: str
    notification_metadata: Optional[dict]
    status: str
    sent_at: Optional[str]
    attempts: int
    last_error: Optional[str]


@router.post("/send", response_model=MessagingResponse)
async def send_notification(
    payload: SendNotificationRequest,
    service: MessagingService = Depends(get_messaging_service),
    db: Session = Depends(get_db),
):
    try:
        notification = await service.send(
            db=db,
            recipient_id=payload.recipient_id,
            recipient_contact=payload.recipient_contact,
            body=payload.body,
            module_name=payload.module_name,
            subject=payload.subject,
            channel=payload.channel,
            adapter_name=payload.adapter_name,
            metadata=payload.metadata,
            content_type=payload.content_type,
        )
        db.commit()
        return MessagingResponse(
            id=notification.id,
            uuid=notification.uuid,
            module_name=notification.module_name,
            recipient_id=notification.recipient_id,
            channel=notification.channel,
            subject=notification.subject,
            body=notification.body,
            recipient_contact=notification.recipient_contact,
            notification_metadata=notification.notification_metadata,
            status=notification.status.value,
            sent_at=notification.sent_at.isoformat() if notification.sent_at else None,
            attempts=notification.attempts,
            last_error=notification.last_error,
        )
    except AdapterNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/notifications", response_model=List[MessagingResponse])
async def list_notifications(
    module_name: Optional[str] = Query(None, description="Filter by module name"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    status: Optional[str] = Query(None, description="Filter by status"),
    service: MessagingService = Depends(get_messaging_service),
    db: Session = Depends(get_db),
):
    stmt = select(Messaging)
    if module_name:
        stmt = stmt.where(Messaging.module_name == module_name)
    if channel:
        stmt = stmt.where(Messaging.channel == channel)
    if status:
        stmt = stmt.where(Messaging.status == status)
    stmt = stmt.order_by(Messaging.created_at.desc())
    result = db.execute(stmt)
    notifications = result.scalars().all()

    return [
        MessagingResponse(
            id=n.id,
            uuid=n.uuid,
            module_name=n.module_name,
            recipient_id=n.recipient_id,
            channel=n.channel,
            subject=n.subject,
            body=n.body,
            recipient_contact=n.recipient_contact,
            notification_metadata=n.notification_metadata,
            status=n.status.value,
            sent_at=n.sent_at.isoformat() if n.sent_at else None,
            attempts=n.attempts,
            last_error=n.last_error,
        )
        for n in notifications
    ]


@router.get("/notifications/{notification_uuid}", response_model=MessagingResponse)
async def get_notification(
    notification_uuid: str,
    service: MessagingService = Depends(get_messaging_service),
    db: Session = Depends(get_db),
):
    notification = service.get_notification(db, notification_uuid)
    if not notification:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessagingResponse(
        id=notification.id,
        uuid=notification.uuid,
        module_name=notification.module_name,
        recipient_id=notification.recipient_id,
        channel=notification.channel,
        subject=notification.subject,
        body=notification.body,
        recipient_contact=notification.recipient_contact,
        notification_metadata=notification.notification_metadata,
        status=notification.status.value,
        sent_at=notification.sent_at.isoformat() if notification.sent_at else None,
        attempts=notification.attempts,
        last_error=notification.last_error,
    )


@router.get("/notifications/{notification_uuid}/status")
async def get_notification_status(
    notification_uuid: str,
    service: MessagingService = Depends(get_messaging_service),
    db: Session = Depends(get_db),
):
    status = await service.get_status(db, notification_uuid)
    if status is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"notification_uuid": notification_uuid, "status": status.value}