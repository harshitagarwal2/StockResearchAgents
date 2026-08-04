"""Fail-closed verification for the legacy-executor removal decision."""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import subprocess
import tomllib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .workflow import LEGACY_TRANSITION_MANIFEST, load_legacy_transition_manifest

EVIDENCE_INDEX_ID = "tradingagents.legacy-removal-evidence.v1"
ARTIFACT_SCHEMA_ID = "tradingagents.legacy-removal-gate-evidence.v1"
DEFAULT_EVIDENCE_INDEX = Path("evidence/legacy-removal-evidence.v1.json")
HMAC_TRUST_ROOTS_ID = "tradingagents.legacy-removal-hmac-trust-roots.v1"
DEFAULT_TRUSTED_SIGNERS = frozenset({"portable-release-maintainers"})
LOCAL_GATES = frozenset(
    {
        "parity_ledger",
        "python_cli_mcp_ui_equivalence",
        "saved_result_migration",
    }
)
OPERATIONAL_GATES = frozenset(
    {
        "source_contracts_and_concrete_adapter_mcp",
        "deterministic_dual_run_semantic_conformance",
        "representative_live_and_failure_matrix",
    }
)
RELEASE_GATES = frozenset({"published_deprecation_release", "major_version_boundary"})
EXTERNAL_GATES = OPERATIONAL_GATES | RELEASE_GATES

_INDEX_KEYS = {"schema_version", "id", "records"}
_RECORD_KEYS = {"gate_id", "artifact", "producing_commit", "verified_at", "sign_offs"}
_ARTIFACT_REF_KEYS = {"path", "sha256", "schema"}
_SIGN_OFF_KEYS = {"signer", "role", "attestation"}
_CLAIM_KEYS = {"required_evidence", "artifacts"}
_CLAIM_ARTIFACT_KEYS = {"path", "sha256"}
_ARTIFACT_KEYS = {
    "schema_version",
    "id",
    "gate_id",
    "evidence_kind",
    "result",
    "producing_commit",
    "generated_at",
    "claims",
}


class AttestationVerifier(Protocol):
    """Authentication boundary supplied by release infrastructure."""

    def verify(
        self,
        *,
        statement: bytes,
        attestation: str,
        trust_root: object,
    ) -> bool:
        """Return true only when ``attestation`` authenticates ``statement``."""


class HmacSha256AttestationVerifier:
    """Verify canonical statements with signer-specific HMAC-SHA256 keys."""

    def verify(
        self,
        *,
        statement: bytes,
        attestation: str,
        trust_root: object,
    ) -> bool:
        if not isinstance(trust_root, str | bytes):
            raise TypeError("HMAC trust roots must be strings or bytes")
        key = trust_root.encode("utf-8") if isinstance(trust_root, str) else trust_root
        if not key:
            raise ValueError("HMAC trust roots must not be empty")
        prefix = "hmac-sha256:"
        if not attestation.startswith(prefix):
            return False
        supplied = attestation.removeprefix(prefix)
        expected = hmac.new(key, statement, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)


def load_hmac_trust_roots(path: str | Path) -> dict[str, str]:
    """Load the strict signer-to-secret boundary used by release automation."""
    raw = _load_json(Path(path), "HMAC trust roots")
    _exact_keys(raw, {"schema_version", "id", "signers"}, "HMAC trust roots")
    if raw["schema_version"] != "1.0.0" or raw["id"] != HMAC_TRUST_ROOTS_ID:
        raise ValueError("unexpected HMAC trust-roots identity")
    signers = _object(raw["signers"], "HMAC trust-root signers")
    if not signers:
        raise ValueError("HMAC trust roots require at least one signer")
    return {signer: _text(secret, f"HMAC trust root for {signer!r}") for signer, secret in signers.items()}


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} keys must be exactly {sorted(expected)}")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _timestamp(value: object, label: str) -> datetime:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load {label}: {exc}") from exc


