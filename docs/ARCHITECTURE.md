# StockResearchAgents architecture

- **Purpose:** define implementation boundaries, components, state transitions, persistence, and completed presentation.
- **Audience:** host integrators, maintainers, and reviewers.
- **Canonical for:** system structure and module ownership.
- **Not canonical for:** product language, wire-field definitions, version status, or proof.

## Architectural drivers

StockResearchAgents separates host-owned research execution from portable contracts, validation, persistence, and final projection. Its primary `company-analytics.v1` profile composes the frozen evidence-first dossier with deterministic analytics, research-lab records, forecasts, and evaluation without embedding a model client or provider.

The design is driven by five invariants:

1. Any capable harness can execute the same workflow semantics.
2. Credentials, provider clients, exact prompt wording, source terms, and intermediate criterion attestations remain host-owned; portable stage roles, objectives, and completion-criteria declarations remain versioned workflow semantics, while Portable verifies the terminal bundle and coordinator commitments.
3. Strict point-in-time contracts and deterministic conformance are portable.
4. Partial lifecycle state never becomes a completed research artifact.
5. No portable surface gains broker, order, approval, or execution authority.

## System at a glance

[![Technical system context showing the host boundary, portable contracts, publication gate, completed dossier, viewer, and exports](../assets/architecture/system-context.png)](../assets/architecture/system-context.svg)

[![SOLID ports-and-adapters view of Company Analytics](../assets/architecture/solid-ports-adapters.png)](../assets/architecture/solid-ports-adapters.svg)

External evidence enters only through a research host. The host sends typed submissions and bounded stage descriptors across the trust boundary. Portable conformance and publication decide whether a Completed Research Dossier exists; the viewer and exports read that completed artifact only.

Portable conformance is independent of the optional upstream checkout. `ConformanceReport.passed` and `verified` describe StockResearchAgents' own deterministic checks; the serialized `upstream_compatibility` block separately reports whether the exact external oracle revision was checked and matched. Missing or mismatched upstream evidence therefore cannot turn a portable success into a portable failure, and portable success cannot be presented as verified upstream compatibility.

## Evidence-to-dossier flow

[![Evidence-to-dossier flow showing the host-owned SourcePort, portable lineage checks, explicit coverage limitations, the conformance gate, and completed-only readers](../assets/architecture/source-to-dossier.png)](../assets/architecture/source-to-dossier.svg)

The host may retrieve public or entitled data through its `SourcePort`; `SourcePortfolioCollector` validates routes, isolates failures, and retains bounded `SourceBatch` records before the host derives the portable terminal lineage fields carried by the v4 submission. Host `SourceBatch` and `SourcePortfolioReceipt` types do not cross as portable-domain types. The portfolio receipt keeps sanitized failed attempts and coverage gaps host-side; the host must carry decision-relevant gaps into the submission as explicit limitations. Portable validates the crosswalk's identity, digest scope, and entitlement fields alongside the dossier's separate temporal provenance, then validates the resulting claims and calculations. A rejected terminal submission is not published. An accepted dossier may represent incomplete coverage only through an explicit limitation. Only an atomically published dossier reaches the viewer, MCP, or exports.

## Architectural patterns

[![StockResearchAgents architecture map showing inbound adapters, application services, domain rules, and outbound adapters](../assets/architecture/portable-patterns.png)](../assets/architecture/portable-patterns.png)

[Open the full-resolution architecture pattern map.](../assets/architecture/portable-patterns.png)

| Pattern | Concrete use | Why it exists |
| --- | --- | --- |
| Ports and adapters | CLI, MCP, Python, Codex, host submissions, optional upstream adapter | Keeps harness and transport APIs replaceable |
| Anti-corruption layer | Strict host-submission parsing and upstream `TradingAgentsGraph` adapter | Prevents external runtime semantics from leaking into the domain |
| State machine | Lifecycle statuses, optimistic revisions, pause/resume, cancellation, finalization | Makes legal transitions and recovery boundaries explicit |
| Specification pattern | Temporal, numerical, referential, completeness, entitlement, and safety checks | Keeps conformance deterministic and composable |
| Repository pattern | SQLite/WAL lifecycle, decision memory, atomic result store | Separates durable storage from domain rules |
| Projection pattern | `RunView`, exports, Research Dossier Viewer | Prevents presentation from becoming an authority |
| Content-addressed value objects | Dossier/result digests and safe stage descriptors | Makes identity, idempotency, and integrity explicit |
| Parallel contract versioning | v1/v2 compatibility beside v2/v3 company research | Adds semantics without mutating frozen readers |

