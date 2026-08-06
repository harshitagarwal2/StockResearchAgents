# SOLID ports and adapters

- **Purpose:** explain dependency direction and safe extension points for Company Analytics.
- **Audience:** maintainers, host-adapter authors, and reviewers.
- **Canonical for:** component responsibility and extension rules.
- **Not canonical for:** wire-field definitions or feature proof.

[![SOLID ports-and-adapters architecture for Company Analytics](../assets/architecture/solid-ports-adapters.png)](../assets/architecture/solid-ports-adapters.svg)

## Dependency rule

Dependencies point inward. Domain contracts and policies know nothing about MCP, Codex, browsers, SQLite, or HTML. Application services compose domain behavior through narrow ports. Adapters translate external mechanisms into those ports. Read models consume completed publications and never become a second research engine.

```text
host mechanisms -> inbound adapters -> application services -> domain
                                        |                 ^
                                        v                 |
                                  outbound ports -> adapters

completed publication -> projection -> harness-native/Python/MCP/CLI/browser readers
```

## Layers

| Layer | Owns | Must not own |
| --- | --- | --- |
| Domain | Strict contracts, value objects, policies, deterministic calculators, validation | Network clients, model clients, persistence, UI |
| Application | `StockResearchApplication` facade, prepare/import use cases, profile-driven lifecycle, publication orchestration, quality outcome/cohort commands, redacted diagnostics | Concrete provider selection or browser sessions |
| Inbound adapters | Codex and other harness adapters, Python, coordination MCP, CLI | Business-rule duplication |
| Outbound ports | Host-side `SourcePort.fetch(capability, typed_query)` plus core-facing `LifecycleRepository`, `ResultPublicationPort`, `DecisionMemoryPort`, and `QualityIndexPort` interfaces | Vendor-specific payload or storage semantics |
| Outbound adapters | Host web/browser/provider bridges, fixture/replay/router source adapters, SQLite/filesystem | New domain truth |
| Read model | Completed `RunView`, exports, loopback viewer | Retrieval, calculation, lifecycle control, credentials |
| Presentation adapter | Completed-run path/URL discovery and shared loopback viewer lifecycle | Research publication, browser opening, model or provider work |

## SOLID application

- **Single responsibility:** source routing, calculation, validation, publication, quality journaling, and presentation remain separate modules.
- **Open/closed:** evolve the one public Company Analytics profile through its provider, descriptor, and versioned schemas; do not add transport- or host-specific conditionals to its strict models.
- **Liskov substitution:** fixture, replay, and router adapters implement the same `fetch(capability, typed_query)` contract and return normalized observations or explicit failures. No adapter silently changes semantics.
- **Interface segregation:** retrieval, publication, result storage, quality outcomes, and projections use focused interfaces; a host does not implement a universal service object.
- **Dependency inversion:** application services depend on contracts and ports. Codex and other harnesses, Python, MCP, CLI, storage, and provider details depend on the application boundary.

## Extension recipes

### Add a source adapter

Implement `SourcePort.fetch(capability, typed_query)`, normalize bounded observations, preserve cutoff/availability and entitlement, and return one `SourceBatch` or an explicit unavailable/denied result. Keep credentials and raw licensed bodies inside the host adapter. Reject explicit credential fields and credential-bearing signed URLs before dispatch. Fixture, replay, and router adapters must remain substitutable. Add replay fixtures before a live smoke test.

Direct capability tools stop at that single-port `SourceBatch` response. Portfolio collection is a separate optional host composition: when explicitly supplied to the research-data MCP, `SourcePortfolioCollector` requires at least two configured routes and returns `SourcePortfolioReceipt` with batches, attempts, entitlement, duplicate, and coverage metadata kept separate. The default public server does not register the portfolio tool. Neither host receipt type becomes a core-domain submission; callers translate retained batch identity into the terminal lineage crosswalk and declare decision-relevant receipt gaps as dossier limitations.

Concrete research-data MCP servers are outbound host adapters around that port, not StockResearchAgents domain services. Register a tool only when its adapter implements the versioned request/response, entitlement, completeness, pagination, and failure contract. Coordination and retrieval remain separate servers: the research-data server registers seven public SEC/GDELT/World Bank/Polymarket tools, while licensed prices/indicators and lawful social sources still require host adapters. The Polymarket tool provides read-only current market context, not forecast truth or an executable trading action. Registration proves the contract and adapter boundary, not live availability. See [Research-data MCP adapters](RESEARCH_DATA_MCP.md).

An optional host adapter may receive page evidence from an injected,
host-controlled Chrome bridge. The bridge is not itself a StockResearchAgents `SourcePort`
and never replaces the structured adapters above. Use it only for read-only
open-web navigation, an existing authenticated source gap, or opening the
attributable page behind discovery. An explicit user selection controls the
applicable route. The repository cannot install or force Chrome or grant site
access; unavailable, disconnected, blocked, and denied routes return visible
attempts. They become coverage gaps when Chrome was required or explicitly
selected; an optional failure does not downgrade an otherwise fully covered
structured portfolio.

