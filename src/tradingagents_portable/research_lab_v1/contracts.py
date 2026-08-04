"""Versioned, immutable records for reproducible research operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from tradingagents_portable.research_contracts import (
    StrictModel,
    _bounded_text,
    _utc_timestamp,
    _validate_id,
)

_DIGEST_LENGTH = 64


def _digest(value: str, path: str) -> None:
    if len(value) != _DIGEST_LENGTH or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{path} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ResearchPackDefinition(StrictModel):
    pack_id: str
    title: str
    purpose: str
    required_capabilities: tuple[str, ...]
    optional_capabilities: tuple[str, ...]
    stage_ids: tuple[str, ...]
    output_artifact_kinds: tuple[str, ...]
    history_policy: Literal["event_driven", "cycle_aware", "structural", "user_bounded"]

    def __post_init__(self) -> None:
        _validate_id(self.pack_id, "pack_id")
        _bounded_text(self.title, "title", 128)
        _bounded_text(self.purpose, "purpose", 1_000)
        for name, values in (
            ("required_capabilities", self.required_capabilities),
            ("optional_capabilities", self.optional_capabilities),
            ("stage_ids", self.stage_ids),
            ("output_artifact_kinds", self.output_artifact_kinds),
        ):
            if not values or len(set(values)) != len(values):
                raise ValueError(f"{name} must be a non-empty unique sequence")
            for value in values:
                _validate_id(value, name)
        overlap = set(self.required_capabilities) & set(self.optional_capabilities)
        if overlap:
            raise ValueError(f"capabilities cannot be both required and optional: {sorted(overlap)}")


@dataclass(frozen=True, slots=True)
class StageReceipt(StrictModel):
    stage_id: str
    status: Literal["completed", "skipped", "blocked"]
    started_at: str
    completed_at: str
    input_digest: str
    output_digest: str | None
    attempts: int
    limitation: str | None

    def __post_init__(self) -> None:
        _validate_id(self.stage_id, "stage_id")
        started = _utc_timestamp(self.started_at, "started_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("stage completed_at must not precede started_at")
        _digest(self.input_digest, "input_digest")
        if self.output_digest is not None:
            _digest(self.output_digest, "output_digest")
        if not 1 <= self.attempts <= 100:
            raise ValueError("attempts must be between 1 and 100")
        if self.status == "completed" and self.output_digest is None:
            raise ValueError("completed stages require an output_digest")
        if self.status != "completed" and not self.limitation:
            raise ValueError("skipped or blocked stages require a limitation")
        if self.limitation is not None:
            _bounded_text(self.limitation, "limitation", 1_000)


@dataclass(frozen=True, slots=True)
class StageCommitmentV1(StrictModel):
    """Coordinator-owned binding for one durably committed stage boundary."""

    stage_id: str
    envelope_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _validate_id(self.stage_id, "stage_id")
        _digest(self.envelope_digest, "envelope_digest")
        _digest(self.receipt_digest, "receipt_digest")


@dataclass(frozen=True, slots=True)
class RunCardV1(StrictModel):
    run_id: str
    profile: str
    research_pack_id: str
    submission_digest: str
    workflow_digest: str
    harness: str
    execution_mode: Literal["full", "compatible", "tools_only", "replay", "fixture"]
    started_at: str
    completed_at: str
    stages: tuple[StageReceipt, ...]
    source_batch_ids: tuple[str, ...]
    artifact_kinds: tuple[str, ...]
    limitations: tuple[str, ...]
    complete: Literal[True]
    coordinator_commitments: tuple[StageCommitmentV1, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run_id")
        _validate_id(self.profile, "profile")
        _validate_id(self.research_pack_id, "research_pack_id")
        _digest(self.submission_digest, "submission_digest")
        _digest(self.workflow_digest, "workflow_digest")
        _bounded_text(self.harness, "harness", 128)
        started = _utc_timestamp(self.started_at, "started_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("run completed_at must not precede started_at")
        if not self.stages:
            raise ValueError("run card requires stage receipts")
        stage_ids = tuple(stage.stage_id for stage in self.stages)
        if len(set(stage_ids)) != len(stage_ids):
            raise ValueError("run card stage receipts must be unique")
        commitment_ids = tuple(item.stage_id for item in self.coordinator_commitments)
        if len(set(commitment_ids)) != len(commitment_ids):
            raise ValueError("run card coordinator commitments must be unique")
        if commitment_ids and commitment_ids != stage_ids:
            raise ValueError("run card coordinator commitments must match stage receipt order exactly")
        if not self.artifact_kinds or len(set(self.artifact_kinds)) != len(self.artifact_kinds):
            raise ValueError("run card artifact kinds must be a non-empty unique sequence")
        if len(set(self.source_batch_ids)) != len(self.source_batch_ids):
            raise ValueError("run card source batch IDs must be unique")
        for source_id in self.source_batch_ids:
            _validate_id(source_id, "source_batch_ids")
        for limitation in self.limitations:
            _bounded_text(limitation, "limitations", 1_000)

    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Hypothesis(StrictModel):
    hypothesis_id: str
    statement: str
    falsification_criteria: str
    expected_observation: str
    horizon_at: str
    created_at: str
    evidence_ids: tuple[str, ...]
    related_hypothesis_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.hypothesis_id, "hypothesis_id")
        _bounded_text(self.statement, "statement", 2_000)
        _bounded_text(self.falsification_criteria, "falsification_criteria", 2_000)
        _bounded_text(self.expected_observation, "expected_observation", 2_000)
        created = _utc_timestamp(self.created_at, "created_at")
        if _utc_timestamp(self.horizon_at, "horizon_at") <= created:
            raise ValueError("hypothesis horizon_at must be later than created_at")
        if self.hypothesis_id in self.related_hypothesis_ids:
            raise ValueError("a hypothesis cannot relate to itself")
        for identifier in (*self.evidence_ids, *self.related_hypothesis_ids):
            _validate_id(identifier, "hypothesis reference")


@dataclass(frozen=True, slots=True)
class HypothesisTransition(StrictModel):
    transition_id: str
    hypothesis_id: str
    from_status: Literal["proposed", "supported", "weakened", "refuted", "inconclusive"] | None
    to_status: Literal["proposed", "supported", "weakened", "refuted", "inconclusive"]
    changed_at: str
    reason: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.transition_id, "transition_id")
        _validate_id(self.hypothesis_id, "hypothesis_id")
        _utc_timestamp(self.changed_at, "changed_at")
        _bounded_text(self.reason, "reason", 2_000)
        if self.from_status == self.to_status:
            raise ValueError("hypothesis transition must change status")
        for evidence_id in self.evidence_ids:
            _validate_id(evidence_id, "evidence_ids")


@dataclass(frozen=True, slots=True)
class HypothesisLedger(StrictModel):
    run_id: str
    hypothesis: Hypothesis
    transitions: tuple[HypothesisTransition, ...]
    final_status: Literal["proposed", "supported", "weakened", "refuted", "inconclusive"]

    def __post_init__(self) -> None:
        _validate_id(self.run_id, "run_id")
        if not self.transitions:
            if self.final_status != "proposed":
                raise ValueError("a hypothesis without transitions must remain proposed")
            return
        status: str | None = None
        previous_at = self.hypothesis.created_at
        seen: set[str] = set()
        for transition in self.transitions:
            if transition.transition_id in seen:
                raise ValueError("hypothesis transition IDs must be unique")
            seen.add(transition.transition_id)
            if transition.hypothesis_id != self.hypothesis.hypothesis_id:
                raise ValueError("transition references a different hypothesis")
            if transition.from_status != status:
                raise ValueError("hypothesis transition chain is not append-only")
            if _utc_timestamp(transition.changed_at, "changed_at") < _utc_timestamp(previous_at, "previous_at"):
                raise ValueError("hypothesis transitions must be chronological")
            status = transition.to_status
            previous_at = transition.changed_at
        if status != self.final_status:
            raise ValueError("final_status must match the last transition")


@dataclass(frozen=True, slots=True)
class ResearchIterationReceipt(StrictModel):
    iteration_id: str
    run_id: str
    hypothesis_ids: tuple[str, ...]
    started_at: str
    completed_at: str
    budget_units: int
    consumed_units: int
    novelty_score: float
    maximum_correlation: float
    decision: Literal["continue", "stop_sufficient", "stop_budget", "stop_no_novelty", "stop_policy"]
    output_digest: str

    def __post_init__(self) -> None:
        _validate_id(self.iteration_id, "iteration_id")
        _validate_id(self.run_id, "run_id")
        if not self.hypothesis_ids:
            raise ValueError("research iteration requires at least one hypothesis")
        started = _utc_timestamp(self.started_at, "started_at")
        completed = _utc_timestamp(self.completed_at, "completed_at")
        if completed < started:
            raise ValueError("iteration completed_at must not precede started_at")
        if self.budget_units < 1 or not 0 <= self.consumed_units <= self.budget_units:
            raise ValueError("consumed_units must be within the positive budget")
        if not 0 <= self.novelty_score <= 1 or not 0 <= self.maximum_correlation <= 1:
            raise ValueError("novelty and correlation scores must be between zero and one")
        _digest(self.output_digest, "output_digest")
