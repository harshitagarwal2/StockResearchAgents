# Validation checklist

This checklist records current evidence, not intended capability. Checked items must have a fresh local test or static assertion. Credentialed upstream execution was not performed.

Fresh evidence on `2026-08-02`: `86 passed` from `uv run pytest -q`; `All checks passed!` from `uv run ruff check .`; successful fixture, backend smoke, pinned-upstream import/signature check, MCP stdio smoke, loopback health, and `/api/runs/current/view` checks.

## Verified credential-free proof

- [x] `uv run tradingagents-portable fixture --events` completes the deterministic synthetic ORCL run without provider credentials.
- [x] Fixture tests confirm all configured analyst, research-debate, manager, trader, risk-debate, and portfolio stages.
- [x] Tests confirm the fixture produces typed result data, ordered events, the five report groups, and JSON/Markdown artifacts.
- [x] Dashboard tests confirm loopback serving and read-only run, events, result, and merged `/view` endpoints, including the `current` alias.
- [x] `uv run python scripts/smoke_mcp.py` starts the exact MCP command with the pinned upstream extra, discovers 11 tools, confirms both executors are importable, runs the fixture, and retrieves the merged run view.
- [x] `uv build` includes the workflow manifest and browser assets; an isolated wheel smoke loads both and completes the fixture.
- [x] Manifest tests parse `.codex-plugin/plugin.json` and `.mcp.json`, inspect the bundled skill, and verify the MCP tool surface.
- [x] `uv run ruff check src tests` passes.
- [x] `uv run pytest -q` passes without live credentials.

## Verified safety and boundary proof

- [x] The ORCL fixture is synthetic and does not call a real provider.
- [x] Security tests reject credential-shaped portable configuration and confirm environment credentials are not serialized.
- [x] Dashboard tests reject non-loopback bind addresses and verify escaping/path traversal protections.
- [x] Surface tests confirm there is no broker/order tool or executable action and trade-like outputs are labeled non-executable.
- [x] UI contract tests confirm the browser is a post-run reader: it fetches the merged `/view` response and contains no fixture or upstream execution controls.

## Verified delegated adapter behavior

- [x] Fake-graph tests confirm portable CLI/MCP symbol strings are delegated unchanged to upstream `TradingAgentsGraph`, including stock, exchange-qualified, and crypto examples; the portable parser does not restrict other Yahoo-style instrument families.
- [x] Tests confirm selected analysts, asset type, date, debate/risk rounds, typed provider/model settings, and checkpoint override map to the upstream call.
- [x] A fake-graph boundary test confirms `openai_codex` and its reasoning setting pass through while Codex OAuth paths/content remain outside serialized results.
- [x] Missing upstream installation/configuration produces typed setup guidance.
- [x] The adapter projects completed upstream logical state into portable contracts without parsing terminal output or copying upstream business logic.
- [x] Checkpointing is opt-in at the portable boundary.

## Not yet verified

- [ ] A live upstream run completes with real provider and data-vendor credentials.
- [ ] Live provider responses and data access work for the documented arbitrary instrument families.
- [ ] Upstream checkpoint creation and resume work end to end.
- [ ] Live upstream stage events stream during execution; this is currently unimplemented.
- [ ] A host-native stage executor runs the workflow; this is currently unimplemented.

## Integration decision

Do not treat fake-graph delegation tests or upstream importability as evidence of credentialed live readiness. Any integration proposal must preserve the unchecked items above as explicit gaps until fresh runtime evidence exists.
