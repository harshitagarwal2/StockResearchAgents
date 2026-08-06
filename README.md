# StockResearchAgents

<!-- mcp-name: io.github.harshitagarwal2/stock-research-agents -->

Evidence-first company research for agent harnesses, with versioned contracts, deterministic analytics, durable lifecycle controls, and completed-only dossiers.

> **Prototype research only. Not financial advice.** StockResearchAgents has no broker integration and cannot submit, modify, approve, cancel, or fill an order.

## Harness-neutral research capability

StockResearchAgents is an independent capability bundle for MCP-capable agent harnesses and custom applications. The **caller runtime** retrieves evidence, runs models, invokes tools, and schedules agents. The StockResearchAgents core supplies the harness-neutral workflow contracts, deterministic validation and analytics, durable `run-control.v1` lifecycle, atomic publication, typed exports, and completed-only presentation. It does not prescribe a model provider, prompt runtime, or agent scheduler. Codex is an optional thin adapter, not a platform dependency.

[![StockResearchAgents system overview: the public Company Analytics profile wraps an embedded research dossier and publishes only completed results](assets/architecture/system-overview.png)](assets/architecture/system-overview.png)

[Open the full-resolution system overview.](assets/architecture/system-overview.png)

The public product profile is `company-analytics.v1`. Its outer `CompanyAnalyticsSubmissionV1` adds deterministic fundamentals, valuation, consensus, positioning, catalysts, experiments, falsifiable hypotheses, forecasts, and outcome scoring around an embedded `CompanyResearchSubmissionV1` / `ResearchDossierV1` foundation. The StockResearchAgents core validates the exact outer submission and publishes one strict `CompanyAnalyticsResultV1` containing that submission plus seven authoritative artifacts: dossier, analytics bundle, run card, hypothesis ledger, research iterations, quality receipt, and forecast set. The read-only **Research Dossier Viewer** is a projection of that completed result.

The boundary is deliberate:

- **The caller owns** retrieval, reasoning, credentials, entitlements, tool invocation, exact prompt wording, and agent scheduling. Plans encode this boundary in `system_boundary.caller_owns`, while `execution_contract.global_policy.caller_ownership` states the runtime rule.
- **The StockResearchAgents core owns** versioned stage roles/objectives/completion-criteria declarations, contracts, deterministic validation, `run-control.v1` stage boundaries and recovery, terminal validation, publication, exports, and completed read models. Plans enumerate these responsibilities in `system_boundary.core_owns`. A caller attests intermediate criterion satisfaction; opaque nonterminal content remains caller-owned and is not independently verified by the core.
- **The viewer owns no research logic.** It remains empty until a completed result is published.

## Install a released version

When a tagged version has been published to PyPI, install the CLI in an isolated tool environment:

```bash
uv tool install "stock-research-agents==<VERSION>"
stock-research-agents --help
```

`pipx install "stock-research-agents==<VERSION>"` is equivalent. Applications can use `python -m pip install "stock-research-agents==<VERSION>"`, and an MCP host can launch the same package with:

```bash
uvx --from "stock-research-agents==<VERSION>" stock-research-agents-mcp
```

Use a full release tag for direct Git installs, never a moving branch. The release and host-adapter guide documents source, Python, MCP, TestPyPI, and GitHub Release paths: [Harnesses](docs/HOSTS.md) and [Releasing](docs/RELEASING.md).

