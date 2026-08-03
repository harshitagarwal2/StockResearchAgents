# TradingAgents Portable

An isolated, harness-neutral adapter for running upstream TradingAgents research and inspecting the completed result as a portable dossier.

> **Prototype research only. Not financial advice.** This repository has no broker integration and cannot place, approve, size, submit, modify, or cancel orders.

## Product boundary

- The `research` CLI command and MCP `run_legacy` tool accept arbitrary Yahoo-style company or instrument symbols and delegate the complete feature execution to upstream `TradingAgentsGraph`.
- This repository does not copy analyst, debate, trader, risk, portfolio-manager, provider, or checkpoint business logic from upstream.
- The UI is a strictly post-run, read-only dossier. It merges normalized reports, debates, decisions, signal, provenance, events, and artifacts after upstream execution completes. It does not configure, start, orchestrate, monitor, cancel, or resume a run.
- The deterministic ORCL fixture is the credential-free local proof. It uses synthetic data, executes every declared fixture stage, and emits ordered events without network access.
- Live upstream execution requires the provider and data credentials expected by TradingAgents. The adapter and result mapping are tested with fakes, but a credentialed live provider run has not been verified in this repository.
- Host-native execution and live upstream event streaming are not implemented. Legacy events are reconstructed from completed state.

The feature matrix separates implementation from runtime readiness. `runtime_readiness.legacy_upstream.ready` reports whether upstream is importable, not whether credentials, data access, checkpoint resume, or a live run are working. Broker execution is prohibited.

## Quick start

Python 3.11+ and `uv` are recommended.

```bash
uv run tradingagents-portable fixture --events
uv run tradingagents-portable dashboard --fixture
```

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

The included `.mcp.json` starts the same module from the plugin root with `PYTHONPATH=src` and the pinned `upstream` extra, which keeps the cached plugin bundle self-contained while still allowing `TRADINGAGENTS_LEGACY_PATH` to override the upstream code.

## Python API

```python
from tradingagents_portable import RunRequest, run_fixture

result, events = run_fixture(RunRequest(debate_rounds=2, risk_rounds=2))
assert len(result.research_debate) == 4
assert len(result.risk_debate) == 6
```

## Upstream execution

Install TradingAgents so `tradingagents.graph.trading_graph` is importable, or set `TRADINGAGENTS_LEGACY_PATH` to an upstream repository root. Configure its provider and data-vendor credentials in the process environment. No portable CLI or MCP argument accepts credentials.

The adapter maps portable, non-secret options into the upstream graph and projects its completed state into portable contracts. Checkpointing remains off by the upstream default unless an explicit argument or the upstream environment overlay enables it. Upstream's ordinary decision logs and report files are still written; that persistence is distinct from checkpoint resume. Credentialed execution and checkpoint resume remain runtime-unverified here.

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

The `/view` response is the merged, UI-ready post-run dossier. `current` resolves to the latest stored run and also works with the run, events, and result endpoints. Everything else is served from the packaged `tradingagents_portable/web/` assets, with SPA fallback to `index.html` and path traversal protection.

## Incubation boundary

This prototype deliberately stays separate from the sibling `tradingAgents` repository. The legacy adapter is the only integration seam. Validate contracts, UI behavior, and test expectations here first; decide later which pieces, if any, belong upstream.
