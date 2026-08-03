# TradingAgents Portable

An isolated, harness-neutral TradingAgents capability that lets the active host harness perform the reasoning and then presents the completed result as a portable dossier.

> **Prototype research only. Not financial advice.** This repository has no broker integration and cannot place, approve, size, submit, modify, or cancel orders.

## Product boundary

- The preferred Codex and generic-harness path is `host_native`: the current host task runs every analyst/debate/decision stage with its own agents and tools, then imports one complete validated result. It accepts no API keys or model-provider configuration.
- The optional `research` CLI and explicit `tradingagents-portable-legacy-mcp` executable retain backward-compatible delegation to upstream `TradingAgentsGraph`; neither is registered by the Codex plugin.
- This repository does not copy analyst, debate, trader, risk, portfolio-manager, provider, or checkpoint business logic from upstream.
- The UI is a strictly post-run, read-only dossier. It merges normalized reports, debates, decisions, signal, provenance, events, and artifacts after upstream execution completes. It does not configure, start, orchestrate, monitor, cancel, or resume a run.
- The deterministic ORCL fixture is the credential-free local proof. It uses synthetic data, executes every declared fixture stage, and emits ordered events without network access.
- Host-native plan/import is implemented and credential-free. It records truthful post-run import receipts; it does not pretend the portable server observed live model execution.
- The portable guarantee is analysis-stage and final-information parity. Agent spawning, checkpoint storage, live progress, token accounting, and other runtime mechanics remain harness-specific.
- Live upstream execution still requires the provider and data credentials expected by TradingAgents. The adapter and result mapping are tested with fakes, but a credentialed live provider run has not been verified in this repository.

The feature matrix separates implementation from runtime readiness. `runtime_readiness.legacy_upstream.ready` reports whether upstream is importable, not whether credentials, data access, checkpoint resume, or a live run are working. Broker execution is prohibited.

## Quick start

Python 3.11+ and `uv` are recommended.

```bash
uv run tradingagents-portable fixture --events
uv run tradingagents-portable dashboard --fixture
uv run tradingagents-portable host-plan ORCL --date 2026-08-01
uv run tradingagents-portable host-import --input ./orcl-host-run.json --dashboard
```

`host-plan` is stateless. The active Codex task or another harness executes the returned roles using its own internal agents and tools. The plan includes exact per-stage context/tool contracts and the versioned host-submission JSON Schema. `host-import` rejects incomplete results, post-cutoff evidence, malformed provenance, dangling references, and credential-shaped fields; it derives metadata/events/artifacts server-side and publishes only the completed dossier.

Install the pinned official upstream runtime before delegated research:

```bash
uv sync --extra upstream
uv run tradingagents-portable research AAPL --date 2026-07-03
```

The `upstream` extra is pinned to the official TradingAgents base commit used for this adapter. `--legacy-path` may point to another compatible checkout and takes precedence, while the pinned extra supplies the upstream runtime dependencies.

Dependency-free fixture smoke check from a checkout:

```bash
PYTHONPATH=src python scripts/smoke_backend.py
```

Start the MCP server directly:

```bash
uv run tradingagents-portable-mcp
```

The included `.mcp.json` starts the 12-tool credential-free server from the plugin root with `PYTHONPATH=src`. It registers no legacy/provider executor and imports no legacy/upstream module. The Codex plugin therefore uses fixture and host-native execution; the optional legacy CLI/server remains a separately configured compatibility path.

## Python API

```python
from tradingagents_portable import RunRequest, run_fixture

result, events = run_fixture(RunRequest(debate_rounds=2, risk_rounds=2))
assert len(result.research_debate) == 4
assert len(result.risk_debate) == 6
```

For a host-owned run, call `prepare_host_run(RunRequest(executor="host_native", ...))`, execute the returned topology in the current harness, then call `submit_host_run(payload)`. The importer never creates an LLM client and never accepts an API key.

For a harness with only one agent, implement `StageExecutor.execute_stage` and call `run_sequential_host_workflow`. The packaged reference runner applies the same manifest, context projections, tool-capability IDs, output schema, and atomic importer without any Codex or LangGraph dependency.

