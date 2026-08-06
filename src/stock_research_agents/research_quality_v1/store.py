"""Append-only outcome journal and persisted deterministic scorecards."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from ..state import DEFAULT_STATE_LAYOUT
from ..state_write_lock import state_write_lock
from .conformance import validate_quality_bundle
from .contracts import (
    Forecast,
    OutcomeLedger,
    OutcomeObservation,
    ResearchQualityReceipt,
    canonical_json,
)
from .scoring import QualityScorecard, score_forecast


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(payload))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class QualityStore:
    """Persist immutable forecasts and append-only outcome corrections."""

    def __init__(self, state_dir: str | os.PathLike[str] | None = None) -> None:
        self._state_dir = Path(state_dir).expanduser() if state_dir is not None else None
        self._lock = RLock()
        self._registrations: dict[str, tuple[ResearchQualityReceipt, tuple[Forecast, ...]]] = {}
        self._staged_registrations: dict[str, tuple[ResearchQualityReceipt, tuple[Forecast, ...]]] = {}
        self._observations: dict[str, tuple[OutcomeObservation, ...]] = {}
        self._loaded = False

    @property
    def state_dir(self) -> Path | None:
        return self._state_dir

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._state_dir is not None:
            registration_dir = self._state_dir / "registrations"
            if registration_dir.exists():
                for path in sorted(registration_dir.glob("*.json")):
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict) or set(raw) != {"receipt", "forecasts"}:
                        raise ValueError(f"invalid quality registration: {path.name}")
                    receipt = ResearchQualityReceipt.from_dict(raw["receipt"])
                    forecasts = tuple(Forecast.from_dict(item) for item in raw["forecasts"])
                    self._registrations[receipt.run_id] = (receipt, forecasts)
            staged_dir = self._state_dir / "staged-registrations"
            if staged_dir.exists():
                for path in sorted(staged_dir.glob("*.json")):
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(raw, dict) or set(raw) != {"receipt", "forecasts"}:
                        raise ValueError(f"invalid staged quality registration: {path.name}")
                    receipt = ResearchQualityReceipt.from_dict(raw["receipt"])
                    forecasts = tuple(Forecast.from_dict(item) for item in raw["forecasts"])
                    self._staged_registrations[receipt.run_id] = (receipt, forecasts)
            outcome_dir = self._state_dir / "outcomes"
            if outcome_dir.exists():
                for forecast_dir in sorted(path for path in outcome_dir.iterdir() if path.is_dir()):
                    forecast_id = forecast_dir.name
                    observations = tuple(
                        self._load_observation(json.loads(path.read_text(encoding="utf-8")), forecast_id)
                        for path in sorted(forecast_dir.glob("*.json"))
                    )
                    if observations:
                        OutcomeLedger("research-quality.v1", forecast_id, observations)
                        self._observations[forecast_id] = observations
        self._loaded = True

    def _writer_root(self) -> Path | None:
        return None if self._state_dir is None else self._state_dir.parent

    def _refresh_durable_snapshot(self) -> None:
        if self._state_dir is None:
            self._ensure_loaded()
            return
        self._registrations.clear()
        self._staged_registrations.clear()
        self._observations.clear()
        self._loaded = False
        self._ensure_loaded()

    @staticmethod
    def _load_observation(value: object, forecast_id: str) -> OutcomeObservation:
        if isinstance(value, dict) and value.get("forecast_id") != forecast_id:
            value = value | {"forecast_id": forecast_id}
        return OutcomeObservation.from_dict(value)

    @staticmethod
    def _same_registration(
        current: tuple[ResearchQualityReceipt, tuple[Forecast, ...]],
        receipt: ResearchQualityReceipt,
        forecasts: tuple[Forecast, ...],
    ) -> bool:
        return canonical_json(current[0]) == canonical_json(receipt) and canonical_json(
            [item.to_dict() for item in current[1]]
        ) == canonical_json([item.to_dict() for item in forecasts])

    @staticmethod
    def _registration_payload(
        receipt: ResearchQualityReceipt,
        forecasts: tuple[Forecast, ...],
    ) -> dict[str, object]:
        return {
            "receipt": receipt.to_dict(),
            "forecasts": [item.to_dict() for item in forecasts],
        }

    def stage_registration(self, receipt: ResearchQualityReceipt, forecasts: tuple[Forecast, ...]) -> None:
        """Validate and durably stage an immutable registration without exposing it."""
        report = validate_quality_bundle(receipt, forecasts, ())
        if not report.passed:
            raise ValueError(
                "quality registration is not conformant: "
                + "; ".join(f"{issue.path}: {issue.detail}" for issue in report.issues)
            )
        with state_write_lock(self._writer_root()), self._lock:
            self._refresh_durable_snapshot()
            current = self._registrations.get(receipt.run_id)
            candidate = (receipt, tuple(forecasts))
            if current is not None:
                if self._same_registration(current, receipt, forecasts):
                    return
                raise ValueError(f"quality run already has a different immutable registration: {receipt.run_id}")
            staged = self._staged_registrations.get(receipt.run_id)
            if staged is not None:
                if self._same_registration(staged, receipt, forecasts):
                    return
                raise ValueError(f"quality run already has a different staged registration: {receipt.run_id}")
            known_forecasts = {
                forecast.forecast_id
                for _, registered_forecasts in (
                    *self._registrations.values(),
                    *self._staged_registrations.values(),
                )
                for forecast in registered_forecasts
            }
            overlap = known_forecasts & {forecast.forecast_id for forecast in forecasts}
            if overlap:
                raise ValueError(f"forecast IDs are already registered to another run: {sorted(overlap)}")
            if self._state_dir is not None:
                _atomic_write(
                    self._state_dir / "staged-registrations" / f"{receipt.run_id}.json",
                    self._registration_payload(receipt, forecasts),
                )
            self._staged_registrations[receipt.run_id] = candidate

    def publish_registration(self, run_id: str) -> None:
        """Make one staged registration visible; retry is idempotent after crashes."""
        with state_write_lock(self._writer_root()), self._lock:
            self._refresh_durable_snapshot()
            if run_id in self._registrations:
                return
            candidate = self._staged_registrations.get(run_id)
            if candidate is None:
                raise KeyError(f"staged quality registration not found: {run_id}")
            receipt, forecasts = candidate
            if self._state_dir is not None:
                _atomic_write(
                    self._state_dir / "registrations" / f"{run_id}.json",
                    self._registration_payload(receipt, forecasts),
                )
                try:
                    (self._state_dir / "staged-registrations" / f"{run_id}.json").unlink(missing_ok=True)
                except OSError:
                    pass
            self._registrations[run_id] = candidate
            self._staged_registrations.pop(run_id, None)

    def register(self, receipt: ResearchQualityReceipt, forecasts: tuple[Forecast, ...]) -> None:
        """Stage and publish an immutable forecast set, idempotently."""
        self.stage_registration(receipt, forecasts)
        self.publish_registration(receipt.run_id)

    def is_published(self, run_id: str) -> bool:
        """Return whether a registration crossed its visibility boundary."""
        with state_write_lock(self._writer_root()), self._lock:
            self._refresh_durable_snapshot()
            return run_id in self._registrations

    def _forecast(self, forecast_id: str) -> Forecast:
        for _, forecasts in self._registrations.values():
            for forecast in forecasts:
                if forecast.forecast_id == forecast_id:
                    return forecast
        raise KeyError(f"forecast is not registered: {forecast_id}")

    def append_outcome(self, observation: OutcomeObservation) -> QualityScorecard:
        """Append one resolution/correction and persist its derived scorecard."""
        with state_write_lock(self._writer_root()), self._lock:
            self._refresh_durable_snapshot()
            forecast = self._forecast(observation.forecast_id)
            observations = self._observations.get(observation.forecast_id, ())
            if observations and observations[-1].observation_id == observation.observation_id:
                if canonical_json(observations[-1]) != canonical_json(observation):
                    raise ValueError("observation ID already identifies different outcome content")
                return score_forecast(
                    forecast,
                    OutcomeLedger("research-quality.v1", observation.forecast_id, observations),
                )
            ledger = OutcomeLedger("research-quality.v1", observation.forecast_id, observations).append(observation)
            scorecard = score_forecast(forecast, ledger)
            if scorecard.status == "policy_blocked":
                raise ValueError("outcome violates forecast timing policy")
            sequence = len(ledger.observations)
            if self._state_dir is not None:
                _atomic_write(
                    self._state_dir
                    / "outcomes"
                    / observation.forecast_id
                    / f"{sequence:06d}.{observation.observation_id}.json",
                    observation.to_dict(),
                )
                _atomic_write(
                    self._state_dir
                    / "scorecards"
                    / observation.forecast_id
                    / f"{sequence:06d}.{observation.observation_id}.json",
                    scorecard.to_dict(),
                )
            self._observations[observation.forecast_id] = ledger.observations
            return scorecard

    def projection(self, run_id: str) -> dict[str, object] | None:
        """Return completed quality records and stored scorecards without UI calculations."""
        with state_write_lock(self._writer_root()), self._lock:
            self._refresh_durable_snapshot()
            registration = self._registrations.get(run_id)
            if registration is None:
                return None
            receipt, forecasts = registration
            ledgers: list[dict[str, object]] = []
            scorecards: list[dict[str, object]] = []
            for forecast in forecasts:
                ledger = OutcomeLedger(
                    "research-quality.v1",
                    forecast.forecast_id,
                    self._observations.get(forecast.forecast_id, ()),
                )
                ledgers.append(ledger.to_dict())
                scorecards.append(score_forecast(forecast, ledger).to_dict())
            return {
                "receipt": receipt.to_dict(),
                "forecasts": [forecast.to_dict() for forecast in forecasts],
                "outcome_ledgers": ledgers,
                "scorecards": scorecards,
                "complete": True,
            }


QUALITY_STORE = QualityStore(DEFAULT_STATE_LAYOUT.quality_dir)