## Five-minute deterministic test proof

Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync
uv run stock-research-agents fixture --events
```

This command exercises the deterministic ORCL fixture used by tests and local verification. The fixture is not a public research profile and never represents live research. It proves contract validation and the completed-result path; open the returned `presentation.url` only to inspect that test result in the shared loopback viewer.

For normal research, start from a host integration. Codex can use the packaged skill and MCP servers; other harnesses can use MCP, Python, or their own adapter over the same contracts. See [Harness integration](docs/INTEGRATION.md).

## Choose your path

| Goal | Start here |
| --- | --- |
| Connect any MCP-capable harness | [Harnesses](docs/HOSTS.md) and [integration](docs/INTEGRATION.md#mcp) |
| Use Claude Code, OpenCode, or Hermes | [Host adapters](docs/INTEGRATION.md#host-adapters) |
| Use the optional Codex plugin | [Harness integration](docs/INTEGRATION.md#optional-codex-adapter) |
| Embed the StockResearchAgents API in an application | [Harness integration](docs/INTEGRATION.md#python) |
| Run the deterministic test proof | [Getting started](docs/GETTING_STARTED.md) |
| Build a durable host adapter | [Contract guide](docs/CONTRACTS.md) and [Architecture](docs/ARCHITECTURE.md) |
| Improve source breadth and independence | [Source portfolio](docs/SOURCE_PORTFOLIO.md) |
| Understand SOLID and ports/adapters boundaries | [Ports and adapters](docs/PORTS_AND_ADAPTERS.md) |
| Operate, export, or troubleshoot runs | [Operations](docs/OPERATIONS.md) |
| Understand product and UI decisions | [Design](DESIGN.md) |
| Review forecast accountability | [Research Quality](docs/RESEARCH_QUALITY.md) |
| Publish or verify a release | [Releasing](docs/RELEASING.md) |
| Contribute safely | [Contributing](CONTRIBUTING.md) |

The complete documentation map is in [docs/README.md](docs/README.md).

## What exists today

The implemented **Company Analytics** capability provides:

- an exact, timezone-aware research cutoff;
- first-class source, entitlement, timestamp, claim, calculation, peer, valuation, risk, monitoring, and coverage records;
- a 26-stage caller-executed workflow whose `sequential` coordinator/runner reports `executor_required` until the caller supplies a `LifecycleStageExecutor`, plus a caller-adapter-dependent `native` mode, an implemented but live-coverage-dependent `import` mode, and a mandatory sequential fallback;
- deterministic fundamentals, ratios, valuation cases, consensus, positioning, catalysts, point-in-time experiment receipts, hypotheses, forecasts, and reproducible outcome scorecards;
- strict temporal, referential, numerical, structured-challenge, sanitized-context, licensing, and safety validation of the complete outer submission;
- SQLite/WAL lifecycle checkpoints with optimistic revisions, pause/resume, cooperative cancellation, and recovery;
- content-addressed `CompanyAnalyticsResultV1` publication with an exact `CompanyAnalyticsSubmissionV1` and seven authoritative artifacts;
- five deterministic report groups—Executive Summary, Evidence and Claims, Analytics and Valuation, Risks and Counterevidence, and Monitoring and Quality—plus JSON/Markdown exports, harness-neutral MCP reads, and an automatically discovered, shared loopback-only Research Dossier Viewer with exact source identity/access states, deduplicated planned-versus-held coverage, publisher/host concentration, entitlement gaps, and claim-lineage analysis.

The product exposes two separate MCP servers. The coordination MCP (`stock-research-agents-mcp`) owns Company Analytics planning, `run-control.v1`, validation, publication, and completed-result reads; it registers no research-data tools. The research-data MCP (`stock-research-data-mcp`) implements `SourceBatch.v1` and registers seven public tools by default: SEC filings/fundamentals/statements, GDELT company/global news discovery metadata plus publisher links, World Bank macro observations, and credential-free `prediction_markets` search through Polymarket Gamma. The Gamma adapter returns public, read-only market metadata; it does not expose wallet, CLOB, or order endpoints. Treat its probabilities only as current market-implied observations when they are decision-relevant—not as truth, forecasts, or executable signals—and do not use current search results to reconstruct a historical snapshot. Prices and indicators require an entitled caller `SourcePort`; Yahoo Finance/`yfinance` remains caller-owned and terms-permitting rather than a default. Reddit requires approved caller OAuth, StockTwits is denied/unregistered, and FRED and Alpha Vantage are not default providers. The World Bank API supplies current-vintage values and cannot reconstruct historical revision lineage. GDELT results are discovery records—not opened publisher evidence—and saturated result sets are reported as partial.

StockResearchAgents therefore has partial live public-source coverage, not complete live company research. The prediction-market adapter does not close the licensed market-data or lawful social-provider gaps. Live correctness still depends on source availability, caller entitlements, model behavior, and exact-cutoff discipline.
The public `run_sequential_company_lifecycle` fallback reports `executor_required` until a caller supplies the `LifecycleStageExecutor` that performs each stage. It drives the same 26 durable stage contracts and resumes at the first incomplete stage. `native` execution remains caller-adapter work, and `import` remains partial for live research because provider coverage is incomplete. Native multi-agent runtimes may schedule the same contracts differently without changing their observable meaning.

## Company research from a caller runtime

Plan the public analytics flow from a schema-valid company request:

The example below uses the CLI as a thin local adapter. Codex, MCP, Python, and custom harness adapters consume the same plan and terminal contract without inheriting CLI orchestration.

```bash
uv run stock-research-agents analytics-plan \
  --input examples/company-request.v1.json \
  --output plan.json
