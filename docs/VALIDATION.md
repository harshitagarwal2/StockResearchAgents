# Validation checklist

- **Purpose:** record what local, credential-free validation can establish.
- **Audience:** contributors, reviewers, and release owners.
- **Canonical for:** executable proof and explicit validation gaps.
- **Not canonical for:** architecture decisions or Research Quality interpretation semantics.

## Company-research v2/v3 contract

- [x] The workflow manifest loads as `tradingagents.company-research.v2`, has 15 contiguous ordered stages, resolves only earlier dependencies, declares capability IDs and v3 output references, uses sequential fallback, and terminates at `publish.dossier`.
- [x] Discovery returns both `financial-research.v1`/`host-submission.v2` and `company-research.v2`/`host-submission.v3` without changing the legacy profile.
- [x] The v3 dataclass parser and JSON Schema require schema version `2026-08-03.v3`, the company workflow ID, a typed request, and a completed dossier.
- [x] Requests require truthful `research_mode` values (`live`, `fixture`, or `historical_replay`), and imported result capability flags distinguish fixture data from live host retrieval.
- [x] Strict parsing rejects unknown fields, duplicate IDs, dangling references, schema/runtime bound mismatches, unsafe market symbols, mismatched request/dossier identity or cutoff, and terminal dossiers over the configured size bound.
- [x] First-class contract tests cover identity, documents, calculations, metrics, claims, debate arguments, filings, filing changes, transcripts, guidance, peers, factors, valuations, entities, events, risks, monitoring, prior outcomes, evaluation, research delta, coverage, and optional sanitized portfolio context.
- [x] Deterministic ORCL, META, QQQ, and ACME submissions exercise multiple company/fund identities and keep their research IDs isolated.

## Point-in-time and evidence integrity

- [x] Document availability, filing timestamps, metric information vintages, transcript events, factor timestamps, historical events, and prior outcomes after the cutoff are rejected. Reported metric periods cannot follow their information vintage; cutoff-safe estimates, assumptions, and calculations may describe future periods.
- [x] Post-cutoff processing/completion remains allowed because processing time is distinct from evidence availability.
- [x] Claims, calculations, metrics, filings, transcripts, peers, factors, valuations, events, risks, monitoring, evaluation, coverage, and research delta must resolve their referenced IDs.
- [x] Claims require retained evidence or metrics; completed dossiers require non-empty documents/claims and a structured two-role challenge with an explicit rebuttal.
- [x] Complete coverage requires retained sources. Partial, missing, stale, conflicting, entitlement-blocked, and not-applicable coverage requires a limitation.
- [x] Entitlement-blocked fixtures retain the gap without a licensed extract or fabricated consensus claim; affirmative claims and non-assumption metrics need at least one accessible source.
- [x] Non-redistributable sources are metadata/reference only and reject all extracts, including bounded extracts; recursive safety checks reject raw-source fields.
- [x] `SourcePort.fetch(capability, typed_query)` conformance covers fixture, replay, and router adapters; typed queries reject explicit credentials and credential-bearing signed URLs before dispatch.
- [x] `SourceBatch` v1 validates exact query/capability pairing, cutoff, typed status, provenance, entitlement, completeness, pagination, limitations, and deterministic normalized observations. `SourceObservation.content_sha256_scope` distinguishes source bytes, exact bounded extracts, and normalized source records while preserving the safe normalized-record adapter default.
- [x] The isolated `tradingagents-research-data` default server registers exactly six conformance-receipted public tools: three SEC, two GDELT metadata/link, and one World Bank macro tool. The coordination MCP registers none of them.
- [x] SEC company-fact observations have provider-order-independent IDs and a hard item cap that reports omitted matches as partial coverage; GDELT observations have canonical-URI deduplication, provider-order-independent IDs, explicit seen-time semantics, and partial coverage at the result cap.
- [x] Prices and indicators remain unregistered without a licensed host `SourcePort`; Reddit remains unregistered without host OAuth; StockTwits is denied and unregistered.

## Company-analytics v1/v4 contract

