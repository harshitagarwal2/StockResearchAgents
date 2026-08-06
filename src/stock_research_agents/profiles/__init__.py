"""Open/closed workflow profile registration for StockResearchAgents research."""

from .base import ProfileDescriptor, ProfileProvider
from .registry import ProfileRegistry

__all__ = ["ProfileDescriptor", "ProfileProvider", "ProfileRegistry"]
