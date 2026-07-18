from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from .context_factory import get_db, get_module_context, get_notification_service
from .models import NotificationTemplate, Notification, ModuleNotificationMapping, NotificationStatus
from .service import NotificationService
from .adapters import NotificationAdapterRegistry
from .exceptions import TemplateNotFoundError, AdapterNotFoundError, VariableValidationError


router = APIRouter()


class SendNotificationRequest(BaseModel):
    module_name: str = Field(..., description="Module name sending the notification")
    template_key: str = Field(..., description="Template identifier")
    recipient_id: str = Field(..., description="User/entity identifier")
    recipient_contact: str = Field(..., description="Email address or phone number")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Variables for template rendering")
    channel: Optional[str] = Field(default=None, description="Channel override")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Module-specific tracking data")


class SendDirectNotificationRequest(BaseModel):
    module_name: str = Field(..., description="Module name sending the notification")
    recipient_id: str = Field(..., description="User/entity identifier")
    recipient_contact: str = Field(..., description="Email address or phone number")
    subject: Optional[str] = Field(default=None, description="Notification subject (required for email, ignored for SMS)")
    body: str = Field(..., description="Notification body content")
    channel: str = Field(default="email", description="Channel to use")
    adapter_name: str = Field(default="console", description="Adapter to use")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Module-specific tracking data")


class CreateTemplateRequest(BaseModel):
    template_key: str = Field(..., description="Template identifier")
    channel: str = Field(default="email", description="Channel")
    adapter_name: str = Field(default="console", description="Adapter name")
    subject_template: Optional[str] = Field(default=None, description="Jinja subject template")
    body_template: str = Field(..., description="Jinja body template")
    email_type: Optional[str] = Field(default=None, description="html or text")
    variables_schema: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Variable schema")
    description: Optional[str] = Field(default=None, description="Template description")


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    template_id: Optional[int]
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


class NotificationTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_key: str
    module_name: str
    channel: str
    adapter_name: str
    subject_template: Optional[str]
    body_template: str
    email_type: Optional[str]
    variables_schema: dict
    description: Optional[str]
    is_active: bool


@router.post("/send", response_model=NotificationResponse)
async def send_notification(
    payload: SendNotificationRequest,
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    try:
        notification = await service.send(
            db=db,
            template_key=payload.template_key,
            recipient_id=payload.recipient_id,
            recipient_contact=payload.recipient_contact,
            variables=payload.variables,
            module_name=payload.module_name,
            channel=payload.channel,
            metadata=payload.metadata,
        )
        db.commit()
        return NotificationResponse(
            id=notification.id,
            template_id=notification.template_id,
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
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VariableValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AdapterNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-direct", response_model=NotificationResponse)
async def send_direct_notification(
    payload: SendDirectNotificationRequest,
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    try:
        notification = await service.send_direct(
            db=db,
            recipient_id=payload.recipient_id,
            recipient_contact=payload.recipient_contact,
            subject=payload.subject,
            body=payload.body,
            module_name=payload.module_name,
            channel=payload.channel,
            adapter_name=payload.adapter_name,
            metadata=payload.metadata,
        )
        db.commit()
        return NotificationResponse(
            id=notification.id,
            template_id=notification.template_id,
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


@router.post("/templates", response_model=NotificationTemplateResponse, status_code=201)
async def create_template(
    payload: CreateTemplateRequest,
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    try:
        module_context = get_module_context()
        module_name = module_context.module_name if module_context else "chacc_messaging"
        template = await service.create_template(
            db=db,
            template_key=payload.template_key,
            module_name=module_name,
            channel=payload.channel,
            adapter_name=payload.adapter_name,
            subject_template=payload.subject_template,
            body_template=payload.body_template,
            email_type=payload.email_type,
            variables_schema=payload.variables_schema,
            description=payload.description,
        )
        db.commit()
        return NotificationTemplateResponse(
            id=template.id,
            template_key=template.template_key,
            module_name=template.module_name,
            channel=template.channel,
            adapter_name=template.adapter_name,
            subject_template=template.subject_template,
            body_template=template.body_template,
            email_type=template.email_type,
            variables_schema=template.variables_schema,
            description=template.description,
            is_active=template.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates", response_model=List[NotificationTemplateResponse])
async def list_templates(
    module_name: Optional[str] = Query(None, description="Filter by module name"),
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    templates = service.list_templates(db, module_name)
    return [
        NotificationTemplateResponse(
            id=t.id,
            template_key=t.template_key,
            module_name=t.module_name,
            channel=t.channel,
            adapter_name=t.adapter_name,
            subject_template=t.subject_template,
            body_template=t.body_template,
            email_type=t.email_type,
            variables_schema=t.variables_schema,
            description=t.description,
            is_active=t.is_active,
        )
        for t in templates
    ]


@router.get("/notifications", response_model=List[NotificationResponse])
async def list_notifications(
    module_name: Optional[str] = Query(None, description="Filter by module name"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    status: Optional[str] = Query(None, description="Filter by status"),
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    stmt = select(Notification)
    if module_name:
        stmt = stmt.where(Notification.module_name == module_name)
    if channel:
        stmt = stmt.where(Notification.channel == channel)
    if status:
        stmt = stmt.where(Notification.status == status)
    stmt = stmt.order_by(Notification.created_at.desc())
    result = db.execute(stmt)
    notifications = result.scalars().all()

    return [
        NotificationResponse(
            id=n.id,
            uuid=n.uuid,
            template_id=n.template_id,
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


@router.get("/notifications/{notification_uuid}", response_model=NotificationResponse)
async def get_notification(
    notification_uuid: str,
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    notification = service.get_notification(db, notification_uuid)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return NotificationResponse(
        id=notification.id,
        uuid=notification.uuid,
        template_id=notification.template_id,
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
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    status = await service.get_status(db, notification_uuid)
    if status is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"notification_uuid": notification_uuid, "status": status.value}
