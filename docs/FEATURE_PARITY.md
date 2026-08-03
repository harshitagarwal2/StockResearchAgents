# TradingAgents feature parity ledger

This ledger compares the portable capability with the current sibling `TradingAgents` checkout. “Feature parity” means the same user-visible research stages, information, ratings, and report groups. It does not mean identical LangGraph internals, model outputs, terminal pixels, or storage implementations.

The safety boundary is external side effects, not financial vocabulary. Research Manager and Portfolio Manager retain five-tier ratings; Trader retains Buy/Hold/Sell plus analytical price and sizing fields. None of those records can authorize or submit an order.

| Capability | Portable status | Current behavior and gap |
| --- | --- | --- |
| Arbitrary stock/crypto symbols | Supported | `host-plan` and host import are symbol-neutral; crypto omits unsupported fundamentals by contract. |
| Selected analyst stages | Supported | Market, social, news, and fundamentals roles expand in canonical order. |
| Analyst evidence and provenance | Supported contract; host-dependent retrieval | Cutoff, source dates, URLs, limitations, and evidence references are validated. Concrete tools and authentication remain host-owned. |
| Analyst tool-call loop | Supported protocol; host-owned execution | The manifest constrains allowed capabilities and safe receipts. The host owns concrete tool calls, authentication, and reasoning. |
| Bull/Bear debate | Supported | Ordered turns and configured round counts are validated. |
| Research Manager decision | Supported | Five-tier recommendation, rationale, strategic actions, confidence, and raw Markdown survive the portable result. |
| Trader proposal | Supported | Buy/Hold/Sell, reasoning, optional entry, stop, sizing, raw Markdown, and non-execution receipts are preserved. |
| Three-way risk debate | Supported | Aggressive, conservative, and neutral turns plus final constraints and unresolved risks are validated. |
| Portfolio Manager decision | Supported | Five-tier rating, executive summary, thesis, optional target/horizon, and raw Markdown are preserved. |
| Processed signal | Supported | Deterministically derived from the Portfolio rating only; it never overwrites Trader output. |
| Final report groups | Supported | Analysts, research, Trader, risk, Portfolio, structured result, and consolidated Markdown artifacts are produced. |
| Read-only final UI | Supported | The post-run dossier merges all completed results and exposes no setup, orchestration, or broker controls. |
| Codex plugin and skill | Supported | Codex can plan, execute with its internal task agents/tools, import, and display the completed dossier without model API keys at the portable boundary. |
| MCP tools-only use | Supported | The default credential-free server exposes 27 discovery, lifecycle, memory, export, conformance, result, and final-view tools. |
| Generic single-agent fallback | Supported | A reference sequential executor runs the same stage contract without subagents or LangGraph. |
| Exact upstream prompts/model text | Harness-specific | Legacy delegates to upstream. Host-native preserves observable schemas and topology while the host owns prompts, models, reasoning, and exact generated text. |
| Live stage observation | Supported portable cursor | Hosts append sanitized stage/tool receipts and consumers poll after a monotonic cursor. `execution_observed` requires linked start/completion receipts and a matching output digest. Push delivery is an optional harness enhancement; legacy events remain post-run projections. |
| Durable host-native run storage | Supported | Private SQLite/WAL lifecycle records plus canonical atomic result/event bundles and recovery intents survive process restarts. |
| Checkpoint interruption/resume | Supported at stage boundaries | Resume selects the first incomplete stage and replays interrupted in-flight work. Exact token continuation remains harness-specific. |
| Decision memory | Supported | SQLite memory recalls at most five same-symbol and three cross-symbol published decisions; pending finalization entries remain hidden, and later outcomes/reflections append without rewriting the original decision. |
| Filesystem report/log tree | Supported | First publication atomically writes the report paths, complete report, result/events, optional safe lifecycle JSONL, and manifest; verified overwrite is journaled and crash-recoverable. |
| Cancellation | Supported cooperatively | Portable cancellation is request plus host acknowledgement. The host owns hard interruption of agents/tools. |
| Interactive portable CLI | Supported | Interactive setup, stage commits, receipts, status, resume, cancellation, memory, export, conformance, and final dashboard publication are available without reproducing terminal pixels. |
| Pinned observable conformance | Supported local invariant check | Credential-free checks cover portable workflow/order/schema/signal/evidence/report/receipt invariants. Supplying an upstream checkout separately verifies its Git revision; it does not prove identical upstream model behavior. |
| Token and wall-time accounting | Host-specific | Receipts may carry bounded duration/digests, but exact token accounting and token-level continuation are not portable requirements. |
| Broker/order execution | Prohibited | No tool, endpoint, UI control, or contract can submit, modify, cancel, approve, or fill an order. This is a safety invariant, not a parity gap. |

## What the cross-company demonstrations prove

A completed ORCL, MSFT, JPM, or 0700.HK host-native dossier proves that the active host can populate and import the portable contract for that company. It does not prove identical recommendations to an upstream provider-backed run. Behavioral equivalence requires running both modes against equivalent models, prompts, data, cutoff, and configuration, then comparing the structured outputs.

## Remaining honest boundaries

1. Verify a credentialed upstream run and its upstream-owned crash/resume path in an isolated compatibility process.
2. Add optional push delivery where a harness supports it; cursor polling remains the portable baseline.
3. Compare generated content only when equivalent models, prompts, data, cutoff, and configuration are available; exact model text is not a portable invariant.
4. Preserve the completed-result-only browser boundary: lifecycle control belongs to CLI/MCP, not the dossier UI.
