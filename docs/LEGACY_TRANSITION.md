# Legacy executor transition

- **Purpose:** define when the optional upstream executor may leave the public product surface.
- **Audience:** maintainers, release owners, adapter authors, and reviewers.
- **Canonical for:** removal scope, blocking gates, deprecation policy, and retained compatibility readers.
- **Not canonical for:** current feature proof; see [Capability and proof ledger](FEATURE_PARITY.md) and [Validation](VALIDATION.md).

## Current decision

Legacy removal is **blocked**. The optional `research` CLI, `tradingagents-portable-legacy-mcp`, `LegacyTradingAgentsAdapter`, and upstream extra remain available and are **not yet deprecated**. The default credential-free Codex/MCP plugin already excludes `run_legacy`, so deleting the opt-in executor now would remove the only upstream execution comparison path without improving the default plugin's safety.

The target is a host-native portable research core. Codex, generic agent harnesses, a sequential fallback, and tools-only MCP clients are adapters around shared versioned contracts. When every gate below is verified, the public legacy executor may be removed at a major-version boundary while the pinned upstream checkout remains a development and CI conformance oracle.

The machine-readable status is [legacy-transition.v1.json](../src/tradingagents_portable/workflow/legacy-transition.v1.json). That manifest must report `removal_allowed: false` while any required gate is not verified.

## Remove versus retain

| Eventually remove from the user surface | Retain after executor removal |
| --- | --- |
| `research` command delegation to `TradingAgentsGraph` | Frozen v1/v2 schemas and readers |
| `tradingagents-portable-legacy-mcp` executable and `run_legacy` | Historical result, event, export, and lifecycle identifiers |
| Runtime `LegacyTradingAgentsAdapter` and `executor="legacy"` creation | Copy-on-write saved-result migrations and migration receipts |
| Upstream runtime dependency from normal installation | Observable-parity fixtures and canonical projections |
| Legacy provider/configuration entry points | Exact upstream pin used only by development/CI conformance |

Removal of the executor is not permission to delete old data contracts. Existing saved results must remain readable, exportable, and viewable after deterministic migration.

## Required gates

| Gate | Current status | Required proof |
| --- | --- | --- |
| `parity_ledger` | Blocked | Every removal-blocking parity row has an owner, fresh evidence artifact, verified commit/date, and release sign-off. |
| `source_contracts_and_concrete_adapter_mcp` | Blocked | Versioned provider-neutral MCP adapters exist for all required data categories, with fixture/replay conformance and no provider SDK in the portable domain. |
| `deterministic_dual_run_semantic_conformance` | Blocked | CI fetches the exact pin and compares a versioned pure-semantic projection from upstream and Portable. The implemented probe excludes model/provider execution, so full dual-run release evidence is still required. |
| `representative_live_and_failure_matrix` | Blocked | Recorded live/failure evidence covers supported asset shapes, ambiguous and unsupported symbols, market-closed cutoffs, partial/stale data, denial, rate limits, pagination, and completed-only publication. |
| `python_cli_mcp_ui_equivalence` | Blocked | Python, CLI, MCP, export/reload, and UI produce the same canonical semantic digest and visible limitations from one completed bundle. |
| `saved_result_migration` | Blocked | Golden artifacts from every public release migrate copy-on-write, idempotently, with original preservation and a migration receipt. |
| `published_deprecation_release` | Blocked | One published release warns on every legacy entry point, names the replacement and migration path, and declares an earliest later major removal version. |
| `major_version_boundary` | Blocked | Executor removal is scheduled only for a documented later major version. |

Passing fixture tests alone cannot satisfy these gates. Removal requires all gates to be freshly verified in the same release decision. Three gates are repository-local proofs, three require provider/operational attestations, and two require release attestations. The library verifier accepts an injected authentication verifier and signer-specific trust roots. The release CLI provides a concrete built-in HMAC-SHA256 path described below; without authenticated trust roots, evidence-bearing runs fail closed.

## Executable removal gate

Run `uv run python scripts/verify_legacy_removal.py --expect-blocked` against the checked-in evidence index. The canonical index at `evidence/legacy-removal-evidence.v1.json` is intentionally empty, so the repository remains blocked. Release automation must instead run `uv run python scripts/verify_legacy_removal.py --hmac-trust-roots "$LEGACY_REMOVAL_TRUST_ROOTS" --require-removal-allowed`; the command exits nonzero unless all eight records and their attestations pass. The environment variable must name a CI-injected file, not a tracked repository secret.

