# Validation checklist

This checklist records current evidence, not intended capability. Checked items must have a fresh local test or static assertion. Credentialed upstream execution was not performed.

Fresh evidence on `2026-08-02`: `132 passed` from `uv run pytest -q`; `All checks passed!` from `uv run ruff check src tests`; `Success: no issues found in 19 source files` from `mypy --ignore-missing-imports`; successful fixture, backend smoke, MCP stdio smoke, loopback health, and `/api/runs/current/view` checks. The built wheel and installed Codex plugin cache also passed host-plan/MCP startup smoke tests without provider credentials.

## Verified credential-free proof

- [x] `uv run tradingagents-portable fixture --events` completes the deterministic synthetic ORCL run without provider credentials.
- [x] Fixture tests confirm all configured analyst, research-debate, manager, trader, risk-debate, and portfolio stages.
- [x] Tests confirm the fixture produces typed result data, ordered events, the five report groups, and JSON/Markdown artifacts.
- [x] Host-native tests confirm stateless plan expansion, complete-run validation, recursive credential rejection, atomic publication, five report groups, and CLI round-trip without provider keys.
- [x] A complete point-in-time ORCL run was researched by this Codex task, imported as `host-46503d8f4e88`, and rendered as a final dossier: 9 evidence records, 4 analyst reports, 2 Bull/Bear turns, Research Manager, Trader, 3 risk turns, Portfolio Manager, 8 artifacts, and 21 post-import events.
- [x] Dashboard tests confirm loopback serving and read-only run, events, result, and merged `/view` endpoints, including the `current` alias.
- [x] `uv run python scripts/smoke_mcp.py` starts the exact credential-free MCP command, discovers 12 tools, confirms fixture/host-native readiness, prepares a host plan, runs the fixture, and retrieves the merged run view.
- [x] The published host-submission JSON Schema and importer reject future cutoffs, post-cutoff sources, explicit `null` arrays, malformed provenance, unknown fields, duplicate/dangling evidence references, executable decisions, and credential-shaped keys.
- [x] The generic sequential runner executes the same manifest stages through a four-argument `StageExecutor` contract and projects only each stage's declared context.
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
- [x] An explicit upstream checkout cannot be silently shadowed by an already-imported `tradingagents` package; the adapter fails with typed fresh-process guidance instead of purging shared module state.
- [x] Upstream symbol-normalization failures propagate; uppercase fallback is limited to the optional symbol-utility module being unavailable.
- [x] The adapter projects completed upstream logical state into portable contracts without parsing terminal output or copying upstream business logic.
- [x] Checkpointing is opt-in at the portable boundary.

## Not yet verified

- [ ] A live upstream run completes with real provider and data-vendor credentials.
- [ ] Live provider responses and data access work for the documented arbitrary instrument families.
- [ ] Upstream checkpoint creation and resume work end to end.
- [ ] Live upstream stage events stream during execution; this is currently unimplemented.
- [x] A current host harness can execute every workflow stage and atomically import the completed result without API keys.
- [ ] Host-native live token/stage streaming, checkpoint/resume, and cancellation are intentionally outside the portable import contract.

## Verified final-only UI

- [x] The loopback dashboard rendered `host-46503d8f4e88` with 4 analyst cards, 9 safe source links, all merged decision sections, and no run buttons or input controls.
- [x] Markdown-like report content is rendered through DOM/text nodes; literal heading markers are removed and no `innerHTML` execution path is used.
- [x] Browser console inspection returned no warnings or errors for the completed ORCL dossier.

## Integration decision

Do not treat fake-graph delegation tests or upstream importability as evidence of credentialed live readiness. Any integration proposal must preserve the unchecked items above as explicit gaps until fresh runtime evidence exists.
