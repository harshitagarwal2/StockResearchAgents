"""Thread-safe registry for immutable workflow profile providers."""

from __future__ import annotations

from threading import RLock

from .base import ProfileDescriptor, ProfileProvider


class ProfileRegistry:
    """Register profile implementations without central switch statements."""

    def __init__(self, providers: tuple[ProfileProvider, ...] = ()) -> None:
        self._lock = RLock()
        self._providers: dict[str, ProfileProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ProfileProvider) -> None:
        if not isinstance(provider, ProfileProvider):
            raise TypeError("provider must implement ProfileProvider")
        profile = provider.descriptor.profile
        with self._lock:
            current = self._providers.get(profile)
            if current is provider:
                return
            if current is not None:
                raise ValueError(f"workflow profile is already registered: {profile}")
            self._providers[profile] = provider

    def get(self, profile: str) -> ProfileProvider:
        with self._lock:
            try:
                return self._providers[profile]
            except KeyError as exc:
                raise KeyError(f"unknown workflow profile: {profile}") from exc

    def descriptors(self) -> tuple[ProfileDescriptor, ...]:
        with self._lock:
            return tuple(self._providers[name].descriptor for name in sorted(self._providers))

    def catalog(self) -> tuple[dict[str, object], ...]:
        return tuple(descriptor.to_dict() for descriptor in self.descriptors())

    def __contains__(self, profile: object) -> bool:
        with self._lock:
            return isinstance(profile, str) and profile in self._providers
