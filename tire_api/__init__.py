import importlib
from typing import Any

__all__ = [
    "BarezTireClient",
    "BaseTireClient",
    "FactoryPortalClient",
    "HyperTireClient",
    "KalaNtswClient",
    "KavirTireClient",
    "MarketPriceClient",
    "SniperEngine",
]

_EXPORT_MAP = {
    "BarezTireClient": "tire_api.barez_client",
    "BaseTireClient": "tire_api.base_client",
    "FactoryPortalClient": "tire_api.multi_portal_client",
    "HyperTireClient": "tire_api.hypertire_client",
    "KalaNtswClient": "tire_api.kala_ntsw_client",
    "KavirTireClient": "tire_api.kavir_client",
    "MarketPriceClient": "tire_api.market_price_client",
    "SniperEngine": "tire_api.sniper_engine",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORT_MAP:
        mod = importlib.import_module(_EXPORT_MAP[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'tire_api' has no attribute {name!r}")