## Upstream execution

This section describes the optional legacy compatibility executor, not the default Codex path.

Install TradingAgents so `tradingagents.graph.trading_graph` is importable, or set `TRADINGAGENTS_LEGACY_PATH` to an upstream repository root. Configure its provider and data-vendor credentials in the process environment. No portable CLI or MCP argument accepts credentials.

The adapter maps portable, non-secret options into the upstream graph and projects its completed state into portable contracts. Checkpointing remains off by the upstream default unless an explicit argument or the upstream environment overlay enables it. Upstream's ordinary decision logs and report files are still written; that persistence is distinct from checkpoint resume. Credentialed execution and checkpoint resume remain runtime-unverified here.

An explicit MCP compatibility server is also available as `uv run tradingagents-portable-legacy-mcp`. It is intentionally absent from `.mcp.json` and the Codex plugin because it may inherit provider credentials from its own environment.

### Non-interactive research CLI

`research` delegates the complete analysis to upstream `TradingAgentsGraph`; this repository does not recreate its business logic. It accepts Yahoo-style company and instrument symbols, including exchange-qualified stocks (`0700.HK`), indices (`^GSPC`), FX/futures (`EURUSD=X`, `GC=F`), and crypto (`BTC-USD`). `--asset-type auto` uses the upstream-compatible crypto suffix rule; all other instruments use the stock pipeline.

```bash
uv run tradingagents-portable research 0700.HK \
  --date 2026-07-03 \
  --analyst market --analyst news --analyst fundamentals \
  --debate-rounds 2 --risk-rounds 2 \
  --provider openai --quick-model gpt-5.4-mini --deep-model gpt-5.5 \
  --reasoning-effort high \
  --report-output ./results/0700-hk \
  --output ./results/0700-hk.json \
  --legacy-path ../tradingAgents
```

Omitting provider/model/round/checkpoint flags preserves upstream defaults after its normal `TRADINGAGENTS_*` environment overlay. `--checkpoint` and `--no-checkpoint` are explicit overrides. `--clear-checkpoints` delegates upstream's cache-scoped cleanup helper and exits. No CLI option accepts API keys or credentials; configure those only in the process environment as required by upstream providers and data vendors.

The adapter also accepts `--provider openai_codex` when the selected upstream checkout contains [TradingAgents PR #1195](https://github.com/TauricResearch/TradingAgents/pull/1195). That provider reads Codex OAuth state through the upstream implementation (default `~/.codex/auth.json`, optionally `TRADINGAGENTS_CODEX_AUTH_PATH`); this portable layer never reads or serializes the token. The PR is currently unmerged and describes the endpoint as undocumented, unversioned, and not clearly sanctioned, so this path is supported at the boundary but is not enabled in the pinned official dependency or runtime-verified here.

Add `--dashboard` to serve the completed, stored run from the same process after graph execution finishes:

```bash
uv run tradingagents-portable research AAPL --date 2026-07-03 \
  --legacy-path ../tradingAgents --dashboard
```

This command requires a working upstream installation and its environment-based credentials. It is documentation for the delegated live path, not part of the credential-free proof.

## Dashboard API

The server rejects non-loopback bind addresses. Its read-only endpoints are:

- `GET /api/health`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/result`
- `GET /api/runs/{run_id}/view`
- `GET /api/runs/current/view`

The `/view` response is the merged, UI-ready post-run dossier. `current` resolves to the latest stored run and also works with the run, events, and result endpoints. A saved `/?run=<run_id>` URL stays pinned to that completed run even after a later run becomes current. Everything else is served from the packaged `tradingagents_portable/web/` assets, with SPA fallback to `index.html` and path traversal protection.

The live run store is process-local. Preserve the host submission or normalized JSON artifact if a dossier must be reconstructed after the MCP/CLI process exits; re-importing the same submission is idempotent and recreates the same run ID.

## Incubation boundary

This prototype deliberately stays separate from the sibling `tradingAgents` repository. The legacy adapter is the only integration seam. Validate contracts, UI behavior, and test expectations here first; decide later which pieces, if any, belong upstream.