The HMAC trust-root file is strict JSON: `{"schema_version":"1.0.0","id":"tradingagents.legacy-removal-hmac-trust-roots.v1","signers":{"release-maintainer":"secret supplied by release automation"}}`. Its signer keys become the default trusted-signer allowlist (or may be narrowed with repeated `--trusted-signer`). Each sign-off attestation is `hmac-sha256:<lowercase hex digest>` over the canonical record statement using that signer's secret. Unknown fields, an empty signer map, empty secrets, unknown signers, missing roots, malformed schemes, and signature mismatches all fail closed. HMAC keys are symmetric release credentials: generate, store, inject, rotate, and audit them in the release system; never commit them with evidence.

The evidence index has the strict identity `tradingagents.legacy-removal-evidence.v1` and contains at most one record per gate. Each record names a repository-relative JSON artifact, its SHA-256 digest, the exact current `HEAD`, a timezone-aware verification time, and one or more authenticated sign-offs. Verification also requires a clean worktree. A signer name or allowlist entry is identity metadata only: production release automation must supply signer-specific trust roots through the HMAC file above (or inject an equivalent library verifier), and verification fails closed when either is absent or the attestation does not authenticate the canonical record statement.

The referenced artifact must use schema `tradingagents.legacy-removal-gate-evidence.v1`, report `result: passed`, repeat the gate and producing commit, and include a timezone-aware generation time. Its evidence kind is `local_verification` for parity/surface/migration proof, `operational_attestation` for provider-backed adapters, real dual runs, and live/failure matrices, or `release_attestation` for deprecation and major-version proof. Its `claims` object must contain exactly the gate's manifest `required_evidence` value and a non-empty list of repository-relative proof artifacts with SHA-256 digests. Every referenced path is traversal- and symlink-checked and every digest is recomputed. Evidence preparation normally keeps the generated index, gate artifacts, and proof files outside tracked repository content (or in an ignored release-work directory) so they can bind to an already-created `HEAD` without making the worktree dirty.

The verifier rejects unknown fields, duplicate gates, absolute/traversing/symlinked paths, hash changes, stale or future timestamps, any producing revision other than exact `HEAD`, dirty worktrees, and signers outside the configured allowlist/trust roots. It inventories only typed owning constructs: arguments attached to the `research` argparse parser, the MCP tool actually registered by `create_legacy_server` and that callable's parameters, public methods owned by `LegacyTradingAgentsAdapter`, legacy project scripts and upstream extras in `pyproject.toml`, and the relevant typed contract fields/literals. It checks each owning group bidirectionally against the transition manifest; loose names, unrelated strings, and unregistered/dead functions do not count. Eligibility is derived from authenticated evidence and the current inventory; the manifest's `removal_allowed` value is reported for visibility but never trusted.

## Upstream oracle scope

The pinned upstream checkout may be a differential oracle only for stable observable behavior:

- selected analysts, workflow stage coverage and order;
- debate and risk-round cardinality;
- configuration defaults and symbol normalization;
- stable state/report fields, decision vocabularies, and processed-signal mapping;
- terminal status, non-execution, and required report groups.

It is not an oracle for exact prose, prompts, token order, LangGraph nodes, provider selection, factual correctness, entitlement, exact-cutoff safety, investment quality, or forecast skill. Portable safety and evidence rules remain independently authoritative.

## Deprecation and removal policy

1. A release first publishes deprecation warnings without removing behavior.
2. That release records `deprecated_since`, the replacement, migration instructions, and the earliest removal version in CLI, MCP discovery, documentation, and package metadata.
3. Removal occurs no earlier than a later **major** version and only when every gate is verified.
4. Frozen readers and migrations remain supported after the executor disappears.
5. If any gate regresses, removal eligibility returns to false.

## Relationship to the upstream RFC

[TradingAgents RFC #1198](https://github.com/TauricResearch/TradingAgents/issues/1198) proposes a thin portable contract without replacing LangGraph inside upstream TradingAgents. This transition is compatible with that RFC: it concerns only the independent [StockResearchAgents repository](https://github.com/harshitagarwal2/StockResearchAgents). Upstream keeps its runtime; this repository eventually stops exposing its own user-facing delegation wrapper after replacement proof exists.

Keep the upstream project intact as an external, exact-revision conformance oracle. CI should use a fresh checkout at the transition manifest's pinned commit; a dirty sibling development clone is never proof. StockResearchAgents may call the optional upstream adapter, but must not vendor or fork upstream workflow business logic into the portable core.

## Paper exchange boundary

A simulated exchange is not a legacy-removal requirement and remains outside the default research plugin. If built, it must use a separate package/process, MCP namespace, state store, and explicit opt-in. It may consume completed non-executable analysis artifacts but must never mutate Portable lifecycle or canonical results.
