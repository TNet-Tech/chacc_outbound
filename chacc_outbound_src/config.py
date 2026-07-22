def get_outbound_config(module_context) -> dict:
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
        "ENVIRONMENT": module_context.get_module_config("ENVIRONMENT", "chacc_outbound", default="development"),
        "EMAIL_BACKEND": module_context.get_module_config("EMAIL_BACKEND", "chacc_outbound", default="console"),
        "EMAIL_SMTP_HOST": module_context.get_module_config("EMAIL_SMTP_HOST", "chacc_outbound", default=""),
        "EMAIL_SMTP_PORT": int(module_context.get_module_config("EMAIL_SMTP_PORT", "chacc_outbound", default="587")),
        "EMAIL_SMTP_USERNAME": module_context.get_module_config("EMAIL_SMTP_USERNAME", "chacc_outbound", default=""),
        "EMAIL_SMTP_PASSWORD": module_context.get_module_config("EMAIL_SMTP_PASSWORD", "chacc_outbound", default=""),
        "EMAIL_SMTP_FROM": module_context.get_module_config("EMAIL_SMTP_FROM", "chacc_outbound", default="noreply@example.com"),
    }
