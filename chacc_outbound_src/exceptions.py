class AdapterNotFoundError(Exception):
    def __init__(self, channel: str, adapter_name: str):
        self.channel = channel
        self.adapter_name = adapter_name
        super().__init__(f"Adapter '{adapter_name}' not found for channel '{channel}'")


class AdapterConfigError(Exception):
    def __init__(self, adapter_name: str, reason: str):
        self.adapter_name = adapter_name
        self.reason = reason
        super().__init__(f"Adapter '{adapter_name}' configuration error: {reason}")
