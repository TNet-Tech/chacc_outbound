class AdapterNotFoundError(Exception):
    def __init__(self, channel: str, adapter_name: str):
        self.channel = channel
        self.adapter_name = adapter_name
        super().__init__(f"Adapter '{adapter_name}' not found for channel '{channel}'")
