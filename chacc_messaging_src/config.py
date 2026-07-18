def get_notification_config(module_context) -> dict:
    if module_context is None:
        return {
            "ENVIRONMENT": "development",
            "EMAIL_BACKEND": "console",
            "EMAIL_SMTP_HOST": "",
            "EMAIL_SMTP_PORT": 587,
            "EMAIL_SMTP_USERNAME": "",
            "EMAIL_SMTP_PASSWORD": "",
            "EMAIL_SMTP_FROM": "noreply@example.com",
        }

    return {
        "ENVIRONMENT": module_context.get_module_config("ENVIRONMENT", "chacc_messaging", default="development"),
        "EMAIL_BACKEND": module_context.get_module_config("EMAIL_BACKEND", "chacc_messaging", default="console"),
        "EMAIL_SMTP_HOST": module_context.get_module_config("EMAIL_SMTP_HOST", "chacc_messaging", default=""),
        "EMAIL_SMTP_PORT": int(module_context.get_module_config("EMAIL_SMTP_PORT", "chacc_messaging", default="587")),
        "EMAIL_SMTP_USERNAME": module_context.get_module_config("EMAIL_SMTP_USERNAME", "chacc_messaging", default=""),
        "EMAIL_SMTP_PASSWORD": module_context.get_module_config("EMAIL_SMTP_PASSWORD", "chacc_messaging", default=""),
        "EMAIL_SMTP_FROM": module_context.get_module_config("EMAIL_SMTP_FROM", "chacc_messaging", default="noreply@example.com"),
    }
