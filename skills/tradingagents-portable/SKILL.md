---
name: tradingagents-portable
description: Research any supported financial instrument through the durable credential-free lifecycle, publish safe receipts and stage checkpoints, finalize the result, and inspect it as a read-only dossier. The atomic import and optional legacy adapter remain available for backward compatibility.
---

# TradingAgents Portable

Use this plugin's durable host-native lifecycle by default. The current Codex task supplies reasoning, subagents, concrete research tools, and hard interruption; TradingAgents Portable supplies topology, stage-boundary persistence, safe receipts, typed validation, decision/report persistence, export, and the final UI. The server must not request or accept an API key. The browser UI and inline view are finalized-result readers, not workflow executors.

## Internal Codex task run (preferred)

1. Call `create_host_run` with the symbol, cutoff date, analyst set, round counts, output language, and decision-memory preference; use returned memory context when enabled. Then call `start_host_run` with the latest `revision`.
2. Follow the returned stage instructions, context projection, allowed capability IDs, source priority, point-in-time cutoff, evidence windows, research-intelligence conventions, and no-key fallback behavior.
3. Execute that stage with this Codex task's own reasoning, subagents, and available research tools. Write in `request.output_language`. Do not create an external LLM client and do not ask for provider credentials.
4. Emit only safe `append_run_receipts`: stable IDs, kind, stage/attempt, capability ID, safe summary, timing, SHA-256 digests, and evidence IDs. For truthful execution observation, emit `stage_started`, then `stage_completed` for the same stage/attempt with the SHA-256 digest of the exact stage output that will be committed. Never include raw prompts, raw tool arguments/results, transcripts, API keys, tokens, cookies, authorization values, or other credentials.
5. Call `commit_host_stage` with the complete typed stage output and latest revision. Repeat the returned next stage until none remains. Preserve source URLs, source dates, retrieval times, limitations, and evidence IDs. Put optional detailed intelligence inside `EvidenceItem.values`: explicit `source_quality`; structured `metrics`; and structured `articles`, `catalysts`, `risks`, `conflicts`, `unknowns`, and `monitoring_conditions`. Preserve existing scalar values beside these structures so older consumers remain useful.
6. Preserve the three distinct decisions: Research Manager uses five-tier `recommendation`; Trader uses Buy/Hold/Sell `action` plus analytical reasoning and optional entry/stop/sizing; Portfolio Manager uses five-tier `rating` plus summary, thesis, optional target, and horizon. None carries execution authority.
7. Use `pause_host_run`/`resume_host_run` when needed. Resume restarts the first incomplete stage; interrupted in-flight work is replayed. Poll `poll_run_events` after its monotonic cursor for portable live progress. Push delivery and token-level continuation are harness-specific.
8. For cancellation, call `request_run_cancellation`, actually stop host-owned work, then call `acknowledge_run_cancellation` with a safe host receipt ID. The portable server does not hard-stop agents or tools.
9. Call `finalize_host_run` only after every stage is committed. Finalization validates the frozen `host-submission.v2` dossier, recoverably stages cross-store writes, atomically publishes the canonical result/event bundle, and exposes decision memory only after lifecycle completion. If control or polling returns `finalizing` with `publication_pending=true`, retry with the latest revision after the boundary failure; completed-result and dashboard surfaces remain hidden until publication succeeds. Only then may you call `get_run_view`, `export_completed_run`, or `launch_local_dashboard`.

If the user omits configuration, use the request date as the research cutoff; if omitted, use today's local date and record the latest completed market session separately. Default to all compatible analysts, one Bull/Bear round, and one Aggressive/Conservative/Neutral risk round. Never include information published after the cutoff.

Always resolve the newest cutoff-valid evidence before relying on an older record, then apply the manifest's adaptive-history policy. Ordinary stock research should normally include up to five years of daily market history, five fiscal years, eight comparable quarters, latest trailing-twelve-month figures, an intensive 90-day news review, and at least a 12-month material-event chronology. Extend toward ten years, listing inception, or the date of a still-relevant acquisition, financing, leadership, regulatory, or business-model change when that history is necessary to explain the current company or span a meaningful cycle. Check amendments, restatements, corrections, follow-up reporting, and superseding guidance. Stop only when no newer source exists by the cutoff, the current business model and a meaningful comparison cycle are covered, and older evidence no longer changes a trend, assumption, catalyst, risk, conflict, unknown, valuation range, or rating-change condition. Do not pad the report with repetitive history.

For news research, use the host's own web and research tools to widen coverage without adding API keys at the portable boundary. Start with official investor-relations and regulatory sources, use broad search or aggregators only to discover candidates, then open the underlying primary source or attributable reputable reporting before retaining a claim. Deduplicate repeated coverage by canonical URL and materially identical event, preserve publication time and canonical link, and label claim type, verification status, source quality, stance, and why the item matters. A search snippet, aggregator headline, or publisher name alone is not evidence and must not be assigned an inferred quality score.

For fundamentals, prefer filings and official results and retain several comparable periods when available. Preserve units, fiscal period, reporting basis, and whether each figure is company-reported, calculated, estimated, or an analytical assumption. Reconcile capex to free cash flow and surface segment trends, concentration, dilution, commitments, valuation dependencies, conflicting figures, and missing decision-critical facts. Never guess an unavailable metric.