def _safe_repo_file(repo_root: Path, relative: object, label: str) -> Path:
    value = Path(_text(relative, label))
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"{label} must be a traversal-free repository-relative path")
    root = repo_root.resolve(strict=True)
    candidate = root.joinpath(value)
    current = root
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} does not exist") from exc
    if resolved.parent != root and root not in resolved.parents:
        raise ValueError(f"{label} escapes the repository")
    if not resolved.is_file():
        raise ValueError(f"{label} must resolve to a regular file")
    return resolved


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"cannot inspect repository state with git {' '.join(args)}")
    return result.stdout.strip()


def _verify_commit(repo_root: Path, commit: object) -> str:
    value = _text(commit, "producing_commit")
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("producing_commit must be a full lowercase Git commit")
    head = _git_output(repo_root, "rev-parse", "HEAD")
    if value != head:
        raise ValueError("producing_commit must exactly match HEAD")
    status = _git_output(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ValueError("repository worktree must be clean")
    return value


def canonical_attestation_statement(
    *,
    gate_id: str,
    artifact: Mapping[str, object],
    producing_commit: str,
    verified_at: str,
    signer: str,
    role: str,
) -> bytes:
    """Build the canonical statement authenticated by one evidence sign-off."""
    return json.dumps(
        {
            "artifact": dict(artifact),
            "gate_id": gate_id,
            "producing_commit": producing_commit,
            "role": role,
            "signer": signer,
            "verified_at": verified_at,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _verify_claims(
    repo_root: Path,
    gate_id: str,
    value: object,
    required_evidence: str,
) -> list[dict[str, str]]:
    claims = _object(value, "evidence artifact claims")
    _exact_keys(claims, _CLAIM_KEYS, "evidence artifact claims")
    if claims["required_evidence"] != required_evidence:
        raise ValueError(f"{gate_id} claims do not match the gate's required evidence")
    references = claims["artifacts"]
    if not isinstance(references, list) or not references:
        raise ValueError("evidence artifact claims require at least one referenced artifact")
    verified: list[dict[str, str]] = []
    paths: set[str] = set()
    for position, value in enumerate(references):
        reference = _object(value, f"claim artifact {position}")
        _exact_keys(reference, _CLAIM_ARTIFACT_KEYS, f"claim artifact {position}")
        relative_path = _text(reference["path"], f"claim artifact {position} path")
        if relative_path in paths:
            raise ValueError("claim artifact paths must be unique")
        paths.add(relative_path)
        artifact_path = _safe_repo_file(repo_root, relative_path, f"claim artifact {position} path")
        expected_digest = _text(reference["sha256"], f"claim artifact {position} sha256")
        if len(expected_digest) != 64 or any(character not in "0123456789abcdef" for character in expected_digest):
            raise ValueError(f"claim artifact {position} sha256 must be lowercase hexadecimal")
        actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(f"claim artifact {position} sha256 does not match")
        verified.append({"path": relative_path, "sha256": actual_digest})
    return verified


_SURFACE_GROUPS = {
    "cli": frozenset({"cli", "legacy_cli_argument", "legacy_cli_option", "legacy_report_tree"}),
    "mcp": frozenset({"legacy_mcp_tool", "legacy_mcp_factory", "legacy_mcp_argument", "legacy_checkpoint_persistence"}),
    "adapter": frozenset({"python_adapter", "python_adapter_method"}),
    "scripts": frozenset({"legacy_mcp_executable"}),
    "extras": frozenset({"package_extra"}),
    "contracts": frozenset(
        {
            "executor_value",
            "request_config",
            "observation_mode",
            "legacy_state_artifact",
            "legacy_signal_artifact",
            "saved_results",
        }
    ),
}


def _python_tree(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"cannot parse owning surface {path}: {exc}") from exc


def _string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    return next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)


def _parameters(function: ast.FunctionDef) -> set[str]:
    return {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if argument.arg not in {"self", "cls"}
    }


def _discover_cli_surfaces(root: Path) -> set[str]:
    function = _function(_python_tree(root / "src/tradingagents_portable/cli.py"), "_add_research_command")
    if function is None:
        return set()
    owners: set[str] = set()
    discovered: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        call = node.value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr == "add_parser" and call.args and _string(call.args[0]) == "research":
            owners.add(node.targets[0].id)
            discovered.add("research")
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in owners
                and call.func.attr in {"add_mutually_exclusive_group", "add_argument_group"}
                and node.targets[0].id not in owners
            ):
                owners.add(node.targets[0].id)
                changed = True
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in owners
        ):
            discovered.update(value for argument in node.args if (value := _string(argument)) is not None)
    return discovered


