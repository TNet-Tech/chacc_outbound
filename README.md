# ChaccNotifications Module

A ChaCC API module providing template-driven notification delivery via adapters.

## Features

- Template registration with Jinja2 rendering
- Adapter-based channel delivery (Email, Console)
- Async fire-and-forget notification sending
- Module notification mappings and retry policies

## Environment Variables

This module uses environment variables from the main `.env` file at project root.
Use the naming convention: `{MODULE_NAME}_{VAR_NAME}` in uppercase.

For example, if your module is named `chacc_messaging`:
```bash
# In .env file at project root
CHACC_NOTIFICATIONS_EMAIL_BACKEND=console
CHACC_NOTIFICATIONS_EMAIL_SMTP_HOST=smtp.example.com
CHACC_NOTIFICATIONS_EMAIL_SMTP_PORT=587
CHACC_NOTIFICATIONS_EMAIL_SMTP_USERNAME=user
CHACC_NOTIFICATIONS_EMAIL_SMTP_PASSWORD=pass
CHACC_NOTIFICATIONS_EMAIL_SMTP_FROM=noreply@example.com
```

## Installation

This module is automatically loaded by the ChaCC backbone when it's placed in the `plugins/` directory.

## Development

### Testing

Run tests using pytest:

```bash
pytest plugins/chacc_messaging/chacc_messaging_src/tests/ -v
```

## Configuration

- `CHACC_NOTIFICATIONS_EMAIL_BACKEND`: Set to `console` (development) or `smtp` (production)
- `CHACC_NOTIFICATIONS_EMAIL_SMTP_HOST`: SMTP server host
- `CHACC_NOTIFICATIONS_EMAIL_SMTP_PORT`: SMTP server port
- `CHACC_NOTIFICATIONS_EMAIL_SMTP_USERNAME`: SMTP username
- `CHACC_NOTIFICATIONS_EMAIL_SMTP_PASSWORD`: SMTP password
- `CHACC_NOTIFICATIONS_EMAIL_SMTP_FROM`: From email address

## API Endpoints

- `POST /notifications/send` - Send a notification
- `POST /notifications/templates` - Register a notification template
- `GET /notifications/templates` - List notification templates
- `GET /notifications/health` - Health check

## Dependencies

- Python 3.12+
- FastAPI
- SQLAlchemy
- Pydantic
- Jinja2

See `requirements.txt` for full dependencies.
