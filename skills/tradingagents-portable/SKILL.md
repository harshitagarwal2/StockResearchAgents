---
name: tradingagents-portable
description: Research any supported financial instrument with the current Codex task or another host harness, import the complete credential-free result, and inspect it as a read-only dossier. The optional legacy adapter remains available for backward compatibility.
---

# TradingAgents Portable

Use this plugin's host-native path by default. The current Codex task supplies reasoning, subagents, and research tools; TradingAgents Portable supplies the exact workflow topology, typed result contract, validation, artifacts, and final UI. The server must not request or accept an API key. The browser UI and inline view are post-run readers, not workflow executors.

## Internal Codex task run (preferred)

1. Call `prepare_host_run` with the symbol, date, analyst set, and round counts.
2. Follow the returned `workflow_semantics`: stage instructions, source priority, point-in-time cutoff, evidence windows, and no-key fallback behavior.
3. Execute every returned stage in order using this Codex task's own reasoning, subagents, and available research tools. Write every stage in `request.output_language`. Do not create an external LLM client and do not ask for provider credentials.
4. Keep source URLs, source dates, retrieval times, limitations, and evidence IDs with each analyst output.
5. Submit one complete payload with `import_host_run`. The importer rejects missing stages, dangling evidence, invalid confidence, executable trade fields, and credential-shaped keys before publishing anything.
6. Inspect `view` in the response or call `get_run_view`. Launch the dashboard only after import succeeds.

If the user omits configuration, use the request date as the research cutoff; if omitted, use today's local date and record the latest completed market session separately. Default to all compatible analysts, one Bull/Bear round, and one Aggressive/Conservative/Neutral risk round. Never include information published after the cutoff.

Host-native events are completion/import receipts. Never describe them as token streaming or portable observation of the host's internal execution. Checkpointing and cancellation remain owned by the host harness and are not exposed in the final UI.

Harnesses without native subagents use the packaged sequential fallback and the same stage/output schema. Agent spawning, checkpoint storage, and live telemetry are adapter-specific; analyst/debate/decision stages and final dossier information remain common.

## Credential-free proof

1. Call `discover_capability` and `get_feature_matrix` when runtime readiness matters.
2. Call `prepare_fixture` to inspect the exact expanded topology.
3. Call `run_fixture` for a credential-free, deterministic ORCL run dated `2026-07-03`.
4. Inspect the response directly or retrieve the complete merged dossier with `get_run_view`; use `get_run_events`, `get_run_result`, and `get_dashboard_report` for narrower post-run projections.
5. Call `launch_local_dashboard` only after a result exists and a browser-oriented view is useful. It binds to loopback and exposes no execution controls.

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
- Host-native plan/import is implemented and locally verified. The host owns execution; the portable layer validates and publishes the completed output.
- Run cancellation is unavailable. Checkpoint/resume is legacy-delegated, opt-in, and runtime-unverified here.

## Safety boundary

Every output is prototype research, not personalized financial advice. The capability has no broker connection and must never place, simulate, approve, size, submit, modify, or cancel an order. Treat fixture values as synthetic integration-test data, never as facts about Oracle or current markets.
