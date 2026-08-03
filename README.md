# tradingrearchagents

An isolated, harness-neutral research capability that lets the active host harness perform the reasoning and then presents the completed result as a portable dossier.

> Upstream project: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). `tradingrearchagents` is an independent adapter, Codex plugin, MCP surface, and dossier UI; it integrates with the pinned upstream project without copying or replacing its workflow business logic.

> **Prototype research only. Not financial advice.** The capability may preserve analytical ratings, targets, stops, and sizing scenarios, but it has no broker integration or authority to submit, modify, cancel, approve, or fill an order.

## Product boundary

- The preferred Codex and generic-harness path is the durable `host_native` lifecycle: create, start, append safe receipts, commit each completed stage, optionally pause/resume or request/acknowledge cancellation, then finalize one validated result. The portable boundary accepts no API keys or model-provider configuration; concrete tools and any tool authentication remain host-owned.
- The optional `research` CLI and explicit `tradingrearchagents-legacy-mcp` executable retain backward-compatible delegation to upstream `TradingAgentsGraph`; neither is registered by the Codex plugin.
- This repository does not copy analyst, debate, trader, risk, portfolio-manager, provider, or checkpoint business logic from upstream.
- The UI is a strictly completed-result, read-only dossier. Lifecycle-backed runs stay absent from every dashboard surface while `get_run_control` or `poll_run_events` reports `finalizing` with `publication_pending=true`; direct fixture/import runs remain available without a lifecycle record. Lifecycle control and cursor polling are CLI/MCP concerns, and the browser does not configure, start, orchestrate, monitor, cancel, or resume a run.
- The deterministic ORCL fixture is the credential-free local proof. It uses synthetic data, executes every declared fixture stage, and emits ordered events without network access.
- The mutable `run-lifecycle.v1` protocol is separate from the frozen terminal `host-submission.v2` schema. Private SQLite/WAL checkpoints, atomic canonical result/event bundles, optimistic revisions, receipt-linked observation, stage-boundary resume, cooperative cancellation, publication-gated decision memory, and report export are locally verified.
- Topology, decision-schema, report-group, lifecycle, persistence, interactive CLI, portable-invariant conformance, optional pinned-checkout identity, and safety-contract parity are verified; see [Feature parity](docs/FEATURE_PARITY.md).
- Live upstream execution still requires the provider and data credentials expected by TradingAgents. The adapter and result mapping are tested with fakes, but a credentialed live provider run has not been verified in this repository.

The feature matrix separates implementation from runtime readiness. `runtime_readiness.legacy_upstream.ready` reports whether upstream is importable, not whether credentials, data access, checkpoint resume, or a live run are working. Exact model text and token-level continuation remain harness-specific. Broker/order execution is prohibited.

## Keeping upstream current

`upstream.lock.json` is the single declared upstream source of truth. It pins the exact `TauricResearch/TradingAgents` `main` revision used by the optional dependency, conformance checks, lockfile, and CI checkout.

The `sync upstream TradingAgents` workflow runs weekly and can also be started manually. It compares the pin with upstream `main`; when a newer commit exists, it updates every pinned surface, regenerates `uv.lock`, checks the proposed upstream checkout, runs formatting, lint, all tests, both smoke checks, and the package build, then opens a review PR. It never auto-merges an upstream change.

Local maintenance commands are:

```bash
python scripts/upstream_pin.py --check
python scripts/upstream_pin.py --set-revision <full-upstream-sha>
uv lock
```

## Upstream RFC