- [x] Prepare returns the 26-stage manifest, selected research pack, and one self-contained bundled v4 schema with typed analytics records.
- [x] Strict Python contracts validate cross-field semantics beyond JSON Schema, including the exact `<quality_run_id>.` prefix on every global `forecast_id`.
- [x] V4 parsing and conformance cover the unchanged v3 submission, analytics bundle, provider-neutral source-lineage crosswalk, run card, hypothesis ledger, iterations, quality receipt, and forecasts.
- [x] Source-lineage validation requires exact run-card batch membership, one-to-one coverage of every dossier document and analytics source license, and matching source IDs, canonical URIs, content digests, terms URIs, access, machine-use denial, and redistribution semantics.
- [x] Durable finalization rebinds report result/event descriptors to the lifecycle `run_id`.
- [x] Completed `RunResult.artifacts` are authoritative sidecars. Quality-index stage/publish failure tests keep derived state hidden and reconstruct it from completed artifacts without claiming a distributed transaction.
- [x] The profile-neutral sequential runner executes all 26 primary stages, resumes from the first incomplete stage, and finalizes through the same v4 lifecycle coordinator.
- [x] Every primary stage exposes a strictly validated `stage-instructions.v1` role, objective, completion criteria, dependencies, semantic capabilities, and output references without provider, model, Codex, or LangGraph coupling.

## Numerical, peer, debate, and portfolio conformance

- [x] Metrics require finite numbers, units, economic periods, and an exact cutoff-safe information vintage. Calculated metric values and units bind to deterministic calculation receipts and cannot predate their inputs.
- [x] The conformance engine recomputes bounded deterministic formulas, requires all declared metrics/constants, validates formula shape against the typed operation, applies rounding and absolute tolerance, and rejects tampered calculation, valuation, and sensitivity outputs.
- [x] Peer records require inclusion rationale and normalization methodology.
- [x] Debate turns require claim links; rebuttals must target an earlier turn in the same debate; concessions and unresolved items must be unique and disjoint.
- [x] Supersession links reject missing, self-referential, and cyclic targets.
- [x] Portfolio fields require an explicit non-execution boundary and reject private account/customer identity.
- [x] Credential-shaped keys are rejected recursively.

## Memory and lifecycle

- [x] Exact-cutoff memory recall filters decisions before applying same/cross-symbol limits and filters outcomes independently by `observed_at`.
- [x] Recall excludes later `created_at`, later decision `as_of_date`, and embedded post-cutoff filing/event/metric-vintage/outcome availability while retaining cutoff-safe forecasts with future economic periods; malformed legacy rows and outcomes fail closed without aborting safe recall.
- [x] Staged decisions remain outside recall until final publication.
- [x] `CompanyResearchCoordinator` tests cover all 15 stage boundaries, strict opaque reference descriptors, digest-bound receipts, optimistic revision conflicts, pause/resume, cooperative cancellation, cursor events, fresh-coordinator recovery, cutoff-safe memory recall, and completed publication.
- [x] Existing `run-lifecycle.v1` tests continue to cover the compatibility workflow's checkpoints, resume, cancellation, memory gating, and atomic result/event publication.
- [x] `CompanyAnalyticsCoordinator` tests cover all 26 ordered stage commits, rejection of out-of-order dependency-ready commits, first-incomplete resume, v4 terminal validation, report descriptor rebinding, quality-index staging/publication, and crash reconstruction.

## Plan/import, UI, and package surfaces

- [x] Python, CLI, and MCP plan/import tests validate the company request, return the frozen manifest/schema, import a complete v3 payload, and publish content-addressed symbol-specific results.
- [x] Public lifecycle routing tests create v2 runs through `company-init`/`create_company_research_run` and route shared lifecycle operations to the company coordinator by run ID.
- [x] Analytics lifecycle routing tests create v4 runs through `analytics-init`/`create_company_analytics_run` and route the shared lifecycle controls without duplicating the protocol.
- [x] Repeated identical imports are idempotent; different company submissions receive different run IDs.
- [x] The v3 request and dossier are preserved separately and losslessly as `research_request.v3` and `research_dossier.v3`, then projected as `RunView.research_request` and `RunView.research_dossier`.
- [x] Research-mode tests read the authoritative value from `RunView.research_request` for live, fixture, and historical replay submissions.
- [x] Direct import tests require `checkpoint_enabled=false` and `decision_memory_enabled=false`; durable lifecycle tests require checkpointing and enable memory only when a store is configured.
- [x] UI contract tests cover research delta, coverage, sources, claims, filings, transcripts/guidance, factors, peers, valuations, events, risks, monitoring, prior outcomes, and evaluation receipts.
- [x] The browser remains empty without a completed result and contains no research, run-control, credential, or broker actions.
- [x] `report`, `launch_research_report`, and `get_research_report_summary` provide preferred Research Dossier Viewer names while dashboard-named surfaces remain compatible.
- [x] Completed CLI and MCP responses carry a versioned presentation receipt; spawned-process tests prove one private loopback daemon is reused for multiple companies, observes later atomic publications and quality outcomes, survives the short-lived CLI command, recovers from killed or incompatible generations, and leaves publication-pending results hidden.
- [x] Detached-viewer tests prove per-daemon capability authentication, hostile Host/Origin rejection, restrictive browser headers, private registry permissions, startup diagnostics, headless no-spawn behavior, and per-call MCP presentation policy.
- [x] Documentation checks validate relative links, required canonical documents, Mermaid source/SVG pairs, poster HTML/PNG pairs, PNG dimensions, and SVG parseability.
- [x] Test startup assigns an isolated temporary `STOCKRESEARCHAGENTS_STATE_DIR` when the caller does not provide one, so offline verification does not write to a developer's normal state directory.
- [x] JSON metadata tests parse `.codex-plugin/plugin.json`, `.mcp.json`, workflow manifests, and terminal schemas.

