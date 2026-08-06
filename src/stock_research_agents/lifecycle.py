"""Shared durable lifecycle storage for company analytics runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock
from typing import Any, cast

from .company_analytics_v1 import CompanyAnalyticsSubmissionV1, analytics_run_id
from .contracts import reject_secret_shaped_keys
from .memory import ResearchHistoryRepository
from .research_contracts import CompanyResearchRequest
from .research_lab_v1 import StageCommitmentV1
from .serialization import deserialize_run_events
from .state import DEFAULT_STATE_LAYOUT
from .state_write_lock import state_write_lock

LIFECYCLE_SCHEMA_VERSION = "1.0.0"
_RUN_ID_PATTERN = re.compile(r"analytics-[a-f0-9]{12}\Z")
_MAX_LIFECYCLE_RECORD_BYTES = 16_000_000
_MAX_TOTAL_RECEIPTS = 2048
_MAX_EVIDENCE_IDS_PER_RECEIPT = 256
_MAX_RECEIPT_DURATION_MS = 7 * 24 * 60 * 60 * 1000
_MAX_CANCEL_REASON_CHARS = 1000
_SAFE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
_STATUS_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")
_RECEIPT_KINDS = frozenset(
    {"stage_started", "stage_completed", "stage_progress", "tool_started", "tool_completed", "tool_failed", "warning"}
)
_RECEIPT_FIELDS = frozenset(
    {
        "receipt_id",
        "observed_at",
        "kind",
        "stage_id",
        "attempt",
        "capability_id",
        "execution_call_id",
        "status",
        "duration_ms",
        "input_digest",
        "output_digest",
        "evidence_ids",
        "safe_summary",
    }
)
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "workflow_profile",
        "workflow_id",
        "run_id",
        "status",
        "revision",
        "request",
        "topology",
        "system_boundary",
        "research_pack_id",
        "execution_mode",
        "execution_mode_readiness",
        "execution_mode_locally_ready",
        "completed_stage_ids",
        "stage_outputs",
        "stage_commitments",
        "attempts",
        "active_stage_id",
        "active_attempt",
        "receipts",
        "receipt_ids",
        "memory_context",
        "memory_recall",
        "decision_memory_enabled",
        "memory_stage_receipt",
        "memory_write_receipt",
        "final_submission",
        "result_run_id",
        "finalization_completed_at",
        "cancel_reason",
        "cancel_ack_receipt_id",
        "failure",
        "events",
        "created_at",
        "updated_at",
    }
)
_STAGE_FIELDS = frozenset(
    {"id", "ordinal", "role", "objective", "depends_on", "capabilities", "output_refs", "completion_criteria"}
)
_REFERENCE_FIELDS = frozenset({"reference_id", "media_type", "sha256", "byte_length", "summary"})


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _stage_commitment_envelope_digest(output: Mapping[str, object], *, terminal: bool) -> str:
    candidate = _json_copy(dict(output))
    if terminal:
        refs = candidate.get("output_refs")
        if isinstance(refs, dict) and len(refs) == 1:
            submission = next(iter(refs.values()))
            if isinstance(submission, dict):
                run_card = submission.get("run_card")
                if isinstance(run_card, dict):
                    run_card["coordinator_commitments"] = []
                    stages = run_card.get("stages")
                    if isinstance(stages, list):
                        for stage in stages:
                            if isinstance(stage, dict):
                                stage["output_digest"] = "0" * 64
                quality = submission.get("quality_receipt")
                if isinstance(quality, dict) and isinstance(quality.get("stage_digests"), list):
                    quality["stage_digests"] = [
                        [item[0], "0" * 64]
                        for item in quality["stage_digests"]
                        if isinstance(item, list | tuple) and len(item) == 2
                    ]
    return _canonical_digest(candidate)


def is_lifecycle_run_id(run_id: object) -> bool:
    """Return whether a run ID can belong to the durable analytics lifecycle."""

    return isinstance(run_id, str) and _RUN_ID_PATTERN.fullmatch(run_id) is not None


class LifecycleStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class RevisionConflict(ValueError):
    """Raised when a caller attempts to mutate a stale lifecycle revision."""


@dataclass(frozen=True, slots=True)
class LifecycleRecordV1:
    """Validated aggregate for the stable lifecycle-record wire representation."""

    run_id: str
    revision: int
    status: LifecycleStatus
    created_at: str
    updated_at: str
    _payload: dict[str, Any]

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_run_id: str | None = None,
    ) -> LifecycleRecordV1:
        payload = _json_copy(value)
        if not isinstance(payload, dict):
            raise ValueError("lifecycle record must be a JSON object")
        if payload.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
            raise ValueError(f"lifecycle record schema_version must be {LIFECYCLE_SCHEMA_VERSION}")
        run_id = payload.get("run_id")
        if not is_lifecycle_run_id(run_id):
            raise ValueError("lifecycle run_id must match analytics- followed by 12 lowercase hexadecimal characters")
        if expected_run_id is not None and run_id != expected_run_id:
            raise ValueError(f"invalid persisted lifecycle record: {expected_run_id}")
        revision = payload.get("revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("lifecycle revision must be a non-negative integer")
        raw_status = payload.get("status")
        if not isinstance(raw_status, str):
            raise ValueError("lifecycle status is invalid")
        try:
            status = LifecycleStatus(raw_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("lifecycle status is invalid") from exc
        created_at = cls._timestamp(payload.get("created_at"), "created_at")
        updated_at = cls._timestamp(payload.get("updated_at"), "updated_at")
        if datetime.fromisoformat(updated_at) < datetime.fromisoformat(created_at):
            raise ValueError("lifecycle updated_at cannot precede created_at")
        cls._validate_fields(payload)
        cls._validate_identity(payload)
        cls._validate_request(payload)
        cls._validate_topology(payload)
        cls._validate_supporting_state(payload)
        cls._validate_state(payload, status)
        cls._validate_events(payload, str(run_id))
        return cls(str(run_id), revision, status, created_at, updated_at, payload)

    @staticmethod
    def _validate_fields(payload: Mapping[str, Any]) -> None:
        fields = set(payload)
        unknown = sorted(fields - _RECORD_FIELDS)
        missing = sorted(_RECORD_FIELDS - fields)
        if unknown or missing:
            raise ValueError(f"lifecycle record fields are invalid: missing={missing}, unknown={unknown}")

    @staticmethod
    def _validate_request(payload: Mapping[str, Any]) -> None:
        try:
            CompanyResearchRequest.from_dict(payload.get("request"))
        except (TypeError, ValueError) as exc:
            raise ValueError("lifecycle request is invalid") from exc

    @staticmethod
    def _timestamp(value: object, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"lifecycle {field} must be a timezone-aware ISO-8601 timestamp")
        return value

    @staticmethod
    def _validate_identity(payload: Mapping[str, Any]) -> None:
        for field in ("workflow_profile", "workflow_id"):
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise ValueError(f"lifecycle {field} must be a non-empty string")

    @staticmethod
    def _validate_topology(payload: Mapping[str, Any]) -> None:
        topology = payload.get("topology")
        if (
            not isinstance(topology, Mapping)
            or set(topology) != {"stages", "terminal_stage"}
            or not isinstance(topology.get("stages"), list)
        ):
            raise ValueError("lifecycle topology.stages must be an array")
        stages = topology["stages"]
        if any(not isinstance(stage, Mapping) or set(stage) != _STAGE_FIELDS for stage in stages):
            raise ValueError("lifecycle topology stages have invalid fields")
        stage_ids = [stage.get("id") for stage in stages if isinstance(stage, Mapping)]
        invalid_stage_id = any(not isinstance(item, str) or not item for item in stage_ids)
        if len(stage_ids) != len(stages) or invalid_stage_id:
            raise ValueError("lifecycle topology stages must have non-empty string IDs")
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("lifecycle topology stage IDs must be unique")
        for ordinal, stage in enumerate(stages, start=1):
            assert isinstance(stage, Mapping)
            if stage.get("ordinal") != ordinal:
                raise ValueError("lifecycle topology stage ordinals must be contiguous")
            for field in ("role", "objective"):
                if not isinstance(stage.get(field), str) or not stage[field]:
                    raise ValueError(f"lifecycle topology stage {field} must be a non-empty string")
            for field in ("depends_on", "capabilities", "output_refs", "completion_criteria"):
                values = stage.get(field)
                if not isinstance(values, list) or any(not isinstance(item, str) or not item for item in values):
                    raise ValueError(f"lifecycle topology stage {field} must be an array of non-empty strings")
            if any(dependency not in stage_ids[: ordinal - 1] for dependency in stage["depends_on"]):
                raise ValueError("lifecycle topology dependencies must reference earlier stages")
        terminal_stage = topology.get("terminal_stage")
        if terminal_stage != (stage_ids[-1] if stage_ids else None):
            raise ValueError("lifecycle topology terminal_stage must reference the final stage")
        completed = payload.get("completed_stage_ids")
        if not isinstance(completed, list) or any(not isinstance(item, str) for item in completed):
            raise ValueError("lifecycle completed_stage_ids must be an array of strings")
        if len(completed) != len(set(completed)) or completed != stage_ids[: len(completed)]:
            raise ValueError("lifecycle completed stages must be a unique topology prefix")
        active_stage = payload.get("active_stage_id")
        active_attempt = payload.get("active_attempt")
        if active_stage is None:
            if active_attempt is not None:
                raise ValueError("lifecycle active_attempt requires active_stage_id")
        elif active_stage not in stage_ids or active_stage in completed:
            raise ValueError("lifecycle active_stage_id must reference an incomplete topology stage")
        if active_attempt is not None and (
            not isinstance(active_attempt, int) or isinstance(active_attempt, bool) or active_attempt < 1
        ):
            raise ValueError("lifecycle active_attempt must be a positive integer")

    @staticmethod
    def _validate_supporting_state(payload: Mapping[str, Any]) -> None:
        for field in ("research_pack_id", "execution_mode", "execution_mode_readiness"):
            if not isinstance(payload.get(field), str) or not payload[field]:
                raise ValueError(f"lifecycle {field} must be a non-empty string")
        for field in ("execution_mode_locally_ready", "decision_memory_enabled"):
            if not isinstance(payload.get(field), bool):
                raise ValueError(f"lifecycle {field} must be a boolean")
        boundary = payload.get("system_boundary")
        if not isinstance(boundary, Mapping) or set(boundary) != {"caller_owns", "core_owns", "forbidden"}:
            raise ValueError("lifecycle system_boundary has invalid fields")
        if any(
            not isinstance(boundary[field], list)
            or any(not isinstance(item, str) or not item for item in boundary[field])
            for field in boundary
        ):
            raise ValueError("lifecycle system_boundary values must be arrays of non-empty strings")
        reject_secret_shaped_keys(payload.get("memory_context"), ("memory_context",))
        memory_context = payload.get("memory_context")
        if memory_context is not None and not isinstance(memory_context, dict):
            raise ValueError("lifecycle memory_context must be an object or null")
        LifecycleRecordV1._validate_memory_recall(payload.get("memory_recall"))
        LifecycleRecordV1._validate_memory_receipt(payload.get("memory_stage_receipt"), "memory_stage_receipt")
        LifecycleRecordV1._validate_memory_receipt(payload.get("memory_write_receipt"), "memory_write_receipt")
        final_submission = payload.get("final_submission")
        if final_submission is not None:
            try:
                CompanyAnalyticsSubmissionV1.from_dict(final_submission)
            except (TypeError, ValueError) as exc:
                raise ValueError("lifecycle final_submission is invalid") from exc
        if payload.get("failure") is not None:
            raise ValueError("lifecycle failure must be null for the current schema")
        cancel_reason = payload.get("cancel_reason")
        if cancel_reason is not None and (
            not isinstance(cancel_reason, str)
            or not cancel_reason.strip()
            or cancel_reason != cancel_reason.strip()
            or len(cancel_reason) > _MAX_CANCEL_REASON_CHARS
        ):
            raise ValueError(
                f"lifecycle cancel_reason must contain 1 to {_MAX_CANCEL_REASON_CHARS} non-whitespace characters"
            )
        cancel_ack_receipt_id = payload.get("cancel_ack_receipt_id")
        if cancel_ack_receipt_id is not None and (
            not isinstance(cancel_ack_receipt_id, str) or _SAFE_ID_PATTERN.fullmatch(cancel_ack_receipt_id) is None
        ):
            raise ValueError("lifecycle cancel_ack_receipt_id must be a safe identifier or null")

        stages = payload["topology"]["stages"]
        stage_ids = [str(stage["id"]) for stage in stages]
        completed = payload["completed_stage_ids"]
        attempts = payload.get("attempts")
        if not isinstance(attempts, dict) or any(
            key not in stage_ids or not isinstance(value, int) or isinstance(value, bool) or value < 1
            for key, value in attempts.items()
        ):
            raise ValueError("lifecycle attempts must map topology stage IDs to positive integers")
        if any(stage_id not in attempts for stage_id in completed):
            raise ValueError("lifecycle attempts must include every completed stage")

        outputs = payload.get("stage_outputs")
        if not isinstance(outputs, list) or len(outputs) != len(completed):
            raise ValueError("lifecycle stage_outputs must align with completed_stage_ids")
        for stage_id, output in zip(completed, outputs, strict=True):
            if not isinstance(output, Mapping) or set(output) != {"schema_version", "stage_id", "output_refs"}:
                raise ValueError("lifecycle stage output has invalid fields")
            if output.get("schema_version") != LIFECYCLE_SCHEMA_VERSION or output.get("stage_id") != stage_id:
                raise ValueError("lifecycle stage output identity is invalid")
            refs = output.get("output_refs")
            if not isinstance(refs, Mapping) or not refs:
                raise ValueError("lifecycle stage output_refs must be a non-empty object")
            topology_stage = next(stage for stage in stages if stage["id"] == stage_id)
            if set(refs) != set(topology_stage["output_refs"]):
                raise ValueError("lifecycle stage output_refs must match the topology")
            if stage_id != payload["topology"]["terminal_stage"]:
                for descriptor in refs.values():
                    if not isinstance(descriptor, Mapping) or set(descriptor) != _REFERENCE_FIELDS:
                        raise ValueError("lifecycle nonterminal output reference has invalid fields")
                    if (
                        not isinstance(descriptor["reference_id"], str)
                        or _SAFE_ID_PATTERN.fullmatch(descriptor["reference_id"]) is None
                        or not isinstance(descriptor["media_type"], str)
                        or "/" not in descriptor["media_type"]
                        or not isinstance(descriptor["sha256"], str)
                        or _DIGEST_PATTERN.fullmatch(descriptor["sha256"]) is None
                        or not isinstance(descriptor["byte_length"], int)
                        or isinstance(descriptor["byte_length"], bool)
                        or descriptor["byte_length"] < 0
                        or not isinstance(descriptor["summary"], str)
                        or not descriptor["summary"]
                    ):
                        raise ValueError("lifecycle nonterminal output reference is invalid")

        commitments = payload.get("stage_commitments")
        if not isinstance(commitments, list) or len(commitments) != len(completed):
            raise ValueError("lifecycle stage_commitments must align with completed_stage_ids")
        parsed_commitments = tuple(StageCommitmentV1.from_dict(item) for item in commitments)
        if any(item.stage_id != stage_id for item, stage_id in zip(parsed_commitments, completed, strict=True)):
            raise ValueError("lifecycle stage_commitments must align with completed_stage_ids")
        LifecycleRecordV1._validate_stage_commitment_digests(
            payload,
            tuple(outputs),
            parsed_commitments,
        )

        receipts = payload.get("receipts")
        receipt_ids = payload.get("receipt_ids")
        if not isinstance(receipts, list) or not isinstance(receipt_ids, list):
            raise ValueError("lifecycle receipts and receipt_ids must be arrays")
        if len(receipts) > _MAX_TOTAL_RECEIPTS:
            raise ValueError(f"lifecycle receipts cannot exceed {_MAX_TOTAL_RECEIPTS} items")
        validated_ids: list[str] = []
        for receipt in receipts:
            if not isinstance(receipt, Mapping) or set(receipt) - _RECEIPT_FIELDS:
                raise ValueError("lifecycle receipt has invalid fields")
            receipt_id = receipt.get("receipt_id")
            kind = receipt.get("kind")
            if not isinstance(receipt_id, str) or _SAFE_ID_PATTERN.fullmatch(receipt_id) is None:
                raise ValueError("lifecycle receipt_id is invalid")
            if kind not in _RECEIPT_KINDS:
                raise ValueError("lifecycle receipt kind is invalid")
            observed_at = receipt.get("observed_at")
            if observed_at is not None:
                LifecycleRecordV1._timestamp(observed_at, "receipt.observed_at")
            stage_id = receipt.get("stage_id")
            if stage_id is not None and stage_id not in stage_ids:
                raise ValueError("lifecycle receipt stage_id is invalid")
            for field in ("stage_id", "capability_id", "execution_call_id"):
                identifier = receipt.get(field)
                if identifier is not None and (
                    not isinstance(identifier, str) or _SAFE_ID_PATTERN.fullmatch(identifier) is None
                ):
                    raise ValueError(f"lifecycle receipt {field} is invalid")
            capability_id = receipt.get("capability_id")
            if capability_id is not None:
                stage = next((item for item in stages if item["id"] == stage_id), None)
                if stage is None or capability_id not in stage["capabilities"]:
                    raise ValueError("lifecycle receipt capability_id is invalid for its stage")
            attempt = receipt.get("attempt")
            if attempt is not None and (not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1):
                raise ValueError("lifecycle receipt attempt is invalid")
            status = receipt.get("status")
            if status is not None and (not isinstance(status, str) or _STATUS_PATTERN.fullmatch(status) is None):
                raise ValueError("lifecycle receipt status is invalid")
            duration = receipt.get("duration_ms")
            if duration is not None and (
                not isinstance(duration, int)
                or isinstance(duration, bool)
                or not 0 <= duration <= _MAX_RECEIPT_DURATION_MS
            ):
                raise ValueError("lifecycle receipt duration_ms is invalid")
            for field in ("input_digest", "output_digest"):
                digest = receipt.get(field)
                if digest is not None and (not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None):
                    raise ValueError(f"lifecycle receipt {field} is invalid")
            evidence_ids = receipt.get("evidence_ids")
            if evidence_ids is not None and (
                not isinstance(evidence_ids, list)
                or len(evidence_ids) > _MAX_EVIDENCE_IDS_PER_RECEIPT
                or any(not isinstance(item, str) or _SAFE_ID_PATTERN.fullmatch(item) is None for item in evidence_ids)
            ):
                raise ValueError("lifecycle receipt evidence_ids are invalid")
            safe_summary = receipt.get("safe_summary")
            if safe_summary is not None and (not isinstance(safe_summary, str) or len(safe_summary) > 1000):
                raise ValueError("lifecycle receipt safe_summary is invalid")
            if kind in {"stage_started", "stage_completed"} and (not isinstance(stage_id, str) or attempt is None):
                raise ValueError(f"lifecycle {kind} receipt requires stage_id and attempt")
            if kind == "stage_completed" and receipt.get("output_digest") is None:
                raise ValueError("lifecycle stage_completed receipt requires output_digest")
            validated_ids.append(receipt_id)
        if receipt_ids != validated_ids or len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("lifecycle receipt_ids must exactly index unique receipts")

    @staticmethod
    def _validate_stage_commitment_digests(
        payload: Mapping[str, Any],
        outputs: tuple[Mapping[str, object], ...],
        commitments: tuple[StageCommitmentV1, ...],
    ) -> None:
        terminal_stage = payload["topology"]["terminal_stage"]
        topology_by_id = {stage["id"]: stage for stage in payload["topology"]["stages"]}
        attempts = payload["attempts"]
        for output, commitment in zip(outputs, commitments, strict=True):
            stage_id = commitment.stage_id
            envelope_digest = _stage_commitment_envelope_digest(
                output,
                terminal=stage_id == terminal_stage,
            )
            if commitment.envelope_digest != envelope_digest:
                raise ValueError(
                    f"lifecycle stage_commitments envelope_digest does not match stage_output for {stage_id}"
                )
            receipt = {
                "schema_version": "coordinator-stage-commit.v1",
                "stage_id": stage_id,
                "ordinal": topology_by_id[stage_id]["ordinal"],
                "attempt": attempts[stage_id],
                "envelope_digest": envelope_digest,
            }
            if commitment.receipt_digest != _canonical_digest(receipt):
                raise ValueError(
                    f"lifecycle stage_commitments receipt_digest does not match stage identity for {stage_id}"
                )

    @staticmethod
    def _validate_final_submission_binding(
        payload: Mapping[str, Any],
        commitments: tuple[StageCommitmentV1, ...],
    ) -> None:
        final_value = payload.get("final_submission")
        if final_value is None:
            return
        final_submission = CompanyAnalyticsSubmissionV1.from_dict(final_value)
        if _json_copy(final_submission.company_research.request.to_dict()) != payload.get("request"):
            raise ValueError("lifecycle final_submission request must exactly match the lifecycle request")
        if final_submission.run_card.execution_mode != payload.get("execution_mode"):
            raise ValueError("lifecycle final_submission execution_mode must match the lifecycle execution_mode")
        if final_submission.run_card.coordinator_commitments != commitments:
            raise ValueError("lifecycle final_submission commitments must match lifecycle stage_commitments")

        outputs = payload["stage_outputs"]
        terminal_output = outputs[-1] if outputs else None
        refs = terminal_output.get("output_refs") if isinstance(terminal_output, Mapping) else None
        if not isinstance(refs, Mapping) or len(refs) != 1:
            raise ValueError("lifecycle terminal stage output must contain exactly one submission")
        terminal_value = next(iter(refs.values()))
        try:
            terminal_submission = CompanyAnalyticsSubmissionV1.from_dict(terminal_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("lifecycle terminal stage output submission is invalid") from exc
        if _json_copy(terminal_submission.company_research.request.to_dict()) != payload.get("request"):
            raise ValueError("lifecycle terminal stage output request must exactly match the lifecycle request")
        if terminal_submission.run_card.execution_mode != payload.get("execution_mode"):
            raise ValueError("lifecycle terminal stage output execution_mode must match the lifecycle execution_mode")

        rebound = cast(dict[str, Any], terminal_submission.to_dict())
        rebound["run_card"]["coordinator_commitments"] = [item.to_dict() for item in commitments]
        committed_digests = {item.stage_id: item.envelope_digest for item in commitments}
        rebound_stages = rebound["run_card"]["stages"]
        for stage_receipt in rebound_stages:
            stage_receipt["output_digest"] = committed_digests[stage_receipt["stage_id"]]
        rebound["quality_receipt"]["stage_digests"] = [
            {"stage_id": stage_receipt["stage_id"], "sha256": stage_receipt["output_digest"]}
            for stage_receipt in rebound_stages
        ]
        previous_run_id = terminal_submission.run_card.run_id
        rebound_run_id = analytics_run_id(rebound)
        rebound = LifecycleRecordV1._rebind_run_id(rebound, previous_run_id, rebound_run_id)
        expected = CompanyAnalyticsSubmissionV1.from_dict(rebound).to_dict()
        if _json_copy(final_submission.to_dict()) != _json_copy(expected):
            raise ValueError("lifecycle final_submission must match the committed terminal stage output")

    @staticmethod
    def _rebind_run_id(value: object, previous_run_id: str, run_id: str) -> Any:
        if isinstance(value, dict):
            return {key: LifecycleRecordV1._rebind_run_id(item, previous_run_id, run_id) for key, item in value.items()}
        if isinstance(value, list):
            return [LifecycleRecordV1._rebind_run_id(item, previous_run_id, run_id) for item in value]
        if isinstance(value, str):
            return value.replace(previous_run_id, run_id)
        return value

    @staticmethod
    def _validate_memory_receipt(value: object, field: str) -> None:
        if value is None:
            return
        expected = {"schema_version", "operation", "memory_id", "run_id", "symbol", "persisted_at", "outcome_id"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError(f"lifecycle {field} is not a DecisionMemoryReceipt")
        if value.get("schema_version") != LIFECYCLE_SCHEMA_VERSION:
            raise ValueError(f"lifecycle {field} has an unsupported schema_version")
        operation = value.get("operation")
        expected_operation = "decision_staged" if field == "memory_stage_receipt" else "decision_appended"
        if operation != expected_operation:
            raise ValueError(f"lifecycle {field} has an invalid operation")
        for key in ("memory_id", "run_id", "symbol"):
            item = value.get(key)
            if not isinstance(item, str) or not item or len(item) > 128:
                raise ValueError(f"lifecycle {field}.{key} must be a bounded non-empty string")
        LifecycleRecordV1._timestamp(value.get("persisted_at"), f"{field}.persisted_at")
        outcome_id = value.get("outcome_id")
        if outcome_id is not None and (not isinstance(outcome_id, str) or not outcome_id or len(outcome_id) > 128):
            raise ValueError(f"lifecycle {field}.outcome_id must be a bounded string or null")

    @staticmethod
    def _validate_memory_recall(value: object) -> None:
        if value is None:
            return
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "symbol",
            "same_symbol",
            "cross_symbol",
        }:
            raise ValueError("lifecycle memory_recall has invalid fields")
        if value.get("schema_version") != LIFECYCLE_SCHEMA_VERSION or not isinstance(value.get("symbol"), str):
            raise ValueError("lifecycle memory_recall identity is invalid")
        for collection_name in ("same_symbol", "cross_symbol"):
            entries = value.get(collection_name)
            if not isinstance(entries, list):
                raise ValueError(f"lifecycle memory_recall.{collection_name} must be an array")
            for entry in entries:
                LifecycleRecordV1._validate_memory_entry(entry)

    @staticmethod
    def _validate_memory_entry(value: object) -> None:
        fields = {"memory_id", "run_id", "symbol", "as_of_date", "decision", "context", "created_at", "outcomes"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("lifecycle memory_recall entry has invalid fields")
        for field in ("memory_id", "run_id", "symbol", "as_of_date"):
            if not isinstance(value.get(field), str) or not value[field]:
                raise ValueError(f"lifecycle memory_recall entry {field} must be a non-empty string")
        LifecycleRecordV1._timestamp(value.get("created_at"), "memory_recall.created_at")
        for field in ("decision", "context"):
            if not isinstance(value.get(field), dict):
                raise ValueError(f"lifecycle memory_recall entry {field} must be an object")
        outcomes = value.get("outcomes")
        if not isinstance(outcomes, list):
            raise ValueError("lifecycle memory_recall entry outcomes must be an array")
        for outcome in outcomes:
            if not isinstance(outcome, Mapping) or set(outcome) != {
                "outcome_id",
                "outcome",
                "reflection",
                "observed_at",
            }:
                raise ValueError("lifecycle memory_recall outcome has invalid fields")
            for field in ("outcome_id", "reflection"):
                if not isinstance(outcome.get(field), str) or not outcome[field]:
                    raise ValueError(f"lifecycle memory_recall outcome {field} must be a non-empty string")
            LifecycleRecordV1._timestamp(outcome.get("observed_at"), "memory_recall.outcome.observed_at")

    @staticmethod
    def _validate_state(payload: Mapping[str, Any], status: LifecycleStatus) -> None:
        final_submission = payload.get("final_submission")
        finalization_at = payload.get("finalization_completed_at")
        result_run_id = payload.get("result_run_id")
        completed_stage_ids = payload["completed_stage_ids"]
        topology_stage_ids = [stage["id"] for stage in payload["topology"]["stages"]]
        terminal_stage = payload["topology"]["terminal_stage"]

        if final_submission is not None and terminal_stage not in completed_stage_ids:
            raise ValueError("lifecycle final_submission requires the terminal stage to be completed")
        if status in {LifecycleStatus.FINALIZING, LifecycleStatus.COMPLETED}:
            if not isinstance(final_submission, dict):
                raise ValueError("finalizing lifecycle records require final_submission")
            LifecycleRecordV1._timestamp(finalization_at, "finalization_completed_at")
            if completed_stage_ids != topology_stage_ids:
                raise ValueError("finalizing lifecycle records require every stage to be completed")
            if payload.get("active_stage_id") is not None or payload.get("active_attempt") is not None:
                raise ValueError("finalizing lifecycle records cannot retain an active stage")
        elif finalization_at is not None:
            raise ValueError("lifecycle finalization_completed_at requires finalizing or completed status")

        if status is LifecycleStatus.COMPLETED:
            if not isinstance(result_run_id, str):
                raise ValueError("completed lifecycle records require result_run_id")
            assert isinstance(final_submission, dict)
            if result_run_id != analytics_run_id(final_submission):
                raise ValueError("completed lifecycle result_run_id must match final_submission")
        elif result_run_id is not None:
            raise ValueError("lifecycle result_run_id requires completed status")
        if final_submission is not None:
            commitments = tuple(StageCommitmentV1.from_dict(item) for item in payload["stage_commitments"])
            LifecycleRecordV1._validate_final_submission_binding(payload, commitments)

        cancel_reason = payload.get("cancel_reason")
        cancel_ack_receipt_id = payload.get("cancel_ack_receipt_id")
        if status in {LifecycleStatus.CANCEL_REQUESTED, LifecycleStatus.CANCELLED}:
            if not isinstance(cancel_reason, str):
                raise ValueError("cancelled lifecycle states require cancel_reason")
        elif cancel_reason is not None:
            raise ValueError("lifecycle cancel_reason requires cancel_requested or cancelled status")
        if status is LifecycleStatus.CANCELLED:
            if not isinstance(cancel_ack_receipt_id, str):
                raise ValueError("cancelled lifecycle records require cancel_ack_receipt_id")
        elif cancel_ack_receipt_id is not None:
            raise ValueError("lifecycle cancel_ack_receipt_id requires cancelled status")

        if status is LifecycleStatus.PREPARED and (
            completed_stage_ids
            or payload["stage_outputs"]
            or payload["stage_commitments"]
            or payload["attempts"]
            or payload["active_stage_id"] is not None
            or payload["active_attempt"] is not None
            or payload["receipts"]
            or payload["receipt_ids"]
            or final_submission is not None
        ):
            raise ValueError("prepared lifecycle records cannot contain execution progress")

    @staticmethod
    def _validate_events(payload: Mapping[str, Any], run_id: str) -> None:
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("lifecycle events must be an array")
        typed_events = deserialize_run_events(json.dumps(events, ensure_ascii=False, allow_nan=False))
        for sequence, event in enumerate(typed_events, start=1):
            if event.run_id != run_id or event.sequence != sequence:
                raise ValueError("lifecycle events must have contiguous sequence values for run_id")

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._payload)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_copy(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


class LifecycleStore:
    """In-memory or SQLite/WAL lifecycle records with optimistic revisions."""

    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        *,
        _state_dir_factory: Callable[[], Path] | None = None,
    ) -> None:
        if state_dir is not None and _state_dir_factory is not None:
            raise ValueError("state_dir and _state_dir_factory are mutually exclusive")
        self._lock = RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._configured_state_dir = Path(state_dir).expanduser() if state_dir is not None else None
        self._state_dir_factory = _state_dir_factory
        self._resolved_state_dir: Path | None = None

    @property
    def state_dir(self) -> Path | None:
        if self._resolved_state_dir is None:
            self._resolved_state_dir = (
                self._configured_state_dir
                if self._configured_state_dir is not None
                else self._state_dir_factory()
                if self._state_dir_factory is not None
                else None
            )
        return self._resolved_state_dir

    @property
    def database_path(self) -> Path | None:
        return self.state_dir / "lifecycle.sqlite3" if self.state_dir is not None else None

    def _connect(self) -> sqlite3.Connection:
        database_path = self.database_path
        if database_path is None:
            raise RuntimeError("in-memory lifecycle stores do not have a SQLite connection")
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(database_path.parent, 0o700)
        connection = sqlite3.connect(database_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lifecycle_runs (
                run_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                record_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        os.chmod(database_path, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database_path}{suffix}")
            if sidecar.exists():
                os.chmod(sidecar, 0o600)
        return connection

    @staticmethod
    def _validate_run_id(run_id: str) -> str:
        if not is_lifecycle_run_id(run_id):
            raise ValueError("lifecycle run_id must match analytics- followed by 12 lowercase hexadecimal characters")
        return run_id

    @staticmethod
    def _validate_record_size(record: Mapping[str, Any]) -> None:
        if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
            raise ValueError("lifecycle record exceeds the 16 MB storage limit")

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        aggregate = LifecycleRecordV1.from_mapping(record)
        candidate = aggregate.to_dict()
        self._validate_record_size(candidate)
        run_id = aggregate.run_id
        if aggregate.revision != 0:
            raise ValueError("new lifecycle records must start at revision 0")
        with state_write_lock(self.state_dir), self._lock:
            if self.database_path is None:
                if run_id in self._records:
                    raise ValueError(f"lifecycle run already exists: {run_id}")
                self._records[run_id] = candidate
                return deepcopy(candidate)
            connection = self._connect()
            try:
                try:
                    connection.execute(
                        "INSERT INTO lifecycle_runs(run_id, revision, record_json, updated_at) VALUES (?, ?, ?, ?)",
                        (run_id, 0, json.dumps(candidate, sort_keys=True), candidate["updated_at"]),
                    )
                    connection.commit()
                except sqlite3.IntegrityError as exc:
                    connection.rollback()
                    raise ValueError(f"lifecycle run already exists: {run_id}") from exc
            finally:
                connection.close()
        return deepcopy(candidate)

    def get(self, run_id: str) -> dict[str, Any] | None:
        safe_run_id = self._validate_run_id(run_id)
        with self._lock:
            if self.database_path is None:
                record = self._records.get(safe_run_id)
                if record is None:
                    return None
                return LifecycleRecordV1.from_mapping(record, expected_run_id=safe_run_id).to_dict()
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT revision, record_json FROM lifecycle_runs WHERE run_id = ?", (safe_run_id,)
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return None
        value = json.loads(row[1])
        if not isinstance(value, dict):
            raise ValueError(f"invalid persisted lifecycle record: {safe_run_id}")
        aggregate = LifecycleRecordV1.from_mapping(value, expected_run_id=safe_run_id)
        if aggregate.revision != int(row[0]):
            raise ValueError(f"invalid persisted lifecycle revision: {safe_run_id}")
        return aggregate.to_dict()

    def update(
        self,
        run_id: str,
        expected_revision: int,
        mutation: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        safe_run_id = self._validate_run_id(run_id)
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        with state_write_lock(self.state_dir), self._lock:
            if self.database_path is None:
                original = self._records.get(safe_run_id)
                if original is None:
                    raise KeyError(f"unknown lifecycle run: {safe_run_id}")
                if original["revision"] != expected_revision:
                    raise RevisionConflict(
                        f"revision conflict for {safe_run_id}: expected {expected_revision}, "
                        f"current {original['revision']}"
                    )
                candidate = deepcopy(original)
                mutation(candidate)
                candidate["revision"] = expected_revision + 1
                candidate["updated_at"] = _utc_now()
                validated = LifecycleRecordV1.from_mapping(candidate, expected_run_id=safe_run_id).to_dict()
                self._validate_record_size(validated)
                self._records[safe_run_id] = validated
                return deepcopy(validated)

            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT revision, record_json FROM lifecycle_runs WHERE run_id = ?", (safe_run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown lifecycle run: {safe_run_id}")
                current_revision = int(row[0])
                if current_revision != expected_revision:
                    raise RevisionConflict(
                        f"revision conflict for {safe_run_id}: expected {expected_revision}, current {current_revision}"
                    )
                candidate = json.loads(row[1])
                mutation(candidate)
                candidate["revision"] = expected_revision + 1
                candidate["updated_at"] = _utc_now()
                validated = LifecycleRecordV1.from_mapping(candidate, expected_run_id=safe_run_id).to_dict()
                encoded = json.dumps(validated, ensure_ascii=False, allow_nan=False, sort_keys=True)
                if len(encoded.encode("utf-8")) > _MAX_LIFECYCLE_RECORD_BYTES:
                    raise ValueError("lifecycle record exceeds the 16 MB storage limit")
                cursor = connection.execute(
                    """
                    UPDATE lifecycle_runs
                    SET revision = ?, record_json = ?, updated_at = ?
                    WHERE run_id = ? AND revision = ?
                    """,
                    (validated["revision"], encoded, validated["updated_at"], safe_run_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise RevisionConflict(f"concurrent lifecycle update for {safe_run_id}")
                connection.commit()
                return validated
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()


LIFECYCLE_STORE = LifecycleStore(_state_dir_factory=lambda: DEFAULT_STATE_LAYOUT.root)


def default_decision_memory_store() -> ResearchHistoryRepository:
    """Return the shared durable memory store used by analytics lifecycle adapters."""

    return ResearchHistoryRepository(DEFAULT_STATE_LAYOUT.memory_database)
