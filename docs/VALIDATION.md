# Validation checklist

- **Purpose:** record what local, credential-free validation can establish.
- **Audience:** contributors, reviewers, and release owners.
- **Canonical for:** executable proof and explicit validation gaps.
- **Not canonical for:** architecture decisions or Research Quality interpretation semantics.

## Company Analytics and embedded research contracts

- [x] The embedded `stockresearchagents.company-research.v1` foundation has 15 contiguous ordered stages, resolves only earlier dependencies, declares capability IDs and research output references, and terminates its portion at `assemble.dossier` inside the 26-stage outer workflow.
- [x] Discovery returns `company-analytics.v1` as the one public product profile and identifies `CompanyResearchSubmissionV1` / `ResearchDossierV1` as its embedded foundation.
- [x] The research dataclass parser and JSON Schema require schema version `company-research.v1`, the company workflow ID, a typed request, and a completed dossier.
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
- [x] `SourcePort.fetch(capability, typed_query)` validation covers test-fixture, replay, and router adapters; typed queries reject explicit credentials and credential-bearing signed URLs before dispatch.
- [x] `SourceBatch` v1 validates exact query/capability pairing, cutoff, typed status, provenance, entitlement, completeness, pagination, limitations, and deterministic normalized observations. Every `SourceObservation` explicitly declares whether its digest covers source bytes, an exact bounded extract, or a normalized source record.
- [x] `SourcePortfolioCollector` attempts every explicitly registered provider route without changing `SourceRouter`; its bounded strict v1 receipt preserves each provider batch and entitlement, records sanitized failures and coverage gaps, emits unique deterministic route-qualified run-card batch IDs, and clusters exact duplicates without deleting observations.
- [x] Every observation in a `SourceBatch` must bind to the batch entitlement's license receipt, and run-card source-batch IDs must be unique.
- [x] Completed results are strict `CompanyAnalyticsResultV1` values that retain the exact parsed `CompanyAnalyticsSubmissionV1` and the seven required authoritative artifact kinds.
- [x] The isolated server launched by `stock-research-data-mcp` registers exactly seven receipt-backed public tools: three SEC, two GDELT metadata/link, one World Bank macro, and one Polymarket Gamma public search/read-only `prediction_markets` tool. The coordination MCP registers none of its tools.
- [x] SEC company-fact observations have provider-order-independent IDs and a hard item cap that reports omitted matches as partial coverage; GDELT observations have canonical-URI deduplication, provider-order-independent IDs, explicit seen-time semantics, and partial coverage at the result cap.
- [x] Polymarket Gamma results are current public market metadata only: probabilities remain market-implied observations rather than truth, forecasts, or executable signals; search cannot reconstruct historical snapshots; and wallet, CLOB, and order endpoints are absent.
- [x] Prices and indicators remain unregistered without a licensed caller `SourcePort`; Yahoo Finance/`yfinance` remains caller-owned and subject to applicable terms; Reddit remains unregistered without approved caller OAuth; StockTwits is denied and unregistered; FRED and Alpha Vantage are not defaults.

## Company-analytics v1/analytics contract

- [x] Prepare returns the 26-stage manifest, selected research pack, and one self-contained bundled analytics schema with typed analytics records.
- [x] Strict Python contracts validate cross-field semantics beyond JSON Schema, including the exact `<quality_run_id>.` prefix on every global `forecast_id`.
- [x] Analytics parsing and validation cover the embedded `CompanyResearchSubmissionV1` / `ResearchDossierV1`, analytics bundle, provider-neutral source-lineage crosswalk, run card, hypothesis ledger, iterations, quality receipt, and forecasts.
- [x] Source-lineage validation requires exact run-card batch membership, one-to-one coverage of every dossier document and analytics source license, and matching source IDs, canonical URIs, content digests, terms URIs, access, machine-use denial, and redistribution semantics.
- [x] Durable finalization preserves separate identities: lifecycle operations use the control `run_id`, while completed control state exposes the content-derived canonical publication ID as `result_run_id`; result events, reports, exports, and viewer routes use that canonical ID.
- [x] The exact result submission and seven `CompanyAnalyticsResultV1.artifacts` are authoritative. Quality-index stage/publish failure tests keep derived state hidden and reconstruct it from completed artifacts without claiming a distributed transaction.
- [x] With a caller-supplied `LifecycleStageExecutor`, the profile-neutral sequential runner executes all 26 primary stages, resumes from the first incomplete stage, and finalizes through the same analytics lifecycle coordinator.
- [x] Every primary stage exposes a strictly validated `stage-instructions.v1` role, objective, completion criteria, dependencies, semantic capabilities, and output references without provider, model, Codex, or graph-framework coupling.

## Numerical, peer, structured-challenge, and sanitized-context validation

- [x] Metrics require finite numbers, units, economic periods, and an exact cutoff-safe information vintage. Calculated metric values and units bind to deterministic calculation receipts and cannot predate their inputs.
- [x] The validation engine recomputes bounded deterministic formulas, requires all declared metrics/constants, validates formula shape against the typed operation, applies rounding and absolute tolerance, and rejects tampered calculation, valuation, and sensitivity outputs.
- [x] Peer records require inclusion rationale and normalization methodology.
- [x] Structured-challenge turns require claim links; rebuttals must target an earlier argument in the same challenge, and concessions and unresolved items must be unique and disjoint.
- [x] Completed dossiers require at least two distinct argument roles and at least one explicit rebuttal; validation does not infer hidden runtime roles or a trading workflow.
- [x] Supersession links reject missing, self-referential, and cyclic targets.
- [x] Portfolio fields require an explicit non-execution boundary and reject private account/customer identity.
- [x] Credential-shaped keys are rejected recursively.

