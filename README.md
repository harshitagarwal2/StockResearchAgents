# StockResearchAgents

Evidence-first company research that preserves what was known, why a conclusion was reached, and how the completed work can be audited.

> **Prototype research only. Not financial advice.** StockResearchAgents has no broker integration and cannot submit, modify, approve, cancel, or fill an order.

## Relationship to TradingAgents

StockResearchAgents is an independent, harness-neutral approach inspired by the specialized research roles, adversarial discussion, and risk-review ideas introduced by [TradingAgents](https://github.com/TauricResearch/TradingAgents). The foundational reference is [*TradingAgents: Multi-Agents LLM Financial Trading Framework* (Xiao, Sun, Luo, and Wang, arXiv:2412.20138)](https://arxiv.org/abs/2412.20138).

It is **not a fork or replacement** for TradingAgents. TradingAgents is a LangGraph-based multi-agent trading framework; StockResearchAgents keeps the research workflow portable across Codex, other agent harnesses, and custom applications. The host chooses its models, prompts, tools, credentials, and agent-scheduling mechanics. This repository supplies the versioned research contracts, deterministic validation and analytics, durable lifecycle, and completed-only presentation. An optional pinned upstream adapter exists only for compatibility and conformance—not as the portable core.

[![StockResearchAgents system overview: host-owned research flows through the evidence-first portable core into a completed research dossier and read-only viewer](assets/architecture/system-overview.png)](assets/architecture/system-overview.png)

[Open the full-resolution system overview.](assets/architecture/system-overview.png)

StockResearchAgents is a harness-neutral capability bundle. A **research host**—Codex, another agent harness, or a custom application—retrieves evidence and runs models. The primary `company-analytics.v1` profile adds deterministic fundamentals, valuation, consensus, positioning, catalysts, experiments, falsifiable hypotheses, forecasts, and outcome scoring to the evidence-first dossier. The portable core validates exact-cutoff contracts, atomically publishes the completed bundle, and serves a read-only **Research Dossier Viewer**.

The boundary is deliberate:

- **The host owns** retrieval, reasoning, credentials, entitlements, tool invocation, exact prompt wording, and agent scheduling.
- **Portable owns** versioned stage roles/objectives/completion-criteria declarations, contracts, deterministic conformance, stage boundaries, recovery, terminal validation, publication, exports, and completed read models. A host attests intermediate criterion satisfaction; opaque nonterminal content remains host-owned and is not called verified by Portable.
- **The viewer owns no research logic.** It remains empty until a completed result is published.

## Five-minute safe demo

Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) are recommended.

```bash
uv sync
uv run stock-research-agents fixture --events
```

Open the returned `presentation.url`. Completed CLI and MCP operations automatically ensure one shared loopback viewer
and return a URL pinned to that exact run; later companies reuse the same application. The ORCL data is deterministic
fixture material and is visibly labeled as such; it does not claim to be current market research. The foreground
`report` command remains available for diagnostics or an explicitly selected port.

To inspect the CLI, coordination MCP, and isolated public research-data MCP:

```bash
uv run stock-research-agents --help
uv run stock-research-agents-mcp
uv run stock-research-data-mcp
```

`dashboard` remains a compatibility alias for the preferred `report` command. The original
`tradingagents-portable*` command names remain additive compatibility aliases for saved scripts and integrations.

## Choose your path