def _discover_mcp_surfaces(root: Path) -> set[str]:
    tree = _python_tree(root / "src/tradingagents_portable/legacy_mcp_server.py")
    factory = _function(tree, "create_legacy_server")
    if factory is None:
        return set()
    discovered: set[str] = set()
    for node in ast.walk(factory):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Call) or not node.args:
            continue
        registration = node.func
        if not isinstance(registration.func, ast.Attribute) or registration.func.attr != "tool":
            continue
        callable_node = node.args[0]
        if not isinstance(callable_node, ast.Name):
            continue
        tool_name = next((_string(keyword.value) for keyword in registration.keywords if keyword.arg == "name"), None)
        implementation = _function(tree, callable_node.id)
        if tool_name is None or implementation is None:
            continue
        discovered.update({"create_legacy_server", tool_name})
        discovered.update(_parameters(implementation))
    return discovered


def _discover_adapter_surfaces(root: Path) -> set[str]:
    tree = _python_tree(root / "src/tradingagents_portable/legacy.py")
    adapter = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LegacyTradingAgentsAdapter"),
        None,
    )
    if adapter is None:
        return set()
    return {adapter.name} | {
        node.name for node in adapter.body if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }


def _annotation_strings(annotation: ast.AST) -> set[str]:
    return {
        node.value for node in ast.walk(annotation) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _class_fields(tree: ast.Module, class_name: str) -> tuple[set[str], dict[str, set[str]]]:
    class_node = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name),
        None,
    )
    if class_node is None:
        return set(), {}
    fields: set[str] = set()
    literals: dict[str, set[str]] = {}
    for node in class_node.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            fields.add(node.target.id)
            literals[node.target.id] = _annotation_strings(node.annotation)
    return fields, literals


def _discover_contract_surfaces(root: Path) -> set[str]:
    tree = _python_tree(root / "src/tradingagents_portable/contracts.py")
    request_fields, request_literals = _class_fields(tree, "RunRequest")
    result_fields, _ = _class_fields(tree, "RunResult")
    _, metadata_literals = _class_fields(tree, "CapabilityMetadata")
    discovered = {"RunResult"} if result_fields else set()
    discovered.update(request_fields & {"legacy_config"})
    discovered.update(request_literals.get("executor", set()) & {"legacy"})
    discovered.update(metadata_literals.get("observation_mode", set()) & {"legacy_post_run"})
    discovered.update(
        result_fields
        & {
            "investment_plan",
            "trader_investment_plan",
            "portfolio_manager_decision",
            "final_trade_decision",
            "processed_signal",
        }
    )
    return discovered


def _discover_packaging_surfaces(root: Path) -> tuple[set[str], set[str]]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = _object(pyproject.get("project"), "pyproject project")
    scripts = _object(project.get("scripts"), "pyproject scripts")
    extras = _object(project.get("optional-dependencies"), "pyproject optional-dependencies")
    legacy_scripts = {
        name for name, target in scripts.items() if "legacy" in name.lower() or "legacy" in str(target).lower()
    }
    upstream_extras = {
        name
        for name, dependencies in extras.items()
        if name == "upstream"
        or any(
            "tradingagents" in str(dependency).lower() for dependency in dependencies if isinstance(dependencies, list)
        )
    }
    return legacy_scripts, upstream_extras


