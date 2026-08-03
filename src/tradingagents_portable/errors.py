"""Typed capability errors."""

from __future__ import annotations

from .contracts import SetupGuidance


class CapabilitySetupError(RuntimeError):
    def __init__(self, guidance: SetupGuidance):
        super().__init__(guidance.message)
        self.guidance = guidance

    def to_dict(self) -> dict[str, object]:
        return {"ok": False, "error": self.guidance.to_dict()}