Patterns are used only where they protect a real boundary. The codebase deliberately avoids a dependency-injection framework, generic command bus, continuously running projector, or repository abstraction for every dataclass.

## Authority boundary

The host harness owns:

- exact model prompts, reasoning, native agent scheduling, and exact generated text;
- concrete filing, market, news, transcript, and other retrieval;
- provider credentials, tool authentication, entitlements, and source terms;
- exact-cutoff retrieval decisions and adaptive-history expansion; and
- hard interruption of in-flight work.

The portable core owns:

- versioned wire contracts and workflow manifests;
- recursive credential, raw-content, and execution-field rejection;
- temporal, referential, numerical, debate, portfolio, and completeness validation;
- bounded stage envelopes and safe execution receipts;
- SQLite/WAL lifecycle state, optimistic revisions, atomic result/event publication, and report export;
- publication-gated, exact-cutoff-safe decision memory; and
- completed-result `RunView`, MCP reads, and loopback browser projection.

No browser or portable workflow component owns research logic.

## Version map

```text
financial-research.v1  -> host-submission.v2 -> existing RunResult
        |                       |
        +-> run-lifecycle.v1 ---+

company-research.v2   -> host-submission.v3 -> research_dossier.v3
        |
        +-> CompanyResearchCoordinator (Python lifecycle implementation)

company-analytics.v1  -> host-submission.v4 -> unchanged v3 + typed sidecars
        |
        +-> analytics-profile CompanyResearchCoordinator + Research Quality outcome journal
```

`company-research.v2` is a parallel extension. It does not mutate the frozen `financial-research.v1` or `host-submission.v2` contracts. Discovery returns both profiles and their compatibility relationship.

`company-analytics.v1` is a parallel outer profile. It embeds an unchanged v3 submission and adds analytics, run-card, hypothesis, iteration, quality, and forecast sidecars. This is additive contract composition, not a mutation of the v3 dossier.

[Compatibility](COMPATIBILITY.md) is canonical for version status and migration rules.

## Company-research execution

`prepare_company_research` validates a `CompanyResearchRequest` and returns the ordered manifest, routing semantics, portable boundary, sequential fallback, and frozen v3 terminal schema. The host then executes these stages:

| Ordinal | Stage | Main contract responsibility |
| ---: | --- | --- |
| 1 | `research.plan` | Objectives, coverage, latest-data checks, adaptive history, stop conditions. |
| 2 | `evidence.official` | Filings, investor relations, exact availability. |
| 3 | `evidence.market` | Market history and latest-session verification. |
| 4 | `analysis.financial` | Filing, guidance, and transcript analysis. |
| 5 | `analysis.company` | Company events, peers, and factors. |
| 6 | `audit.evidence` | Claim grounding, counterevidence, coverage, and temporal audit. |
| 7 | `verify.numerical` | Deterministic recalculation and unit/period reconciliation. |
| 8 | `debate.bull` | Grounded bullish argument. |
| 9 | `debate.bear` | Counterclaim, counterevidence, and rebuttal. |
| 10 | `synthesis.valuation` | Scenario valuation with calculation links. |
| 11 | `synthesis.risk` | Risk scenarios and sanitized portfolio context. |
| 12 | `research.delta` | Cutoff-safe memory and change-from-prior research. |
| 13 | `research.monitor` | Monitoring triggers and consequences. |
| 14 | `evaluate.final` | Evidence, numerical, temporal, and completeness evaluation. |
| 15 | `publish.dossier` | Completed-only atomic publication. |

Every stage declares only capability identifiers and JSON Schema output references. Concrete providers are absent from the manifest.

## V3 terminal contract

`host-submission.v3` contains the original request and one `ResearchDossierV3`. Both use schema version `2026-08-03.v3`; the workflow ID is `tradingagents.company-research.v2`.

The request freezes:

- exact `requested_at` and `cutoff_at` timestamps;
- typed instrument identity and truthful `research_mode` (`live`, `fixture`, or `historical_replay`);
- research objectives, coverage dimensions, history windows, latest-data checks, and stop conditions;
- output language; and
- optional sanitized, explicitly non-executable portfolio context.

The completed result retains the request and dossier as distinct lossless artifacts. `research_request.v3` is authoritative for request semantics such as `research_mode`, exact cutoff, plan, and optional portfolio context. `research_dossier.v3` contains first-class documents, calculations, metrics, claims, arguments, filings, filing changes, transcripts, guidance, peers, factors, valuations, entities, events, risks, monitoring, prior outcomes, evaluation, research delta, coverage, recommendation, summary, limitations, and optional portfolio impact.