The proposed long-term boundary with TradingAgents is documented in
[Harness-neutral TradingAgents integrations](docs/UPSTREAM_RFC.md). The RFC
asks whether the portable workflow contract should live upstream, remain in
this independent repository, or be split between a thin upstream contract and
external harness adapters. No upstream merge is assumed without maintainer
buy-in. Upstream discussion is tracked in
[TauricResearch/TradingAgents#1198](https://github.com/TauricResearch/TradingAgents/issues/1198).

## Quick start

Python 3.11+ and `uv` are recommended.

```bash
uv run tradingrearchagents fixture --events
uv run tradingrearchagents dashboard --fixture
uv run tradingrearchagents host-init ORCL --date 2026-08-01 --interactive
uv run tradingrearchagents host-plan ORCL --date 2026-08-01
uv run tradingrearchagents host-import --input ./orcl-host-run.json --dashboard
```

`host-init` starts the durable path and may prompt for portable, non-secret research settings with `--interactive`. The host then owns reasoning, agent spawning, concrete tool calls, and hard interruption. The portable layer owns stage order, safe receipts, checkpoint commits, cursor-readable events, validation, and publication.

### Durable Codex/host task flow

1. `host-init` creates a `run-lifecycle.v1` record; `host-start` returns the first stage.
2. The host performs that stage and may append sanitized `host-receipts` containing summaries, digests, timings, and evidence IDs—never prompts, raw tool arguments, transcripts, or credentials. A truthful observed execution uses matching `stage_started` and `stage_completed` receipts for the same attempt; the completion digest must match the committed output.
3. `host-stage-commit` atomically checkpoints the stage output and returns the next stage. Every mutation uses the latest returned `revision`.
4. `host-pause`/`host-resume` continue from the first incomplete stage. Interrupted in-flight work is replayed; token-level continuation is not promised.
5. `run-cancel` requests cooperative cancellation and `run-cancel-ack` makes it terminal after the host has actually stopped its work.
6. `host-finalize` validates all committed stages, stages result/events and memory behind hidden publication boundaries, commits the lifecycle, then atomically publishes the canonical completed bundle. Any boundary failure is retryable; memory is excluded from recall until lifecycle completion. Launch the browser only after this succeeds.

`run-events RUN_ID --after CURSOR` provides portable live progress through a monotonic polling cursor. A harness may add push delivery, but push is not required by the contract.

### Backward-compatible atomic import

The stateless plan/import seam remains supported for callers that already produce one complete payload:

```bash
uv run tradingrearchagents host-plan ORCL --date 2026-08-01 --output ./plan.json
uv run tradingrearchagents host-import --input ./orcl-host-run.json --output ./result.json
```

`host-import` validates the frozen `host-submission.v2` schema, provenance cutoff, evidence references, non-execution invariants, and credential-shaped keys before publishing anything. It does not provide partial checkpoints or live receipts; new Codex tasks should use the durable lifecycle above.

Install the pinned official upstream runtime before delegated research:

```bash
uv sync --extra upstream
uv run tradingrearchagents research AAPL --date 2026-07-03
```

The `upstream` extra is pinned to the official TradingAgents base commit used for this adapter. `--legacy-path` may point to another compatible checkout and takes precedence, while the pinned extra supplies the upstream runtime dependencies.

Dependency-free fixture smoke check from a checkout:

```bash
PYTHONPATH=src python scripts/smoke_backend.py
```

Start the MCP server directly:

```bash
uv run tradingrearchagents-mcp
```

The included `.mcp.json` starts the 27-tool credential-free server from the plugin root with `PYTHONPATH=src`. It covers discovery, fixture execution, legacy-compatible plan/import, durable lifecycle control, cursor receipts, decision memory, report export, conformance, completed-run reads, and final dashboard launch. It registers no legacy/provider executor and imports no legacy/upstream module.

## Python API

```python
from tradingrearchagents import RunRequest, run_fixture

result, events = run_fixture(RunRequest(debate_rounds=2, risk_rounds=2))
assert len(result.research_debate) == 4
assert len(result.risk_debate) == 6
```

For a durable host-owned run, use `HostRunCoordinator.create`, `start`, `append_receipts`, `commit_stage`, and `finalize`; `pause`, `resume`, `request_cancel`, and `acknowledge_cancel` provide stage-boundary control. `DecisionMemoryStore` recalls at most five same-symbol and three cross-symbol published decisions and can append later observed outcomes/reflections. `export_run_bundle` atomically creates a new upstream-compatible report tree; validated overwrite is journaled and crash-recoverable.

For backward compatibility, `prepare_host_run(RunRequest(executor="host_native", ...))` plus `submit_host_run(payload)` still performs one atomic completed-run import. Neither path creates an LLM client or accepts an API key.

For a harness with only one agent, implement `StageExecutor.execute_stage` and call `run_sequential_host_workflow`. The packaged reference runner applies the same manifest, context projections, tool-capability IDs, output schema, and atomic importer without any Codex or LangGraph dependency.

## Upstream execution

This section describes the optional legacy compatibility executor, not the default Codex path.

Install TradingAgents so `tradingagents.graph.trading_graph` is importable, or set `TRADINGAGENTS_LEGACY_PATH` to an upstream repository root. Configure its provider and data-vendor credentials in the process environment. No portable CLI or MCP argument accepts credentials.

The adapter maps portable, non-secret options into the upstream graph and projects its completed state into portable contracts. Checkpointing remains off by the upstream default unless an explicit argument or the upstream environment overlay enables it. Upstream's ordinary decision logs and report files are still written; that persistence is distinct from checkpoint resume. Credentialed execution and checkpoint resume remain runtime-unverified here.

An explicit MCP compatibility server is also available as `uv run tradingrearchagents-legacy-mcp`. It is intentionally absent from `.mcp.json` and the Codex plugin because it may inherit provider credentials from its own environment.

### Non-interactive research CLI

`research` delegates the complete analysis to upstream `TradingAgentsGraph`; this repository does not recreate its business logic. It accepts Yahoo-style company and instrument symbols, including exchange-qualified stocks (`0700.HK`), indices (`^GSPC`), FX/futures (`EURUSD=X`, `GC=F`), and crypto (`BTC-USD`). `--asset-type auto` uses the upstream-compatible crypto suffix rule; all other instruments use the stock pipeline.

```bash
uv run tradingrearchagents research 0700.HK \
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
uv run tradingrearchagents research AAPL --date 2026-07-03 \
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

The `/view` response is the merged, UI-ready post-run dossier. `current` resolves to the latest stored run and also works with the run, events, and result endpoints. A saved `/?run=<run_id>` URL stays pinned to that completed run even after a later run becomes current. Everything else is served from the packaged `tradingrearchagents/web/` assets, with SPA fallback to `index.html` and path traversal protection.

Durable host-native runs use private SQLite/WAL lifecycle state plus canonical atomic result/event bundles and compatibility projections under the configured state directory. The browser still reads completed results only; lifecycle status and live cursor receipts remain on CLI/MCP surfaces. Preserve exported bundles when a portable, independently verifiable archive is required.

## Incubation boundary

This prototype deliberately stays separate from the sibling `tradingAgents` repository. The legacy adapter is the only integration seam. Validate contracts, UI behavior, and test expectations here first; decide later which pieces, if any, belong upstream.