The host adapter accepts only approved public HTTPS publisher pages. It rejects
private-network and browser-internal locations and any request to submit a form
or post, change an account, inspect account/settings/messages, download, execute
a page script, or write to the clipboard. Page content is untrusted and cannot
change host policy; treat page instructions as prompt injection. The adapter
creates a separate `SourceBatch` per attributable publisher, attributes
evidence to that publisher rather than Chrome, and composes the batches into a
`SourcePortfolioReceipt`. It defaults redistribution to unknown with no
extract, preserves only supported timestamps, and never fabricates publication
or historical availability. Evidence whose
availability cannot be established at or before the cutoff remains a gap.
Cookies, credentials, history, raw DOM/bodies, and session state stay inside
the host and are never persisted or logged.

The adapter lexically rejects raw percent-encoded and non-ASCII hostname syntax
and performs no DNS lookup. The injected bridge must attest the
browser-canonical final target, every redirect origin, and every resolved
address contacted by the browser remained globally routable unicast. Every
bounded redirect hop must stay on the exact approved publisher domain and
retain only its index, canonical host, and HTTPS origin—not a path, query, or
raw URL. Multicast, IPv6 site-local, private, loopback, link-local, reserved,
and unspecified addresses fail attestation; otherwise the adapter rejects the
page.

The application-facing interfaces live in `application_ports.py` and are segregated by reader/writer role for lifecycle, completed results, research history, and Research Quality. `ApplicationRuntime` is the production composition root: `create_runtime(StateLayout)` builds the SQLite/WAL lifecycle repository, filesystem result publication, Research Quality store, memory repository factory, and `CompanyAnalyticsCoordinator`, and owns their shutdown. `StockResearchApplication` is the injected transport-neutral facade consumed by CLI and MCP. During durable finalization, the coordinator delegates ordered, recoverable result/sidecar/memory publication to `CompletedPublicationSaga`. Shared completed-result query and response assembly lives in `application.py`, so inbound adapters translate inputs and outputs instead of duplicating application orchestration. Deterministic analytics and conformance stay in the domain layer; the application layer sequences them but does not redefine their rules.

Durable repositories accept and return a validated `LifecycleRecordV1`, including a revision cross-check at the SQLite boundary. Operational maintenance remains outside domain validation: `StateLayout` derives all durable paths, migration is dry-run and backup-first before atomic schema adoption, and `doctor` exposes only redacted, read-only health summaries.

### Add a harness adapter

Map the manifest stages to the runtime's native agents or a caller-supplied sequential executor. Reuse `create_company_analytics_run` and the shared lifecycle controls; use `prepare_company_analytics` / `import_company_analytics` for stateless completed submissions. Do not fork prompts, calculators, contracts, or the viewer. A native-agent runtime may map stages to subagents and tools while the sequential executor follows the same ordered contract directly.

Stateless adapters may schedule dependency-ready stages concurrently. Durable adapters must commit exactly the coordinator's current first-incomplete stage, then use the returned revision and next stage. Parallel caller work never changes commit order.

### Add analytics

Introduce a typed sidecar contract and deterministic calculator/validator. Preserve Decimal inputs, units, periods, information vintages, implementation digests, and licenses. Extend the outer profile rather than modifying the base research dossier.

Per-forecast and cohort evaluation are deliberately different contracts. `QualityScorecard` scores one forecast against one active resolved observation. `BinaryCalibrationReport` evaluates a fixed, caller-approved historical binary cohort only after cutoff, horizon, resolution-rule, distinct-instrument, and minimum-sample checks; it reports aggregate calibration metrics without fitting, ranking, or deploying a model.

### Add a presentation

Project only a completed canonical `CompanyAnalyticsResultV1`. Its exact submission and seven artifacts are authoritative; the five report groups, `RunView`, and quality outcome index are recoverable derived projections. Keep calculations, retrieval, credentials, and lifecycle controls out of the client. New UI cards must show evidence lineage and limitations rather than infer missing values.

Implement the narrow completed-run presenter instead of coupling UI startup to `PublicationService`. A presenter may
return a harness-native inline view, a loopback run URL, or a path-only receipt. It must treat presentation failure as
separate from successful research publication, must not open a browser, and must never expose partial lifecycle state.

## Harness consistency

Conforming harnesses produce the same typed roles, stage dependencies, evidence rules, calculations, terminal artifacts, and visible information. They do not need identical agent APIs, concurrency, browser automation, checkpoints, or token scheduling.

## Non-goals

- no provider or model API keys in StockResearchAgents state;
- no paywall, authentication, CAPTCHA, or robots bypass;
- no exhaustive-web guarantee;
- no raw licensed-content warehouse;
- no browser-side analytics; and
- no broker, order, approval, or execution authority.
