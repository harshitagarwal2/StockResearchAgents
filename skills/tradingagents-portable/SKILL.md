---
name: tradingagents-portable
description: Delegate arbitrary Yahoo-style company or instrument research to upstream TradingAgentsGraph, then inspect the completed result as a read-only dossier. Also use the deterministic credential-free ORCL fixture to verify the portable contracts and UI without live provider access.
---

# TradingAgents Portable

Use this plugin to call the upstream execution authority without copying its business logic, then inspect the completed normalized output. The browser UI and inline view are post-run readers, not workflow executors.

## Credential-free proof

1. Call `discover_capability` and `get_feature_matrix` when runtime readiness matters.
2. Call `prepare_fixture` to inspect the exact expanded topology.
3. Call `run_fixture` for a credential-free, deterministic ORCL run dated `2026-07-03`.
4. Inspect the response directly or retrieve the complete merged dossier with `get_run_view`; use `get_run_events`, `get_run_result`, and `get_dashboard_report` for narrower post-run projections.
5. Call `launch_local_dashboard` only after a result exists and a browser-oriented view is useful. It binds to loopback and exposes no execution controls.

The fixture covers all configured analysts, exactly `2 × debate_rounds` Bull/Bear turns, Research Manager, Trader, exactly `3 × risk_rounds` Aggressive/Conservative/Neutral turns, and Portfolio Manager.

## Delegated upstream research

Use `run_legacy` for arbitrary Yahoo-style company or instrument symbols when the upstream package or `TRADINGAGENTS_LEGACY_PATH` is configured. Examples include `AAPL`, `0700.HK`, `^GSPC`, `EURUSD=X`, `GC=F`, and `BTC-USD`. The tool delegates the complete feature execution to `TradingAgentsGraph`; the portable layer does not implement or copy analyst, debate, trader, risk, portfolio-manager, provider, or checkpoint logic.

- Provider credentials are environment-only. Never put an API key, token, password, cookie, authorization value, or other credential in a tool argument, run request, event, result, report, or dashboard field.
- `openai_codex` is accepted when the configured upstream checkout contains PR #1195. Let upstream read its Codex auth file directly (optionally via `TRADINGAGENTS_CODEX_AUTH_PATH`); never copy OAuth contents into a tool argument or result. Treat this unmerged, undocumented provider as runtime-unverified.
- Use only the typed `run_legacy` settings for `asset_type`, provider/model names, backend URL, output language, temperature, retry count, and provider reasoning effort. Arbitrary configuration objects are intentionally not exposed.
- Omitted debate/risk settings and `checkpoint_enabled` honor the upstream environment overlay; the upstream checkpoint default is false. Enable checkpointing only for an intentional runtime test because creation and resume have not been verified here. Ordinary upstream decision/report persistence does not imply checkpointing.
- Expect upstream's normal data-provider, report, and decision-log side effects during an explicit legacy run.
- If setup is incomplete, return the typed guidance from `legacy_executor_unavailable` instead of guessing configuration.

After `run_legacy` completes, use `get_run_view` for the merged dossier. `get_run_events` returns post-run projected events; it is not a live stream. `launch_local_dashboard` serves the same completed data and must not be presented as setup, orchestration, progress monitoring, cancellation, or resume UI.

## Capability truthfulness

- `fixture` is implemented and verified locally.
- Arbitrary-symbol CLI/MCP delegation and completed-state mapping are covered by fake-graph tests. A credentialed live provider run has not been verified.
- `legacy` events are reconstructed after completion. Importability does not verify provider credentials, data access, checkpoint behavior, or successful live execution.
- Live legacy stage streaming is unavailable until upstream provides an observer seam.
- Host-native execution is manifest/instructions only; it is not an implemented executor.
- Run cancellation is unavailable. Checkpoint/resume is legacy-delegated, opt-in, and runtime-unverified here.

## Safety boundary

Every output is prototype research, not personalized financial advice. The capability has no broker connection and must never place, simulate, approve, size, submit, modify, or cancel an order. Treat fixture values as synthetic integration-test data, never as facts about Oracle or current markets.
