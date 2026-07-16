class TemplateNotFoundError(Exception):
    """Raised when a notification template is not found."""

    def __init__(self, template_key: str):
        self.template_key = template_key
        super().__init__(f"Template '{template_key}' not found")


class AdapterNotFoundError(Exception):
    """Raised when no adapter is registered for a channel."""

    def __init__(self, channel: str, adapter_name: str = None):
        self.channel = channel
        self.adapter_name = adapter_name
        msg = f"No adapter registered for channel '{channel}'"
        if adapter_name:
            msg += f" with name '{adapter_name}'"
        super().__init__(msg)


class VariableValidationError(Exception):
    """Raised when notification variables don't match the template schema."""

    def __init__(self, message: str):
        super().__init__(message)