## Memory and lifecycle

- [x] Exact-cutoff memory recall filters decisions before applying same/cross-symbol limits and filters outcomes independently by `observed_at`.
- [x] Recall excludes later `created_at`, later decision `as_of_date`, and embedded post-cutoff filing/event/metric-vintage/outcome availability while retaining cutoff-safe forecasts with future economic periods; malformed historical rows and outcomes fail closed without aborting safe recall.
- [x] Staged decisions remain outside recall until final publication.
- [x] `CompanyAnalyticsCoordinator` tests cover all 26 ordered stage commits, strict opaque reference descriptors, digest-bound receipts, optimistic revision conflicts, pause/resume, cooperative cancellation, cursor events, fresh-coordinator recovery, cutoff-safe memory recall, rejection of out-of-order dependency-ready commits, analytics terminal validation, report descriptor rebinding, quality-index staging/publication, and crash reconstruction.

## Plan/import, UI, and package surfaces

- [x] Python, CLI, and MCP plan/import tests validate the company request, return the frozen manifest/schema, import a complete research payload, and publish content-addressed symbol-specific results.
- [x] Public lifecycle routing tests create Company Analytics runs through `analytics-init`/`create_company_analytics_run` and route `run-control.v1` operations to the coordinator by run ID.
- [x] Analytics lifecycle routing tests create analytics runs through `analytics-init`/`create_company_analytics_run` and route the shared lifecycle controls without duplicating the protocol.
- [x] Repeated identical imports are idempotent; different company submissions receive different run IDs.
- [x] `CompanyAnalyticsResultV1.submission` preserves the exact request and dossier losslessly; the dossier is also one of the seven authoritative artifacts, while `RunView.research_request` and `RunView.research_dossier` are projections.
- [x] Report tests prove exactly five ordered derived groups: Executive Summary, Evidence and Claims, Analytics and Valuation, Risks and Counterevidence, and Monitoring and Quality.
- [x] Research-mode tests read the authoritative value from `RunView.research_request` for live, fixture, and historical replay submissions.
- [x] Direct import tests require `checkpoint_enabled=false` and `decision_memory_enabled=false`; durable lifecycle tests require checkpointing and enable memory only when a store is configured.
- [x] UI contract tests cover research delta, coverage, sources, claims, filings, transcripts/guidance, factors, peers, valuations, events, risks, monitoring, prior outcomes, and evaluation receipts.
- [x] The browser remains empty without a completed result and contains no research, run-control, credential, or broker actions.
- [x] `report`, `launch_research_report`, and `get_research_report_summary` expose the completed-results-only Research Dossier Viewer.
- [x] Completed CLI and MCP responses carry a versioned presentation receipt; spawned-process tests prove one private loopback daemon is reused for multiple companies, observes later atomic publications and quality outcomes, survives the short-lived CLI command, recovers from killed or protocol-mismatched generations, and leaves publication-pending results hidden.
- [x] Detached-viewer tests prove per-daemon capability authentication, hostile Host/Origin rejection, restrictive browser headers, private registry permissions, startup diagnostics, headless no-spawn behavior, and per-call MCP presentation policy.
- [x] Documentation checks validate relative links, required canonical documents, Mermaid source/SVG/PNG sets, GitHub preview references, poster HTML/PNG pairs, PNG dimensions, and accessible SVG structure.
- [x] Test startup assigns an isolated temporary `STOCKRESEARCHAGENTS_STATE_DIR` when the caller does not provide one, so offline verification does not write to a developer's normal state directory.
- [x] JSON metadata tests parse `.codex-plugin/plugin.json`, `.mcp.json`, workflow manifests, and terminal schemas.

## Standalone integration proof

- [ ] Concrete provider-neutral research-data MCP adapters are registered and conformant for every required category. Seven public tools pass locally, but licensed prices/indicators and lawful social-provider coverage remain open; prediction-market metadata does not close either gap.
- [ ] A representative live and failure symbol matrix has recorded, reproducible evidence.
- [x] Python, CLI, MCP, export/reload, viewer, and RunView return the same canonical completed-run semantic projection and digest; the projection content-addresses every terminal artifact, evidence item, report section, and complete terminal research payload.
- [x] Current-schema result/event goldens exercise strict reload plus hash-bound store/export/memory receipts.

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
- [ ] Exact generated text or recommendation equivalence across hosts.
- [ ] Token-level continuation of an interrupted agent/tool call.
- [ ] Runtime-specific push event delivery or hard-interruption behavior.
- [ ] Live-network freshness and arbitrary-symbol/query coverage for the seven default SEC/GDELT/World Bank/Polymarket Gamma tools; local tests use recorded transports and prove contracts, normalization, and registration rather than current provider availability.
- [ ] Concrete licensed price/indicator retrieval, host-OAuth Reddit retrieval, or approved StockTwits access.
- [ ] Broker or order execution; this is intentionally prohibited, not a validation target.