def _discover_legacy_surfaces(root: Path) -> dict[str, set[str]]:
    scripts, extras = _discover_packaging_surfaces(root)
    return {
        "cli": _discover_cli_surfaces(root),
        "mcp": _discover_mcp_surfaces(root),
        "adapter": _discover_adapter_surfaces(root),
        "scripts": scripts,
        "extras": extras,
        "contracts": _discover_contract_surfaces(root),
    }


def current_legacy_surface_inventory(
    repo_root: str | Path,
    declared: Iterable[Mapping[str, object]],
) -> dict[str, list[str]]:
    """Return exact identifiers found in their typed owning constructs."""
    root = Path(repo_root).resolve(strict=True)
    for item in declared:
        surface = _text(item.get("surface"), "legacy surface type")
        _text(item.get("identifier"), "legacy surface identifier")
        if not any(surface in surfaces for surfaces in _SURFACE_GROUPS.values()):
            raise ValueError(f"legacy surface type {surface!r} has no typed inventory owner")
    discovered = _discover_legacy_surfaces(root)
    return {group: sorted(discovered[group]) for group in _SURFACE_GROUPS}


def _validate_inventory(repo_root: Path, manifest: Mapping[str, Any]) -> dict[str, list[str]]:
    surfaces = manifest["user_facing_legacy_surfaces"]
    inventory = current_legacy_surface_inventory(repo_root, surfaces)
    declared_by_group: dict[str, set[str]] = {group: set() for group in _SURFACE_GROUPS}
    for item in surfaces:
        surface = _text(item.get("surface"), "legacy surface type")
        identifier = _text(item.get("identifier"), "legacy surface identifier")
        group = next(name for name, types in _SURFACE_GROUPS.items() if surface in types)
        declared_by_group[group].add(identifier)
    missing = sorted(
        f"{group}:{identifier}"
        for group, expected in declared_by_group.items()
        for identifier in expected - set(inventory[group])
    )
    if missing:
        raise ValueError(f"declared legacy surface identifiers are absent from the current repository: {missing}")
    undeclared = sorted(
        f"{group}:{identifier}"
        for group, expected in declared_by_group.items()
        for identifier in set(inventory[group]) - expected
    )
    if undeclared:
        raise ValueError(f"current repository exposes undeclared legacy entry points: {undeclared}")
    inventory["discovered_entry_points"] = sorted(set().union(*map(set, inventory.values())))
    return inventory


def _parse_index(path: Path, gate_ids: set[str]) -> dict[str, dict[str, Any]]:
    raw = _load_json(path, "legacy removal evidence index")
    _exact_keys(raw, _INDEX_KEYS, "evidence index")
    if raw["schema_version"] != "1.0.0" or raw["id"] != EVIDENCE_INDEX_ID:
        raise ValueError("unexpected evidence index identity")
    records = raw["records"]
    if not isinstance(records, list):
        raise ValueError("evidence index records must be a list")
    parsed: dict[str, dict[str, Any]] = {}
    for position, value in enumerate(records):
        record = _object(value, f"evidence record {position}")
        _exact_keys(record, _RECORD_KEYS, f"evidence record {position}")
        gate_id = _text(record["gate_id"], "gate_id")
        if gate_id not in gate_ids:
            raise ValueError(f"unknown evidence gate {gate_id!r}")
        if gate_id in parsed:
            raise ValueError(f"duplicate evidence gate {gate_id!r}")
        parsed[gate_id] = record
    return parsed