| Goal | Start here |
| --- | --- |
| See the product safely | [Getting started](docs/GETTING_STARTED.md) |
| Use the Codex plugin | [Harness integration](docs/INTEGRATION.md#codex-plugin) |
| Connect any MCP-capable harness | [Harness integration](docs/INTEGRATION.md#mcp) |
| Build a durable host adapter | [Contract guide](docs/CONTRACTS.md) and [Architecture](docs/ARCHITECTURE.md) |
| Improve source breadth and independence | [Source portfolio](docs/SOURCE_PORTFOLIO.md) |
| Understand SOLID and ports/adapters boundaries | [Ports and adapters](docs/PORTS_AND_ADAPTERS.md) |
| Operate, export, or troubleshoot runs | [Operations](docs/OPERATIONS.md) |
| Understand product and UI decisions | [Design](DESIGN.md) |
| Review forecast accountability | [Research Quality](docs/RESEARCH_QUALITY.md) |
| Contribute safely | [Contributing](CONTRIBUTING.md) |

The complete documentation map is in [docs/README.md](docs/README.md).

## What exists today

The implemented **Company Analytics** capability provides:

- an exact, timezone-aware research cutoff;
- first-class source, entitlement, timestamp, claim, calculation, peer, valuation, risk, monitoring, and coverage records;
- a 26-stage host-executed workflow with a locally ready compatible sequential runner, a full native-agent adapter contract, a partial coordination/import tools-only mode, and a mandatory sequential fallback;
- deterministic fundamentals, ratios, valuation cases, consensus, positioning, catalysts, point-in-time experiment receipts, hypotheses, forecasts, and reproducible outcome scorecards;
- strict temporal, referential, numerical, debate, portfolio, licensing, and safety validation;
- SQLite/WAL lifecycle checkpoints with optimistic revisions, pause/resume, cooperative cancellation, and recovery;
- content-addressed completed results and atomic publication;
- JSON/Markdown exports, MCP reads, and an automatically discovered, shared loopback-only Research Dossier Viewer with exact source identity/access states, deduplicated planned-versus-held coverage, publisher/host concentration, entitlement gaps, and claim-lineage analysis; and
- a preserved TradingAgents compatibility workflow and optional upstream adapter.

The separate `tradingagents-research-data` compatibility server key implements SourceBatch v1 and registers six public tools by default: SEC filings/fundamentals/statements, GDELT company/global news discovery metadata plus publisher links, and World Bank macro observations. The coordination MCP remains isolated from data retrieval. Prices and indicators require an entitled host `SourcePort`, Reddit requires host OAuth, and StockTwits is denied/unregistered. The World Bank API supplies current-vintage values and cannot reconstruct historical revision lineage. GDELT results are discovery records—not opened publisher evidence—and saturated result sets are reported as partial.

Portable therefore has partial live public-source coverage, not complete live company research. Live correctness still depends on source availability, host entitlements, model behavior, exact-cutoff discipline, and the missing market-data/social provider coverage.
The public `run_sequential_company_lifecycle` fallback is the locally ready execution path: it drives the same 26 durable stage contracts through one host executor and resumes at the first incomplete stage. Full native-agent execution remains host-adapter work, and tools-only execution remains partial because live research provider coverage is incomplete. Native multi-agent harnesses may schedule the same contracts differently without changing their observable meaning.

## Company research from a host

Plan the primary analytics flow from a v3-compatible company request:

```bash
uv run stock-research-agents analytics-plan \
  --input examples/company-request.v3.json \
  --output plan.json
```

A host executes the returned versioned roles, objectives, completion criteria, dependencies, capabilities, and output contracts with its own agents and tools. It may then import a complete, schema-valid terminal submission:

```bash
uv run stock-research-agents analytics-import \
  --input submission.v4.json \
  --output result.json
```

For a durable 26-stage run, use `analytics-init`, then the shared host/run lifecycle controls. Opaque nonterminal envelopes are recorded as `committed`, not independently verified stage completions. Commits advance one first-incomplete stage at a time, resume restarts there, and finalization validates the exact canonical 26-stage run card and v4 bundle before atomically publishing authoritative `RunResult` sidecars. The recoverable quality outcome index is reconstructed from those completed artifacts when necessary. `analytics-import` remains the stateless seam for an already-complete v4 payload. See [Integration](docs/INTEGRATION.md).

## Stable product language

| Human-facing name | Meaning | Stable technical identifier |
| --- | --- | --- |
| Company Analytics | Primary research capability | `company-analytics.v1` |
| Completed Research Dossier | Immutable human-facing artifact | `research_dossier.v3` |
| Research Dossier Viewer | Completed-only read projection | compatibility APIs still use `dashboard` |
| TradingAgents Compatibility Workflow | Preserved upstream-shaped workflow | `financial-research.v1` |
| Evidence-First Company Research | Frozen dossier foundation | `company-research.v2` |
| Research Quality | Forecast, outcome, and evaluation capability | `research_quality.v1` sidecar in `company-analytics.v1` |
| Research Quality Receipt | Immutable policy, provenance, forecast, and rule-evaluation artifact | `research-quality.v1` |

Wire identifiers remain versioned and are never renamed cosmetically. See [Glossary](docs/GLOSSARY.md) and [Compatibility](docs/COMPATIBILITY.md).

## Versioned compatibility

| Surface | Status | Purpose |
| --- | --- | --- |
| `financial-research.v1` | Preserved | TradingAgents-compatible analyst/debate/trader/risk/portfolio workflow |
| `host-submission.v2` | Preserved and frozen | Terminal format for the compatibility path |
| `run-lifecycle.v1` | Preserved | Durable lifecycle protocol for the compatibility path |
| `company-research.v2` | Implemented parallel extension | Fifteen-stage Evidence-First Company Research workflow |
| `host-submission.v3` | Implemented and frozen | Strict request plus completed `research_dossier.v3` |
| `company-analytics.v1` | Primary implemented profile | Twenty-six-stage dossier, analytics, research-lab, and quality workflow |
| `host-submission.v4` | Implemented wrapper | Unchanged v3 submission plus typed analytics and quality sidecars |

The analytics profile wraps rather than widens v3. Existing v3 readers remain valid while v4-aware readers consume typed sidecars.

## Optional upstream TradingAgents compatibility adapter

The `research` CLI and historical `tradingagents-portable-legacy-mcp` executable delegate to an installed upstream `TradingAgentsGraph`. The legacy MCP name remains frozen by the transition inventory rather than gaining a second branded alias. Neither is registered by the default credential-free plugin server.

```bash
uv sync --extra upstream
uv run stock-research-agents research AAPL --date 2026-07-03
```

This path may require provider credentials owned by the upstream runtime. Importability and exact revision identity do not prove provider access, behavioral parity, checkpoint resume, or a successful live run.

The host-native core is the target architecture, but the legacy executor is currently available and **not yet deprecated**. Removal remains blocked until complete research-data category coverage (including licensed market data and lawful social sources), scoped upstream dual-run conformance, representative live/failure coverage, full surface equivalence, saved-result migrations, and one published deprecation release are verified. Frozen readers and historical results remain supported after any later-major executor removal. See [Legacy transition](docs/LEGACY_TRANSITION.md) and [Research-data MCP](docs/RESEARCH_DATA_MCP.md).

The architecture direction is being discussed upstream in [TradingAgents RFC #1198](https://github.com/TauricResearch/TradingAgents/issues/1198). This independent implementation lives at [harshitagarwal2/StockResearchAgents](https://github.com/harshitagarwal2/StockResearchAgents). Upstream remains intact and pinned as a conformance oracle; its LangGraph runtime and workflow business logic are not copied into the portable core.

## Current proof boundary

Local tests prove deterministic contracts, lifecycle behavior, safety, and generic symbol handling for fixture submissions. They do not prove:

- that every future host retrieves complete or correct live evidence;
- access to licensed providers or redistribution rights;
- recommendation quality, investment performance, or forecast calibration;
- token-level resume inside a model response or tool call; or
- broker or order execution, which is prohibited.

See [Feature parity](docs/FEATURE_PARITY.md) and [Validation](docs/VALIDATION.md) for the evidence ledger.