```

A caller executes the returned versioned roles, objectives, completion criteria, dependencies, capabilities, and output contracts with its own agents and tools. It may then import a complete, schema-valid terminal submission:

```bash
uv run stock-research-agents analytics-import \
  --input submission.analytics.json \
  --output result.json
```

For a durable 26-stage run, use `analytics-init`, then the shared caller/runtime lifecycle controls. Opaque nonterminal envelopes are recorded as `committed`, not independently verified stage completions. Commits advance one first-incomplete stage at a time and resume restarts there. Finalization validates the exact 26-stage run card, publishes the canonical content-derived `CompanyAnalyticsResultV1.run_id`, and records that ID in the separate lifecycle control as `result_run_id`; the lifecycle `run_id` remains the control handle. The recoverable quality outcome index is reconstructed from the result's seven authoritative artifacts when necessary. `analytics-import` remains the stateless seam for an already-complete analytics payload. See [Integration](docs/INTEGRATION.md).

## Stable product language

| Human-facing name | Meaning | Stable technical identifier |
| --- | --- | --- |
| Company Analytics | Primary research capability | `company-analytics.v1` |
| Completed Research Dossier | Immutable human-facing artifact | `research_dossier.v1` |
| Research Dossier Viewer | Completed-only read projection | `run-view.v1` |
| Evidence-First Company Research | Embedded dossier foundation | `company-research.v1` |
| Research Quality | Forecast, outcome, and evaluation capability | `research_quality.v1` sidecar in `company-analytics.v1` |
| Research Quality Receipt | Immutable policy, provenance, forecast, and rule-evaluation artifact | `research-quality.v1` |

Wire identifiers remain versioned and are never renamed cosmetically. See [Glossary](docs/GLOSSARY.md) and [active contract set](docs/COMPATIBILITY.md).

## Versioned contracts

| Surface | Status | Purpose |
| --- | --- | --- |
| `company-analytics.v1` | One public product profile | Twenty-six-stage dossier, analytics, research-lab, and quality workflow |
| `CompanyAnalyticsSubmissionV1` | Outer terminal submission | Embedded research submission plus typed analytics and quality sidecars |
| `company-research.v1` | Embedded foundation | Fifteen-stage Evidence-First Company Research workflow inside Company Analytics |
| `CompanyResearchSubmissionV1` / `ResearchDossierV1` | Embedded terminal foundation | Strict request plus completed dossier |
| `run-control.v1` | Public lifecycle contract | Ordered commits, optimistic revisions, pause/resume, cancellation, recovery, and finalization |

The analytics profile wraps rather than widens research. Existing research readers remain valid while analytics-aware readers consume typed sidecars.

## Current proof boundary

Local tests prove deterministic contracts, lifecycle behavior, safety, and generic symbol handling for fixture submissions. They do not prove:

- that every future host retrieves complete or correct live evidence;
- access to licensed providers or redistribution rights;
- recommendation quality, investment performance, or forecast calibration;
- token-level resume inside a model response or tool call; or
- broker or order execution, which is prohibited.

See [Capability and proof status](docs/FEATURE_PARITY.md) and [Validation](docs/VALIDATION.md) for the evidence ledger.
