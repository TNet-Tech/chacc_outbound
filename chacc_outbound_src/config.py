def _parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).lower() in ("true", "1", "yes", "on")


def get_outbound_config(module_context) -> dict:
    port = 587
    use_tls = False
    if module_context is not None:
        port_str = module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_PORT", "chacc_outbound", default="587")
        try:
            port = int(port_str)
        except (TypeError, ValueError):
            port = 587
        use_tls_raw = module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_USE_TLS", "chacc_outbound", default=None)
        if use_tls_raw is None:
            use_tls = port == 465
        else:
            use_tls = _parse_bool(use_tls_raw, default=False)

    if module_context is None:
        return {
            "CHACC_OUTBOUND_EMAIL_BACKEND": "console",
            "CHACC_OUTBOUND_EMAIL_SMTP_HOST": "",
            "CHACC_OUTBOUND_EMAIL_SMTP_PORT": port,
            "CHACC_OUTBOUND_EMAIL_SMTP_USERNAME": "",
            "CHACC_OUTBOUND_EMAIL_SMTP_PASSWORD": "",
            "CHACC_OUTBOUND_EMAIL_SMTP_FROM": "noreply@example.com",
            "CHACC_OUTBOUND_EMAIL_SMTP_USE_TLS": use_tls,
        }

    return {
        "CHACC_OUTBOUND_EMAIL_BACKEND": module_context.get_module_config("CHACC_OUTBOUND_EMAIL_BACKEND", "chacc_outbound", default="console"),
        "CHACC_OUTBOUND_EMAIL_SMTP_HOST": module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_HOST", "chacc_outbound", default=""),
        "CHACC_OUTBOUND_EMAIL_SMTP_PORT": port,
        "CHACC_OUTBOUND_EMAIL_SMTP_USERNAME": module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_USERNAME", "chacc_outbound", default=""),
        "CHACC_OUTBOUND_EMAIL_SMTP_PASSWORD": module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_PASSWORD", "chacc_outbound", default=""),
        "CHACC_OUTBOUND_EMAIL_SMTP_FROM": module_context.get_module_config("CHACC_OUTBOUND_EMAIL_SMTP_FROM", "chacc_outbound", default="noreply@example.com"),
        "CHACC_OUTBOUND_EMAIL_SMTP_USE_TLS": use_tls,
    }
