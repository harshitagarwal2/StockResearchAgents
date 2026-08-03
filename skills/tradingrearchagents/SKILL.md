---
name: tradingrearchagents
description: Research any supported financial instrument through the durable credential-free lifecycle, publish safe receipts and stage checkpoints, finalize the result, and inspect it as a read-only dossier. The atomic import and optional legacy adapter remain available for backward compatibility.
---

# tradingrearchagents

Use this plugin's durable host-native lifecycle by default. The current Codex task supplies reasoning, subagents, concrete research tools, and hard interruption; tradingrearchagents supplies topology, stage-boundary persistence, safe receipts, typed validation, decision/report persistence, export, and the final UI. The server must not request or accept an API key. The browser UI and inline view are finalized-result readers, not workflow executors.

## Internal Codex task run (preferred)

1. Call `create_host_run` with the symbol, cutoff date, analyst set, round counts, output language, and decision-memory preference; use returned memory context when enabled. Then call `start_host_run` with the latest `revision`.
2. Follow the returned stage instructions, context projection, allowed capability IDs, source priority, point-in-time cutoff, evidence windows, and no-key fallback behavior.
3. Execute that stage with this Codex task's own reasoning, subagents, and available research tools. Write in `request.output_language`. Do not create an external LLM client and do not ask for provider credentials.
4. Emit only safe `append_run_receipts`: stable IDs, kind, stage/attempt, capability ID, safe summary, timing, SHA-256 digests, and evidence IDs. For truthful execution observation, emit `stage_started`, then `stage_completed` for the same stage/attempt with the SHA-256 digest of the exact stage output that will be committed. Never include raw prompts, raw tool arguments/results, transcripts, API keys, tokens, cookies, authorization values, or other credentials.
5. Call `commit_host_stage` with the complete typed stage output and latest revision. Repeat the returned next stage until none remains. Preserve source URLs, source dates, retrieval times, limitations, and evidence IDs.
6. Preserve the three distinct decisions: Research Manager uses five-tier `recommendation`; Trader uses Buy/Hold/Sell `action` plus analytical reasoning and optional entry/stop/sizing; Portfolio Manager uses five-tier `rating` plus summary, thesis, optional target, and horizon. None carries execution authority.
7. Use `pause_host_run`/`resume_host_run` when needed. Resume restarts the first incomplete stage; interrupted in-flight work is replayed. Poll `poll_run_events` after its monotonic cursor for portable live progress. Push delivery and token-level continuation are harness-specific.
8. For cancellation, call `request_run_cancellation`, actually stop host-owned work, then call `acknowledge_run_cancellation` with a safe host receipt ID. The portable server does not hard-stop agents or tools.
9. Call `finalize_host_run` only after every stage is committed. Finalization validates the frozen `host-submission.v2` dossier, recoverably stages cross-store writes, atomically publishes the canonical result/event bundle, and exposes decision memory only after lifecycle completion. If control or polling returns `finalizing` with `publication_pending=true`, retry with the latest revision after the boundary failure; completed-result and dashboard surfaces remain hidden until publication succeeds. Only then may you call `get_run_view`, `export_completed_run`, or `launch_local_dashboard`.

If the user omits configuration, use the request date as the research cutoff; if omitted, use today's local date and record the latest completed market session separately. Default to all compatible analysts, one Bull/Bear round, and one Aggressive/Conservative/Neutral risk round. Never include information published after the cutoff.

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

The credential-free Codex plugin does not register `run_legacy` and does not import the legacy adapter. For explicit backward compatibility outside Codex, the standalone `research` CLI and opt-in `tradingrearchagents-legacy-mcp` executable can delegate Yahoo-style symbols such as `AAPL`, `0700.HK`, `^GSPC`, `EURUSD=X`, `GC=F`, and `BTC-USD` to `TradingAgentsGraph`. Those surfaces are not the current-task execution path and may require environment-owned provider credentials.

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