All IDs are local to the dossier and cross-references must resolve. Documents retain bounded extracts only when redistribution is permitted. The terminal artifact is size-bounded and cannot contain credential-shaped, raw-source, or execution material.

## Company-analytics execution

`prepare_company_analytics` returns a 26-stage manifest, a selected research pack, and the execution mode selected before work starts. `compatible` is locally ready, `full` requires a host adapter, and `tools_only` remains partial until live research adapters are supplied. Stages 1–15 build and audit the frozen v3 dossier. Stages 16–26 add falsifiable hypotheses; fundamentals; DCF, reverse-DCF, comparables, and sensitivities; consensus; positioning; catalyst mapping; point-in-time experiment plans/receipts; Research Quality; and atomic completed publication.

For a stateless plan, the host may execute dependency-ready work with native subagents and parallel tools before importing one complete payload. A durable full-mode run still commits one current first-incomplete stage at a time; parallel retrieval does not relax coordinator ordering. Every primary stage carries a versioned role, objective, completion criteria, semantic capabilities, dependencies, and output references. The profile-neutral sequential runner drives those same coordinator boundaries for a compatible one-agent host and resumes from the first incomplete stage. The portable semantics and terminal information remain the same; exact prompt wording, agent spawning, and scheduling do not.

The analytics-profile `CompanyResearchCoordinator` (`COMPANY_ANALYTICS_COORDINATOR`) provides the public 26-stage lifecycle through `analytics-init` / `create_company_analytics_run` and shared lifecycle controls. It checkpoints bounded stage descriptors and optional safe receipts, accepts only the current first-incomplete stage, validates the terminal v4 payload, and binds the final run card to coordinator-owned envelope and commit-receipt digests for all 26 stages. The terminal commitment uses a normalized publication-candidate digest so the contract is not circular. It also rejects a terminal run card whose execution mode differs from the mode fixed at run creation. Completed `RunResult.artifacts` are the atomically published source of truth for analytics and quality sidecars. The separate quality outcome index uses hidden stage/publish steps and can be reconstructed from completed artifacts after a crash; the design does not claim a distributed transaction. Atomic complete import remains available when lifecycle state is unnecessary.

[![Durable Company Analytics lifecycle showing ordered stage commits, checkpoints, pause and recovery, terminal cancellation, finalizing, and completed-only publication](../assets/architecture/company-analytics-lifecycle.png)](../assets/architecture/company-analytics-lifecycle.svg)

The host can perform dependency-ready retrieval or analysis in parallel, but a durable run commits exactly one current first-incomplete stage at a time. Each accepted commit creates a new SQLite/WAL revision; pause and crash recovery return to that ordered boundary, while acknowledged cancellation is terminal. A valid final v4 bundle enters a recoverable `FINALIZING` phase that stages the canonical result and derived quality/memory sidecars before publication. This makes a sequential fallback and a native multi-agent host observably compatible without claiming identical agent scheduling.

`prepare_company_analytics` returns a self-contained bundled v4 schema containing typed analytics and inward source-lineage definitions. `source-lineage-crosswalk.v1` preserves provider-neutral host batch/observation identities without moving credentials or raw content into portable state. It declares whether each digest covers authoritative source content, an exact bounded UTF-8 extract, or a normalized source record, then joins that identity to the dossier document, analytics source/license receipt, and run-card batch set. JSON Schema validates shape and local URI/digest constraints; strict Python contracts remain authoritative for complete referential and entitlement equality and for cross-field rules such as the global requirement that every `forecast_id` start with `<quality_run_id>.`.

## Temporal model

The request cutoff is an exact instant, not only a market date. The dossier `as_of_at` must match it exactly.

Source documents separate:

- when an event or source was published;
- when it became available to the research process;
- when the host retrieved it; and
- the cutoff used for the run.

Completed-contract validation rejects documents, filings, metric information vintages, transcript events, factor observations, historical events, and prior outcomes that were unavailable at the cutoff. A metric's `period_end` is its economic period, while `metric.as_of_at` is the cutoff-safe information vintage for the value. Reported metrics cannot describe a period later than their vintage; estimates, assumptions, and deterministic calculations may describe future periods when every input and supporting document was available by their declared vintage. Later processing and completion timestamps are allowed because validation distinguishes evidence availability, economic period, and processing time.