def _verify_record(
    repo_root: Path,
    gate_id: str,
    record: Mapping[str, Any],
    *,
    required_evidence: str,
    trusted_signers: frozenset[str],
    trust_roots: Mapping[str, object],
    attestation_verifier: AttestationVerifier | None,
    now: datetime,
    max_age: timedelta,
) -> dict[str, Any]:
    artifact_ref = _object(record["artifact"], "artifact reference")
    _exact_keys(artifact_ref, _ARTIFACT_REF_KEYS, "artifact reference")
    if artifact_ref["schema"] != ARTIFACT_SCHEMA_ID:
        raise ValueError("artifact reference declares an unsupported schema")
    artifact_path = _safe_repo_file(repo_root, artifact_ref["path"], "artifact path")
    expected_digest = _text(artifact_ref["sha256"], "artifact sha256")
    if len(expected_digest) != 64 or any(character not in "0123456789abcdef" for character in expected_digest):
        raise ValueError("artifact sha256 must be lowercase hexadecimal")
    actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("artifact sha256 does not match")

    commit = _verify_commit(repo_root, record["producing_commit"])
    verified_at = _timestamp(record["verified_at"], "verified_at")
    if verified_at > now or now - verified_at > max_age:
        raise ValueError("evidence is future-dated or stale")

    sign_offs = record["sign_offs"]
    if not isinstance(sign_offs, list) or not sign_offs:
        raise ValueError("at least one authenticated sign-off is required")
    if attestation_verifier is None:
        raise ValueError("an authenticated attestation verifier is required")
    signers: set[str] = set()
    for position, value in enumerate(sign_offs):
        sign_off = _object(value, f"sign_off {position}")
        _exact_keys(sign_off, _SIGN_OFF_KEYS, f"sign_off {position}")
        signer = _text(sign_off["signer"], "signer")
        role = _text(sign_off["role"], "sign-off role")
        attestation = _text(sign_off["attestation"], "sign-off attestation")
        if signer in signers:
            raise ValueError("signers must be unique")
        if signer not in trusted_signers:
            raise ValueError(f"signer {signer!r} is not an allowed identity")
        if signer not in trust_roots:
            raise ValueError(f"signer {signer!r} has no configured trust root")
        statement = canonical_attestation_statement(
            gate_id=gate_id,
            artifact=artifact_ref,
            producing_commit=commit,
            verified_at=_text(record["verified_at"], "verified_at"),
            signer=signer,
            role=role,
        )
        try:
            authenticated = attestation_verifier.verify(
                statement=statement,
                attestation=attestation,
                trust_root=trust_roots[signer],
            )
        except Exception as exc:
            raise ValueError(f"attestation verification failed for signer {signer!r}") from exc
        if authenticated is not True:
            raise ValueError(f"attestation is not authentic for signer {signer!r}")
        signers.add(signer)

    artifact = _load_json(artifact_path, "legacy removal evidence artifact")
    _exact_keys(artifact, _ARTIFACT_KEYS, "evidence artifact")
    if artifact["schema_version"] != "1.0.0" or artifact["id"] != ARTIFACT_SCHEMA_ID:
        raise ValueError("unexpected evidence artifact identity")
    if artifact["gate_id"] != gate_id or artifact["result"] != "passed":
        raise ValueError("evidence artifact does not pass its indexed gate")
    if gate_id in LOCAL_GATES:
        expected_kind = "local_verification"
    elif gate_id in OPERATIONAL_GATES:
        expected_kind = "operational_attestation"
    else:
        expected_kind = "release_attestation"
    if artifact["evidence_kind"] != expected_kind:
        raise ValueError(f"{gate_id} requires {expected_kind} evidence")
    if artifact["producing_commit"] != commit:
        raise ValueError("artifact and index producing commits differ")
    generated_at = _timestamp(artifact["generated_at"], "artifact generated_at")
    if generated_at > verified_at or now - generated_at > max_age:
        raise ValueError("artifact generation time is after verification or stale")
    referenced_artifacts = _verify_claims(repo_root, gate_id, artifact["claims"], required_evidence)
    return {
        "passed": True,
        "artifact": str(artifact_ref["path"]),
        "sha256": actual_digest,
        "producing_commit": commit,
        "verified_at": verified_at.isoformat(),
        "authenticated_signers": sorted(signers),
        "referenced_artifacts": referenced_artifacts,
    }


