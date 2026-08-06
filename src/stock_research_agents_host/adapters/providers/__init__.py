"""Provider-specific strategies used by the public research adapter."""

from stock_research_agents_host.adapters.providers.catalog import (
    CAPABILITY_SPECS,
    CapabilitySpec,
    capability_spec,
    provider_specs,
    public_adapter_capabilities,
)
from stock_research_agents_host.adapters.providers.denied import DeniedSocialProvider
from stock_research_agents_host.adapters.providers.gdelt import GdeltProvider
from stock_research_agents_host.adapters.providers.licensed import LicensedMarketDataProvider
from stock_research_agents_host.adapters.providers.polymarket import PolymarketProvider
from stock_research_agents_host.adapters.providers.sec import SecProvider
from stock_research_agents_host.adapters.providers.world_bank import WorldBankProvider

__all__ = [
    "CAPABILITY_SPECS",
    "CapabilitySpec",
    "DeniedSocialProvider",
    "GdeltProvider",
    "LicensedMarketDataProvider",
    "PolymarketProvider",
    "SecProvider",
    "WorldBankProvider",
    "capability_spec",
    "provider_specs",
    "public_adapter_capabilities",
]