Decision memory applies the same model. Historical recall filters decisions before result limits, filters outcomes independently by observation time, and excludes embedded evidence availability later than the cutoff. Unparseable legacy availability metadata fails closed.

## Calculation and claim integrity

Claims link directly to source documents and metrics. Counterclaims and counterevidence remain separate. Debate turns link to claims and assumptions, name concessions and unresolved issues, and may rebut only an earlier turn in the same debate.

Calculated metrics and valuations use deterministic calculation receipts: engine, operation, formula, input metric IDs, constants, result, unit, tolerance, and rounding. Semantic conformance safely recomputes bounded arithmetic, requires every declared input and constant to appear in the formula, verifies the formula shape against the declared operation, applies decimal rounding followed by the declared absolute tolerance, and checks valuation and sensitivity outputs against referenced calculation results. Model prose cannot substitute for a calculation receipt.

## Completeness and entitlements

Completeness means declared decision-relevant coverage, not omniscience. Every planned coverage dimension must appear in the dossier. `complete` requires retained sources; `partial`, `missing`, `stale`, `conflicting`, `entitlement_blocked`, and `not_applicable` require an explicit limitation.

The host owns entitlement checks. Licensed sources may be referenced only under the host's rights. A non-redistributable source is metadata/reference only and cannot carry an extract, including a bounded one. Seeking Alpha content, transcripts, scores, ratings, and proprietary methodology are not bundled or treated as portable-owned data; its product patterns may inform UX, but content access remains a host licensing concern. The normalized `SourcePort` exposes one `fetch(capability, typed_query)` operation. Fixture, replay, and router adapters implement it, and query validation rejects credentials embedded in signed URLs as well as explicit credential fields.

## Lifecycle and publication

[![Completed-only publication sequence showing the host, portable core, durable storage, and viewer](../assets/architecture/completed-publication.png)](../assets/architecture/completed-publication.svg)

The viewer receives no partial-stage path. A terminal submission is validated, staged, and atomically committed before the completed read model becomes visible.

The existing public `run-lifecycle.v1` tools operate the compatibility workflow. `CompanyResearchCoordinator` implements the equivalent durable concepts across all 15 company-research stages:

- private SQLite/WAL records and strict nonterminal opaque-reference envelopes;
- optimistic revisions and first-incomplete-stage resume;
- capability-scoped safe receipts with optional input/output digests;
- pause, cooperative cancel request, and host acknowledgement;
- cursor-readable lifecycle events;
- strict validation of the terminal `publish.dossier` envelope;
  - recoverable staging of result/events and derived indexes without claiming a distributed transaction; and
- completed-only publication.

Inbound adapters create the same company run: the CLI exposes `company-init`, while MCP and native hosts use `create_company_research_run` or the corresponding Python coordinator. Shared lifecycle operations resolve the coordinator from the run record, so start, receipts, commits, pause/resume, control, events, cancellation, finalization, export, and completed reads work without duplicating application logic per adapter.

Persistence flags describe observed execution, not requested intent. Stateless `company-import` has no lifecycle checkpoint or memory publication, so both flags are false. Durable company finalization sets checkpointing true. The public coordinator supplies a durable memory store by default. Custom coordinators either provide a store/factory, disable memory explicitly, or fail when memory is requested; they never silently downgrade the capability.

## Completed-result projection

`submit_company_research` converts a validated submission into the existing portable `RunResult`, preserves the request as `research_request.v3` and the complete dossier as `research_dossier.v3`, builds reports, and publishes result/events atomically. Content-derived run IDs make repeated stateless imports idempotent and keep different company submissions separate.

`RunResult` capability flags derive from the declared research mode. Deterministic fixtures remain labeled fixture data; only a host submission that truthfully represents live retrieval may be labeled live.

`build_run_view` projects both v3 artifacts without interpreting their contents. `research_request` preserves the authoritative request and `research_dossier` preserves the completed output. The browser renders only when the run status is completed. It displays research delta, coverage, source provenance, claims, earnings/filings, transcripts/guidance, factors, peers, valuations, events, risks, monitoring, prior outcomes, and evaluation receipts. Partial lifecycle state never becomes a dossier.

Presentation is an adapter invoked only after that atomic publication succeeds. It returns a runtime-local
`presentation-link.v1` receipt and ensures one reusable loopback viewer daemon per durable state directory. The same
static application renders every company by loading the typed run selected through `?run=<run_id>`; no per-company
HTML generation exists. The daemon rereads atomic durable bundles on each request so later publications become visible
without restarting it, and it reopens the append-only quality projection so later outcome observations are visible.
A private cross-process lifetime lease preserves the one-daemon invariant. A capability-token bootstrap, exact
loopback Host/Origin checks, browser security headers, and protocol/package/schema/asset identity checks protect the
detached boundary. A path-only adapter supports headless harnesses, and viewer failure never changes the completed
research result.