The final synthesis must be differentiated without pretending to have exclusive data: separate consensus facts from variant interpretation; make assumptions and counter-evidence visible; connect catalysts and risks to evidence and horizons; preserve conflicts and unknowns; and state concrete upgrade, downgrade, stop, or thesis-invalidation conditions. The completed dossier renders this as an evidence-integrity chain and decision ledgers.

The mutable `run-lifecycle.v1` control protocol is separate from frozen terminal `host-submission.v2`. Cursor events are portable observations of sanitized host receipts and committed lifecycle transitions, not raw token streaming. The final UI exposes neither lifecycle controls nor receipt submission.

Harnesses without native subagents use the packaged sequential fallback and the same stage/output schema. The portable layer supplies private SQLite/WAL lifecycle checkpoints, atomic canonical result/event bundles, bounded publication-gated memory recall, later outcome/reflection append, atomic first export, and crash-recoverable verified overwrite. Agent spawning, concrete tools, hard interruption, exact model text, token continuation, and optional push delivery remain host-specific.

## Backward-compatible atomic import

If the caller already has one complete `host-submission.v2` payload, `prepare_host_run` plus `import_host_run` remains supported. It validates and atomically publishes the completed dossier but provides no partial checkpoints or cursor receipts. Prefer the durable lifecycle for new Codex tasks.

## Credential-free proof

1. Call `discover_capability` and `get_feature_matrix` when runtime readiness matters; the default server exposes 27 credential-free tools.
2. Call `prepare_fixture` to inspect the exact expanded topology.
3. Call `run_fixture` for a credential-free, deterministic ORCL run dated `2026-07-03`.
4. Inspect the response directly or retrieve the complete merged dossier with `get_run_view`; use `get_run_events`, `get_run_result`, and `get_dashboard_report` for narrower completed-run projections.
5. Call `launch_local_dashboard` only after finalization or fixture completion and only when a browser-oriented view is useful. It binds to loopback and exposes no execution controls.

The fixture covers all configured analysts, exactly `2 × debate_rounds` Bull/Bear turns, Research Manager, Trader, exactly `3 × risk_rounds` Aggressive/Conservative/Neutral turns, and Portfolio Manager.

## Standalone legacy compatibility (outside this plugin)

The credential-free Codex plugin does not register `run_legacy` and does not import the legacy adapter. For explicit backward compatibility outside Codex, the standalone `research` CLI and opt-in `tradingagents-portable-legacy-mcp` executable can delegate Yahoo-style symbols such as `AAPL`, `0700.HK`, `^GSPC`, `EURUSD=X`, `GC=F`, and `BTC-USD` to `TradingAgentsGraph`. Those surfaces are not the current-task execution path and may require environment-owned provider credentials.

- Provider credentials are environment-only. Never put an API key, token, password, cookie, authorization value, or other credential in a tool argument, run request, event, result, report, or dashboard field.
- `openai_codex` is accepted when the configured upstream checkout contains PR #1195. Let upstream read its Codex auth file directly (optionally via `TRADINGAGENTS_CODEX_AUTH_PATH`); never copy OAuth contents into a tool argument or result. Treat this unmerged, undocumented provider as runtime-unverified.
- Use only the typed `run_legacy` settings for `asset_type`, provider/model names, backend URL, output language, temperature, retry count, and provider reasoning effort. Arbitrary configuration objects are intentionally not exposed.
- Omitted debate/risk settings and `checkpoint_enabled` honor the upstream environment overlay; the upstream checkpoint default is false. Enable checkpointing only for an intentional runtime test because creation and resume have not been verified here. Ordinary upstream decision/report persistence does not imply checkpointing.
- Expect upstream's normal data-provider, report, and decision-log side effects during an explicit legacy run.
- If standalone setup is incomplete, return typed setup guidance instead of guessing configuration.

After standalone legacy execution completes, use its normalized output or explicit compatibility-server projections for the merged dossier. Its events are post-run projections, not a live stream.

## Capability truthfulness

- `fixture` is implemented and verified locally.
- Arbitrary-symbol CLI/MCP delegation and completed-state mapping are covered by fake-graph tests. A credentialed live provider run has not been verified.
- The optional standalone `legacy` events are reconstructed after completion. Importability does not verify provider credentials, data access, checkpoint behavior, or successful live execution.
- Live legacy stage streaming is unavailable until upstream provides an observer seam.
- Durable host-native lifecycle is locally verified: private SQLite/WAL checkpointing, linked safe cursor receipts, stage-boundary resume, cooperative request/ack cancellation, publication-gated bounded memory, canonical atomic result/event bundles, and crash-recoverable export replacement.
- The host owns reasoning, agent spawning, concrete tool calls, authentication, and hard interruption. An interrupted stage is replayed; exact model text and token-level continuation are not portable invariants.
- Legacy upstream checkpoint/resume and live provider execution remain runtime-unverified; importability and pinned credential-free conformance do not prove them.

## Safety boundary

Every output is prototype research, not personalized financial advice. The capability has no broker connection and must never place, simulate, approve, size, submit, modify, or cancel an order. Treat fixture values as synthetic integration-test data, never as facts about Oracle or current markets.
