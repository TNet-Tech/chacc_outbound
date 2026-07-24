from .adapters import OutboundAdapterRegistry, BaseOutboundAdapter


class OutboundAdapterRegistryService:
    def __init__(self, registry: OutboundAdapterRegistry):
        self._registry = registry

    def register(
        self,
        adapter: BaseOutboundAdapter,
        channel: str,
        name: str,
        set_default: bool = False,
    ) -> None:
        self._registry.register(adapter=adapter, channel=channel, name=name, set_default=set_default)

    def get(self, channel: str, adapter_name: str = None) -> BaseOutboundAdapter:
        return self._registry.get(channel=channel, adapter_name=adapter_name)

    def list_adapters(self) -> dict:
        return self._registry.list_adapters()