## Research Quality boundary

Research Quality is an implemented v4 sidecar capability. It owns policy/run provenance, forecasts issued at publication, typed later outcome observations, decision-support status, and deterministic evaluation.

It does not own retrieval, provider health workers, prompts, execution, portfolio mutation, or browser-side scoring. The frozen v3 dossier remains unchanged; the v4 wrapper carries the parallel artifacts described in [Research Quality](RESEARCH_QUALITY.md) and [Compatibility](COMPATIBILITY.md).

## Code location map

| Concern | Canonical location |
| --- | --- |
| Generic portable contracts | `src/tradingagents_portable/contracts.py` |
| Company-research contracts | `src/tradingagents_portable/research_contracts.py` |
| Company-research conformance | `src/tradingagents_portable/research_conformance.py` |
| Workflow manifests and schemas | `src/tradingagents_portable/workflow/` |
| Company planning/import | `src/tradingagents_portable/company_research.py` |
| Company durable lifecycle | `src/tradingagents_portable/company_lifecycle.py` |
| Company analytics profile | `src/tradingagents_portable/company_analytics_v1/`, `company_analytics.py` |
| Deterministic analytics | `src/tradingagents_portable/analytics_v1/` |
| Research lab and packs | `src/tradingagents_portable/research_lab_v1/` |
| Research Quality | `src/tradingagents_portable/research_quality_v1/` |
| Host source ports/adapters | `src/tradingagents_host/` |
| Generic lifecycle/store/memory | `lifecycle.py`, `store.py`, `memory.py` |
| Completed projection | `view.py`, `report_server.py`, packaged `web/` |
| Automatic presentation | `presentation.py`, `viewer_daemon.py` |
| Inbound CLI/MCP adapters | `cli.py`, `mcp_server.py` |
| Optional upstream adapter | `legacy.py`, `legacy_mcp_server.py` |

## Target runtime direction

The product target is the host-native portable core, not a Codex-specific or LangGraph-specific core. Codex, generic multi-agent hosts, the one-agent sequential fallback, and tools-only MCP consumers translate their mechanisms into the same versioned stages and terminal contracts. Lifecycle, memory, export, and completed-only presentation remain common.

Concrete research-data MCP implementations are a host-adapter concern. The isolated server launched by `stock-research-data-mcp` now registers seven public metadata/fact tools: SEC filings, fundamentals, and statements; GDELT company and global news metadata plus publisher links; World Bank macro observations; and read-only Polymarket current-market context. The prediction-market projection is neither forecast truth nor an executable trading action. The manifest retains `tradingagents-research-data` as its compatibility key. Licensed price/indicator adapters, host-OAuth Reddit, and approved StockTwits access are still absent from the default server. Provider SDKs, credentials, sessions, and entitlement enforcement stay outside the portable domain; current registration is not proof of live availability or complete company coverage. The adapter contract and proof requirements are defined in [Research-data MCP adapters](RESEARCH_DATA_MCP.md).

The optional upstream executor is transitional. It remains available and not deprecated until the gates in [Legacy executor transition](LEGACY_TRANSITION.md) pass. CI now checks the exact pin with a credential-free pure-semantic differential over the declared whitelist; complete LLM/provider behavior and live correctness remain outside that proof. Even after executor removal, frozen schemas/readers and migrated historical results remain supported.

## Optional upstream adapter

The legacy adapter imports and invokes upstream `TradingAgentsGraph`; it does not fork upstream prompts, provider clients, LangGraph nodes, or persistence internals. LangGraph remains a thin optional runtime adapter for compatibility and differential development, not a dependency of the portable domain. The default plugin server does not register the legacy executor. Importability and revision identity prove neither behavioral parity nor provider credentials, data access, checkpoint resume, or a successful live run.

## Security and safety invariants

- No portable input or output carries API keys, tokens, authorization headers, or provider configuration secrets.
- No raw copyrighted filing or transcript body belongs in the bounded dossier.
- No broker/order execution field or UI action is allowed.
- Portfolio context is optional, sanitized, and explicitly non-executable.
- The dashboard binds only to loopback and exposes read-only completed results.
- Missing sources and licensed-data gaps remain visible; no silent fallback is allowed.
