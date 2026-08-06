# Capability and proof ledger

- **Purpose:** separate implemented StockResearchAgents behavior from host-dependent execution and unverified integrations.
- **Audience:** maintainers, reviewers, and release owners.
- **Canonical for:** capability status and proof boundary.
- **Not canonical for:** product terminology or contract definitions.

| Capability | Status | Evidence and boundary |
| --- | --- | --- |
| `company-analytics.v1` | Implemented public product profile | Twenty-six stages compose the embedded research dossier with fundamentals, models, consensus, positioning, events, experiments, research-lab records, and Research Quality. Every stage includes a versioned role, objective, completion criteria, dependencies, capabilities, and output refs; exact prompt wording remains caller-owned. |
| `CompanyAnalyticsSubmissionV1` | Implemented outer submission | Strict embedded research submission plus typed analytics, run card, hypothesis ledger, iterations, quality receipt, and forecasts. |
| `company-research.v1` | Implemented embedded foundation | Fifteen ordered stages declare the Evidence-First Company Research portion of Company Analytics. It is not advertised as a second product profile. |
| `CompanyResearchSubmissionV1` / `ResearchDossierV1` | Implemented embedded contracts | Strict request plus completed dossier, both using schema version `company-research.v1`. |
| Self-contained analytics schema | Supported | Prepare returns bundled typed analytics definitions. Python contracts enforce cross-field semantics, including global forecast namespace rules. |
| Product discovery | Supported | Discovery advertises `company-analytics.v1` as the public product profile. |
| Instrument identity | Supported | Typed equity, fund, or crypto identity with bounded ASCII market symbols; deterministic submissions cover ORCL, META, QQQ, and ACME. |
| Research-mode truthfulness | Supported | Requests require `live`, `fixture`, or `historical_replay`; result capability flags derive from that declaration, and fixture data is never presented as live. |
| Lossless request projection | Supported | `CompanyAnalyticsResultV1.submission.company_research.request` is authoritative for `research_mode` and other request semantics; `RunView.research_request` is its lossless projection, not a separate result artifact. |
| Exact-cutoff provenance | Supported validation; caller-owned retrieval | Source availability, filing dates, metric information vintages, transcript events, factors, historical events, and prior outcomes are checked against the request cutoff. Future estimate/model periods remain valid when their information vintage and inputs are cutoff-safe. |
| Adaptive history | Supported contract; caller-dependent execution | Plans declare history windows, expansion reasons, latest-data checks, and stop conditions. The caller chooses and retrieves the periods. |
| Evidence and entitlement | Supported | First-class documents retain locators, hashes, bounded extracts, temporal provenance, entitlement status, and redistribution boundaries. |
| Claims and counterclaims | Supported | Claims link to documents/metrics; counterclaims, counterevidence, stance, kind, and confidence remain explicit. |
| Calculations | Supported deterministic validation | Calculation lineage carries formulas, inputs, constants, results, units, absolute tolerance, and decimal rounding; semantic validation recomputes bounded arithmetic. |
| Filings and filing changes | Supported | Filing identity, accession, period, amendment, and prior/current change links are typed. Concrete filing retrieval remains caller-owned. |
| Transcripts and guidance | Supported with entitlement boundary | Transcript segments/themes and guidance records are typed. Non-redistributable transcript content cannot be embedded. |
| Peers and factors | Supported | Peer rationale/normalization and factor methodology/history links are validated. |
| Valuation | Supported deterministic contract | Cases, assumptions, input metrics, calculation links, and sensitivity cells are first-class. Recommendation quality remains caller-dependent. |
| Events, risks, and monitoring | Supported | Entity/event/ripple links, evidence-backed risks, and monitoring triggers/consequences are typed. |
| Research delta and prior outcomes | Supported | Current IDs link to a prior dossier digest and cutoff-safe outcomes. The caller supplies the prior research context. |
| Evaluation receipts | Supported | Checks retain evaluator provenance, rubric, status, timestamps, references, and limitations. This is not a claim of external evaluator certification. |
| Sanitized portfolio context | Optional and non-executable | Private account/customer identity and executable fields are rejected. |
| Completeness semantics | Supported | Complete coverage needs sources; every non-complete state needs a limitation. Entitlement gaps stay explicit. |
| Analytics adapter plan/import | Supported | CLI names `analytics-plan`/`analytics-import` and MCP/Python operations `prepare_company_analytics`/`import_company_analytics` invoke the same application boundary and atomically publish one complete analytics bundle. |
| `run-control.v1` durable lifecycle | Supported | `analytics-init`/`create_company_analytics_run` creates the 26-stage run; commits advance one first-incomplete stage at a time, with checkpoints, resume, cancellation, strict analytics finalization, durable report-ID rebinding, hidden quality-index publication, and crash recovery. |
| Execution modes | Sequential coordinator/runner requires caller executor; native/import adapter-dependent | The `sequential` runner reports `executor_required` until the caller supplies a `LifecycleStageExecutor`; it does not supply reasoning or retrieval. `native` execution requires a caller adapter; `import` coordination is implemented, while complete live research still depends on caller-supplied adapters and evidence. |
| Caller parallelism | Mode-specific | A `native` caller may execute dependency-ready work in parallel. Durable runs preserve manifest-order commits even when retrieval or reasoning is concurrent. |
| Deterministic company analytics | Supported contracts and calculators | Ratio, DCF/reverse-DCF/comparables, consensus, positioning, catalyst, and experiment records preserve point-in-time inputs and reproducible receipts. Investment usefulness remains caller- and evidence-dependent. |
| Research packs and hypothesis ledger | Supported | Eight versioned pack definitions, immutable run cards, stage receipts, research iterations, and append-only hypotheses are available in the analytics sidecars. |
| Persistence capability truthfulness | Supported | Direct import reports checkpoint and decision memory disabled. Public durable runs use the default memory store; custom coordinators must configure memory, disable it explicitly, or fail rather than silently downgrade. |
| Decision memory | Supported | Published decisions are bounded to five same-symbol and three cross-symbol recalls; exact-cutoff filtering excludes later decisions, outcomes, and embedded availability. |
| Research Dossier Viewer | Supported | The completed projection renders published research sections and contains no research, lifecycle, provider, credential, or broker controls. Completed CLI/MCP adapters return a run-specific link and reuse one loopback daemon per durable state directory; headless mode returns a path-only receipt. |
| Research Quality | Implemented | Immutable receipt/forecast registration, append-only outcome corrections, deterministic scorecards, CLI/MCP operations, durable local storage, and completed-view projection are supported. No forecast-accuracy claim is implied. |
| Completed publication authority | Supported | `CompanyAnalyticsResultV1` retains the exact submission and seven authoritative artifacts. The five report groups, viewer, and outcome index are projections; the index is hidden until publish and reconstructable from completed artifacts without claiming a distributed transaction. |
| Source port/adapters | SourceBatch v1 implemented | Typed queries and SourceBatch v1 cover provenance, entitlement, completeness, pagination, limitations, and typed terminal status; test fixture, replay, router, public, licensed-host, and host-OAuth seams fail closed and reject credentials. |
| Separate MCP surfaces | Implemented | `stock-research-agents-mcp` coordinates Company Analytics and exposes no research-data tools. `stock-research-data-mcp` defaults to seven read-only public tools: SEC filings/fundamentals/statements, GDELT company/global news discovery, World Bank macro, and Polymarket Gamma `prediction_markets`. Prices/indicators require an entitled caller `SourcePort`; Reddit requires approved caller OAuth; StockTwits is denied/unregistered. See [Research-data MCP](RESEARCH_DATA_MCP.md). |
| Multi-source portfolio policy | Caller collector and typed receipt implemented; terminal publication still planned | Full-company runs attempt regulator, issuer, market/fundamental, independent reporting, industry/peer, macro/policy, expectations/positioning, and adversarial lanes. The caller collector attempts every explicit provider route, preserves separate provider entitlements, and receipts failures and exact dedup decisions. The viewer audits supplied breadth and gaps but never fetches or invents sources. Publishing the full receipt as a terminal artifact remains an additive contract extension. See [Source portfolio](SOURCE_PORTFOLIO.md). |
| `import` live end to end | Partial | Import callers can use the seven public tools plus coordination/import/read operations, but complete live company research remains unavailable because licensed market-data and lawful social/provider coverage are not provided by default. Prediction-market metadata does not close either gap. |
| Deterministic test proof | Supported | Test submissions span ORCL, META, QQQ, and ACME; this proves generic contract handling, not live research quality. The deterministic ORCL fixture is test-only. |
| Live provider/data retrieval | Caller-owned and unverified | No local test proves live source availability, provider credentials, freshness, or arbitrary-symbol coverage. |
| Licensed-data behavior | Caller-owned and unverified | Contracts enforce declared entitlements and redistribution rules; no licensed feed has been validated. |
| Runtime execution mechanics | Harness-specific | StockResearchAgents owns stage meaning and observable contracts; agent scheduling, browser sessions, provider clients, and token-level interruption remain caller/runtime-specific. |
| Feature/information consistency | Implemented contract target; live proof incomplete | Every runtime can consume the same declared stages and terminal contracts. With a caller-supplied executor, the sequential runner completes and resumes the 26-stage lifecycle; external live/failure evidence remains required for provider claims. |
| Stage-boundary resume | Supported | Interrupted in-flight work is replayed from the first incomplete stage; token-level continuation is not promised. |
| Push event delivery | Runtime-specific | Monotonic cursor polling is the harness-neutral baseline. |
| Broker/order execution | Prohibited | No tool, endpoint, contract, or UI control can place or manage an order. |

## What deterministic demonstrations prove

A completed deterministic submission proves schema parsing, point-in-time and referential checks, deterministic recomputation, content-addressed publication, multi-company identity isolation, and completed UI projection. It does not prove that a caller retrieved correct live data, possessed a license, followed a provider's terms, or produced an investment-quality recommendation.

## Remaining boundaries

1. Validate a real caller integration against live public sources without moving credentials into the StockResearchAgents boundary.
2. Add and validate receipt-backed licensed market-data and lawful social providers without widening the credential-free core boundary.
3. Record the representative live/failure symbol matrix as reproducible, hash-bound release evidence; local Python/CLI/MCP/export/UI semantic equivalence is already implemented.
4. Preserve the final-only browser boundary, non-execution invariant, and typed-observable validation scope throughout provider integrations.