def verify_legacy_removal(
    repo_root: str | Path,
    *,
    manifest_path: str | Path | None = None,
    evidence_index_path: str | Path = DEFAULT_EVIDENCE_INDEX,
    trusted_signers: Iterable[str] = DEFAULT_TRUSTED_SIGNERS,
    trust_roots: Mapping[str, object] | None = None,
    attestation_verifier: AttestationVerifier | None = None,
    now: datetime | None = None,
    max_age_days: int = 30,
) -> dict[str, Any]:
    """Return a derived, fail-closed legacy-removal eligibility report."""
    root = Path(repo_root).resolve(strict=True)
    manifest_file = (
        Path(manifest_path)
        if manifest_path is not None
        else root / LEGACY_TRANSITION_MANIFEST.relative_to(Path(__file__).resolve().parents[2])
    )
    manifest = load_legacy_transition_manifest(manifest_file)
    gate_ids = {gate["id"] for gate in manifest["removal_gates"]}
    if gate_ids != LOCAL_GATES | OPERATIONAL_GATES | RELEASE_GATES:
        raise ValueError("legacy transition policy gate split is unexpected")
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if max_age_days <= 0:
        raise ValueError("max_age_days must be positive")
    allowlist = frozenset(trusted_signers)
    if not allowlist or any(not isinstance(signer, str) or not signer for signer in allowlist):
        raise ValueError("trusted_signers must be a non-empty allowlist")
    roots = dict(trust_roots or {})
    if any(not isinstance(signer, str) or not signer for signer in roots):
        raise ValueError("trust_roots keys must be non-empty signer identities")

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "id": "tradingagents.legacy-removal-report.v1",
        "manifest_removal_allowed_ignored": manifest.get("removal_allowed"),
        "evidence_index_valid": True,
        "inventory_valid": True,
        "inventory": {},
        "gate_results": {},
        "local_gates_passed": False,
        "operational_gates_passed": False,
        "release_gates_passed": False,
        "external_gates_passed": False,
        "removal_allowed": False,
        "errors": [],
    }
    try:
        report["inventory"] = _validate_inventory(root, manifest)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        report["inventory_valid"] = False
        report["errors"].append(f"inventory: {exc}")

    try:
        index_path = _safe_repo_file(root, str(evidence_index_path), "evidence index path")
        records = _parse_index(index_path, gate_ids)
    except ValueError as exc:
        report["evidence_index_valid"] = False
        report["errors"].append(f"evidence index: {exc}")
        records = {}

    for gate_id in sorted(gate_ids):
        record = records.get(gate_id)
        if record is None:
            report["gate_results"][gate_id] = {"passed": False, "error": "missing evidence record"}
            continue
        try:
            report["gate_results"][gate_id] = _verify_record(
                root,
                gate_id,
                record,
                required_evidence=next(
                    gate["required_evidence"] for gate in manifest["removal_gates"] if gate["id"] == gate_id
                ),
                trusted_signers=allowlist,
                trust_roots=roots,
                attestation_verifier=attestation_verifier,
                now=current_time,
                max_age=timedelta(days=max_age_days),
            )
        except ValueError as exc:
            report["gate_results"][gate_id] = {"passed": False, "error": str(exc)}

    report["local_gates_passed"] = all(report["gate_results"][gate]["passed"] for gate in LOCAL_GATES)
    report["operational_gates_passed"] = all(report["gate_results"][gate]["passed"] for gate in OPERATIONAL_GATES)
    report["release_gates_passed"] = all(report["gate_results"][gate]["passed"] for gate in RELEASE_GATES)
    report["external_gates_passed"] = bool(report["operational_gates_passed"] and report["release_gates_passed"])
    report["removal_allowed"] = bool(
        report["evidence_index_valid"]
        and report["inventory_valid"]
        and report["local_gates_passed"]
        and report["external_gates_passed"]
    )
    return report
