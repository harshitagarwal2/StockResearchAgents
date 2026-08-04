from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tradingagents_portable.transition_verifier import (
    ARTIFACT_SCHEMA_ID,
    EXTERNAL_GATES,
    HMAC_TRUST_ROOTS_ID,
    LOCAL_GATES,
    OPERATIONAL_GATES,
    canonical_attestation_statement,
    verify_legacy_removal,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 3, 12, tzinfo=UTC)
TRUST_ROOT = "fixture-trust-root"


class DeterministicAttestationVerifier:
    def verify(self, *, statement: bytes, attestation: str, trust_root: object) -> bool:
        expected = hashlib.sha256(str(trust_root).encode() + b"\0" + statement).hexdigest()
        return attestation == expected


def _sign_record(record: dict[str, object], signer: str = "release@example.invalid") -> None:
    statement = canonical_attestation_statement(
        gate_id=record["gate_id"],  # type: ignore[arg-type]
        artifact=record["artifact"],  # type: ignore[arg-type]
        producing_commit=record["producing_commit"],  # type: ignore[arg-type]
        verified_at=record["verified_at"],  # type: ignore[arg-type]
        signer=signer,
        role="gate_owner",
    )
    sign_offs = record["sign_offs"]  # type: ignore[assignment]
    sign_offs[0]["attestation"] = hashlib.sha256(TRUST_ROOT.encode() + b"\0" + statement).hexdigest()