## Legacy transition proof

- [x] The default credential-free MCP server excludes `run_legacy`; the opt-in executor remains isolated.
- [x] Transition and research-data tool manifests are machine-readable and must not report removal eligibility while a required gate is unverified.
- [x] The executable legacy-removal verifier fails closed on the canonical empty evidence index and independently derives local, provider/operational, release-attestation, external, and overall gate status. Evidence must bind exact clean `HEAD`, gate-specific referenced hashes, and an authenticated trust-root verifier.
- [ ] The line-item parity ledger covers every whitelisted observable and the pure-semantic probe passes, but fresh release commit/date/sign-off evidence is still absent.
- [ ] Concrete provider-neutral research-data MCP adapters are registered and conformant for every required category. Six public categories pass locally, but licensed prices/indicators and lawful social-provider coverage remain open.
- [x] CI checks out the exact upstream pin and runs a credential-free pure-semantic comparison of scoped observable contracts. This is not an LLM/provider graph dual-run.
- [x] Portable conformance reports portable pass/verification independently and records missing, matching, or mismatched upstream identity under a separate compatibility status.
- [ ] A representative live and failure symbol matrix has recorded, reproducible evidence.
- [x] Python, CLI, MCP, export/reload, dashboard, and RunView return the same canonical completed-run semantic projection and digest; the projection content-addresses every terminal artifact, evidence item, report section, and complete terminal research payload.
- [x] Complete retained historical-schema `2026-08-02` result/event goldens exercise strict migration plus copy-on-write store/export/memory receipts. These fixtures are not provenance-backed public-release artifacts.
- [ ] The published-release saved-result inventory and release-owner attestation are not yet reconciled.
- [ ] One published deprecation release has warned on every legacy entry point and named a later major removal version.
- [ ] Executor removal occurs only at the documented later major-version boundary.

Until every unchecked item passes together, legacy removal and complete observable behavioral-parity claims are prohibited.

## Verification commands

Run the credential-free gates from the repository root:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy --ignore-missing-imports src
uv run python -m compileall -q src tests
uv run python scripts/check_docs.py
uv build --offline
uv run pytest -q tests/test_manifests_and_mcp.py
uv run python scripts/verify_legacy_removal.py --expect-blocked
```

The fixture and CLI help are safe smoke checks:

```bash
uv run stock-research-agents fixture --events
uv run stock-research-agents --help
```

Record fresh counts and command results in the release or handoff report. Do not preserve a stale fixed test count or MCP tool count in this document.

## Not verified by local tests

- [ ] A live provider-backed company-research run.
- [ ] Live public-source freshness or coverage for any symbol.
- [ ] Seeking Alpha or another licensed provider integration, entitlement, or redistribution behavior.
- [ ] Credentialed upstream TradingAgents execution and checkpoint resume.
- [ ] Exact generated text or recommendation equivalence across hosts.
- [ ] Token-level continuation of an interrupted agent/tool call.
- [ ] Host-specific push event delivery or hard-interruption behavior.
- [ ] Live-network freshness and arbitrary-symbol coverage for the six default SEC/GDELT/World Bank tools; local tests use recorded transports and prove contracts, normalization, and registration rather than current upstream availability.
- [ ] Concrete licensed price/indicator retrieval, host-OAuth Reddit retrieval, or approved StockTwits access.
- [ ] Full behavioral upstream dual-run conformance with credentialed live providers; the pure-semantic pinned differential is implemented.
- [ ] Published-release migration attestation or a published legacy deprecation release.
- [ ] Broker or order execution; this is intentionally prohibited, not a validation target.
