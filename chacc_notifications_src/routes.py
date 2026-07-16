from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from .context_factory import get_db, get_module_context
from .models import NotificationTemplate, Notification, ModuleNotificationMapping, NotificationStatus
from .service import NotificationService
from .adapters import NotificationAdapterRegistry
from .config import get_notification_config
from .exceptions import TemplateNotFoundError, AdapterNotFoundError


router = APIRouter()


def get_notification_service() -> NotificationService:
    context = get_module_context()
    if context is None:
        raise HTTPException(status_code=500, detail="Module not initialized")

    service = context.get_service("notification_service")
    if service is None:
        raise HTTPException(status_code=500, detail="Notification service not initialized")

    return service


class SendNotificationRequest(BaseModel):
    template_key: str = Field(..., description="Template identifier")
    recipient_id: str = Field(..., description="User/entity identifier")
    recipient_contact: str = Field(..., description="Email address")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Variables for template rendering")
    channel: str = Field(default="email", description="Channel to use")
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
    template_id: int
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
        module_context = get_module_context()
        notification = await service.send(
            db=db,
            template_key=payload.template_key,
            recipient_id=payload.recipient_id,
            recipient_contact=payload.recipient_contact,
            variables=payload.variables,
            channel=payload.channel,
            metadata=payload.metadata,
            module_context=module_context,
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


@router.post("/templates", response_model=NotificationTemplateResponse, status_code=201)
async def create_template(
    payload: CreateTemplateRequest,
    service: NotificationService = Depends(get_notification_service),
    db: Session = Depends(get_db),
):
    try:
        module_context = get_module_context()
        module_name = module_context.module_name if module_context else "chacc_notifications"
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