def _run(root: Path, *args: str) -> str:
    return subprocess.run(
        args,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    workflow_dir = root / "src/tradingagents_portable/workflow"
    workflow_dir.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "src/tradingagents_portable/workflow/legacy-transition.v1.json", workflow_dir)
    (root / "pyproject.toml").write_text(
        """
[project]
name = "fixture"
version = "1.0.0"
[project.scripts]
tradingagents-portable-legacy-mcp = "pkg:main"
[project.optional-dependencies]
upstream = ["example"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    package = root / "src/tradingagents_portable"
    (root / ".gitignore").write_text("/evidence/\n", encoding="utf-8")
    for source_name in ("cli.py", "legacy_mcp_server.py", "legacy.py", "contracts.py"):
        shutil.copy(REPO_ROOT / "src/tradingagents_portable" / source_name, package / source_name)
    _run(root, "git", "init", "-q")
    _run(root, "git", "config", "user.email", "fixture@example.invalid")
    _run(root, "git", "config", "user.name", "Fixture")
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-qm", "fixture surface")
    return root, _run(root, "git", "rev-parse", "HEAD")


def _passing_index(root: Path, commit: str, *, signer: str = "release@example.invalid") -> Path:
    manifest = json.loads(
        (root / "src/tradingagents_portable/workflow/legacy-transition.v1.json").read_text(encoding="utf-8")
    )
    requirements = {gate["id"]: gate["required_evidence"] for gate in manifest["removal_gates"]}
    records = []
    for gate_id in sorted(LOCAL_GATES | EXTERNAL_GATES):
        proof_path = root / "evidence" / f"{gate_id}.proof.json"
        _write_json(proof_path, {"gate_id": gate_id, "fixture_proof": True})
        artifact = {
            "schema_version": "1.0.0",
            "id": ARTIFACT_SCHEMA_ID,
            "gate_id": gate_id,
            "evidence_kind": (
                "local_verification"
                if gate_id in LOCAL_GATES
                else "operational_attestation"
                if gate_id in OPERATIONAL_GATES
                else "release_attestation"
            ),
            "result": "passed",
            "producing_commit": commit,
            "generated_at": "2026-08-03T10:00:00Z",
            "claims": {
                "required_evidence": requirements[gate_id],
                "artifacts": [
                    {
                        "path": f"evidence/{gate_id}.proof.json",
                        "sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                    }
                ],
            },
        }
        artifact_path = root / "evidence" / f"{gate_id}.json"
        _write_json(artifact_path, artifact)
        record = {
            "gate_id": gate_id,
            "artifact": {
                "path": f"evidence/{gate_id}.json",
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "schema": ARTIFACT_SCHEMA_ID,
            },
            "producing_commit": commit,
            "verified_at": "2026-08-03T11:00:00Z",
            "sign_offs": [{"signer": signer, "role": "gate_owner", "attestation": "pending"}],
        }
        _sign_record(record, signer)
        records.append(record)
    index = root / "evidence/index.json"
    _write_json(
        index,
        {"schema_version": "1.0.0", "id": "tradingagents.legacy-removal-evidence.v1", "records": records},
    )
    return index


def _resign_index_with_hmac(index: Path, secret: str) -> None:
    raw = json.loads(index.read_text(encoding="utf-8"))
    for record in raw["records"]:
        sign_off = record["sign_offs"][0]
        statement = canonical_attestation_statement(
            gate_id=record["gate_id"],
            artifact=record["artifact"],
            producing_commit=record["producing_commit"],
            verified_at=record["verified_at"],
            signer=sign_off["signer"],
            role=sign_off["role"],
        )
        sign_off["attestation"] = (
            "hmac-sha256:" + hmac.new(secret.encode("utf-8"), statement, hashlib.sha256).hexdigest()
        )
    _write_json(index, raw)


def _verify(root: Path, **kwargs: object) -> dict[str, object]:
    current_time = kwargs.pop("now", NOW)
    return verify_legacy_removal(
        root,
        manifest_path=root / "src/tradingagents_portable/workflow/legacy-transition.v1.json",
        evidence_index_path="evidence/index.json",
        trusted_signers={"release@example.invalid"},
        trust_roots={"release@example.invalid": TRUST_ROOT},
        attestation_verifier=DeterministicAttestationVerifier(),
        now=current_time,  # type: ignore[arg-type]
        **kwargs,
    )


def test_repository_evidence_index_is_canonically_blocked() -> None:
    report = verify_legacy_removal(REPO_ROOT, now=NOW)

    assert report["evidence_index_valid"] is True
    assert report["inventory_valid"] is True
    assert report["local_gates_passed"] is False
    assert report["operational_gates_passed"] is False
    assert report["release_gates_passed"] is False
    assert report["external_gates_passed"] is False
    assert report["removal_allowed"] is False
    assert all(result["error"] == "missing evidence record" for result in report["gate_results"].values())


def test_synthetic_reachable_fresh_trusted_evidence_passes_all_gates(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    _passing_index(root, commit)

    report = _verify(root)

    assert report["inventory_valid"] is True
    assert report["local_gates_passed"] is True
    assert report["operational_gates_passed"] is True
    assert report["release_gates_passed"] is True
    assert report["external_gates_passed"] is True
    assert report["removal_allowed"] is True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda record: record["artifact"].update(sha256="0" * 64), "sha256 does not match"),
        (lambda record: record.update(verified_at="2026-06-01T00:00:00Z"), "future-dated or stale"),
        (lambda record: record.update(producing_commit="f" * 40), "must exactly match HEAD"),
        (
            lambda record: record.update(
                sign_offs=[{"signer": "stranger", "role": "gate_owner", "attestation": "forged"}]
            ),
            "is not an allowed identity",
        ),
    ],
)
def test_tampered_stale_unreachable_and_untrusted_evidence_fail_closed(
    tmp_path: Path, mutation: object, expected: str
) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    mutation(raw["records"][0])  # type: ignore[operator]
    _write_json(index, raw)

    report = _verify(root)

    result = report["gate_results"][raw["records"][0]["gate_id"]]
    assert result["passed"] is False
    assert expected in result["error"]
    assert report["removal_allowed"] is False


def test_duplicate_gate_invalidates_the_strict_index(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    raw["records"].append(raw["records"][1])
    _write_json(index, raw)

    report = _verify(root)

    assert report["evidence_index_valid"] is False
    assert "duplicate evidence gate" in report["errors"][0]
    assert report["removal_allowed"] is False


def test_naive_timestamp_fails_its_gate_closed(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    raw["records"][0]["verified_at"] = "2026-08-03T11:00:00"
    _write_json(index, raw)

    report = _verify(root)

    result = report["gate_results"][raw["records"][0]["gate_id"]]
    assert result["passed"] is False
    assert "must include a timezone" in result["error"]
    assert report["removal_allowed"] is False


def test_existing_commit_that_is_not_reachable_from_head_fails_closed(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    tree = _run(root, "git", "write-tree")
    unreachable = _run(root, "git", "commit-tree", tree, "-m", "unreachable evidence producer")
    raw = json.loads(index.read_text(encoding="utf-8"))
    record = raw["records"][0]
    record["producing_commit"] = unreachable
    artifact_path = root / record["artifact"]["path"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["producing_commit"] = unreachable
    _write_json(artifact_path, artifact)
    record["artifact"]["sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    _write_json(index, raw)

    report = _verify(root)

    result = report["gate_results"][record["gate_id"]]
    assert result["passed"] is False
    assert result["error"] == "producing_commit must exactly match HEAD"
    assert report["removal_allowed"] is False


def test_ancestor_commit_and_dirty_worktree_fail_closed(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    _passing_index(root, commit)
    (root / "README.md").write_text("new head\n", encoding="utf-8")
    _run(root, "git", "add", "README.md")
    _run(root, "git", "commit", "-qm", "advance head")

    ancestor = _verify(root)
    assert all(result["passed"] is False for result in ancestor["gate_results"].values())
    assert all(
        result["error"] == "producing_commit must exactly match HEAD" for result in ancestor["gate_results"].values()
    )

    head = _run(root, "git", "rev-parse", "HEAD")
    _passing_index(root, head)
    (root / "src/tradingagents_portable/cli.py").write_text("DIRTY = True\n", encoding="utf-8")
    dirty = _verify(root)
    assert all(result["passed"] is False for result in dirty["gate_results"].values())
    assert all(result["error"] == "repository worktree must be clean" for result in dirty["gate_results"].values())


def test_gate_specific_claim_and_referenced_hash_are_enforced(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    first, second = raw["records"][:2]
    first_artifact_path = root / first["artifact"]["path"]
    first_artifact = json.loads(first_artifact_path.read_text(encoding="utf-8"))
    second_artifact = json.loads((root / second["artifact"]["path"]).read_text(encoding="utf-8"))
    first_artifact["claims"] = second_artifact["claims"]
    _write_json(first_artifact_path, first_artifact)
    first["artifact"]["sha256"] = hashlib.sha256(first_artifact_path.read_bytes()).hexdigest()
    _sign_record(first)
    _write_json(index, raw)

    wrong_gate = _verify(root)
    assert "claims do not match the gate's required evidence" in wrong_gate["gate_results"][first["gate_id"]]["error"]

    _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    first = raw["records"][0]
    artifact = json.loads((root / first["artifact"]["path"]).read_text(encoding="utf-8"))
    proof_path = root / artifact["claims"]["artifacts"][0]["path"]
    _write_json(proof_path, {"tampered": True})
    bad_hash = _verify(root)
    assert "claim artifact 0 sha256 does not match" in bad_hash["gate_results"][first["gate_id"]]["error"]


def test_attestations_require_a_verifier_and_authenticate_the_statement(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    without_verifier = verify_legacy_removal(
        root,
        manifest_path=root / "src/tradingagents_portable/workflow/legacy-transition.v1.json",
        evidence_index_path="evidence/index.json",
        trusted_signers={"release@example.invalid"},
        trust_roots={"release@example.invalid": TRUST_ROOT},
        now=NOW,
    )
    assert all(
        result["error"] == "an authenticated attestation verifier is required"
        for result in without_verifier["gate_results"].values()
    )

    raw = json.loads(index.read_text(encoding="utf-8"))
    raw["records"][0]["sign_offs"][0]["attestation"] = "0" * 64
    _write_json(index, raw)
    forged = _verify(root)
    result = forged["gate_results"][raw["records"][0]["gate_id"]]
    assert result["error"] == "attestation is not authentic for signer 'release@example.invalid'"
    assert forged["removal_allowed"] is False


def test_artifact_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    raw = json.loads(index.read_text(encoding="utf-8"))
    raw["records"][0]["artifact"]["path"] = "../outside.json"
    _write_json(index, raw)
    traversal = _verify(root)
    assert "traversal-free" in traversal["gate_results"][raw["records"][0]["gate_id"]]["error"]

    target = root / "evidence" / raw["records"][1]["gate_id"]
    symlink = root / "evidence/symlink.json"
    symlink.symlink_to(target.with_suffix(".json"))
    raw["records"][1]["artifact"]["path"] = "evidence/symlink.json"
    _write_json(index, raw)
    linked = _verify(root)
    assert "symlink" in linked["gate_results"][raw["records"][1]["gate_id"]]["error"]


def test_manifest_removal_boolean_is_never_trusted(tmp_path: Path) -> None:
    root, _ = _fixture_repo(tmp_path)
    manifest_path = root / "src/tradingagents_portable/workflow/legacy-transition.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["removal_allowed"] = True
    for gate in manifest["removal_gates"]:
        gate.update(
            status="passed",
            verification="verified",
            evidence_artifacts=["manifest-only-claim.json"],
            last_verified_commit="a" * 40,
            last_verified_at="2026-08-03T00:00:00Z",
            sign_off=["manifest-only-signer"],
        )
    _write_json(manifest_path, manifest)
    _write_json(
        root / "evidence/index.json",
        {"schema_version": "1.0.0", "id": "tradingagents.legacy-removal-evidence.v1", "records": []},
    )

    report = _verify(root)

    assert report["manifest_removal_allowed_ignored"] is True
    assert report["removal_allowed"] is False


def test_timezone_freshness_boundary_is_inclusive(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    _passing_index(root, commit)

    report = _verify(root, now=NOW + timedelta(days=30))

    assert report["removal_allowed"] is False  # generated_at is two hours older than the 30-day boundary


def test_dead_names_and_strings_do_not_prove_typed_surfaces(tmp_path: Path) -> None:
    root, _ = _fixture_repo(tmp_path)
    manifest_path = root / "src/tradingagents_portable/workflow/legacy-transition.v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_facing_legacy_surfaces"].extend(
        [
            {
                "surface": "legacy_cli_option",
                "identifier": "--dead-only",
                "migration_target": "host_native_research_commands",
            },
            {
                "surface": "legacy_mcp_tool",
                "identifier": "dead_tool",
                "migration_target": "safe_portable_mcp_run_surfaces",
            },
            {
                "surface": "legacy_mcp_argument",
                "identifier": "dead_parameter",
                "migration_target": "portable_company_request_symbol",
            },
        ]
    )
    _write_json(manifest_path, manifest)
    cli_path = root / "src/tradingagents_portable/cli.py"
    cli_path.write_text(cli_path.read_text(encoding="utf-8") + '\nDEAD = "--dead-only"\n', encoding="utf-8")
    mcp_path = root / "src/tradingagents_portable/legacy_mcp_server.py"
    mcp_path.write_text(
        mcp_path.read_text(encoding="utf-8")
        + '\ndef dead_tool(dead_parameter: str) -> None:\n    """Unregistered and therefore not a surface."""\n',
        encoding="utf-8",
    )

    report = _verify(root)

    assert report["inventory_valid"] is False
    assert "cli:--dead-only" in report["errors"][0]
    assert "mcp:dead_tool" in report["errors"][0]
    assert "mcp:dead_parameter" in report["errors"][0]


def test_new_owned_cli_argument_is_discovered_bidirectionally(tmp_path: Path) -> None:
    root, _ = _fixture_repo(tmp_path)
    cli_path = root / "src/tradingagents_portable/cli.py"
    source = cli_path.read_text(encoding="utf-8")
    cli_path.write_text(
        source.replace(
            'research.add_argument("--port", default=8765, type=int)',
            'research.add_argument("--port", default=8765, type=int)\n'
            '    research.add_argument("--undeclared-owned-option")',
        ),
        encoding="utf-8",
    )

    report = _verify(root)

    assert report["inventory_valid"] is False
    assert "cli:--undeclared-owned-option" in report["errors"][0]


def test_verification_cli_accepts_authenticated_hmac_evidence(tmp_path: Path) -> None:
    root, commit = _fixture_repo(tmp_path)
    index = _passing_index(root, commit)
    secret = "release-automation-fixture-secret"
    _resign_index_with_hmac(index, secret)
    trust_roots = root / "evidence/hmac-trust-roots.json"
    _write_json(
        trust_roots,
        {
            "schema_version": "1.0.0",
            "id": HMAC_TRUST_ROOTS_ID,
            "signers": {"release@example.invalid": secret},
        },
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(REPO_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/verify_legacy_removal.py"),
            "--repo-root",
            str(root),
            "--evidence-index",
            "evidence/index.json",
            "--hmac-trust-roots",
            str(trust_roots),
            "--require-removal-allowed",
        ],
        cwd=REPO_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["removal_allowed"] is True
