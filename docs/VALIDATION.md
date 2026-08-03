# Validation checklist

This checklist records current evidence, not intended capability. Checked items must have a fresh local test or static assertion. Credentialed upstream execution was not performed.

Fresh evidence on `2026-08-03`: `229 passed` from the credential-free local suite. Ruff, Ruff format, mypy, compileall, wheel build, the 27-tool MCP smoke, source-plugin validation, and installed-plugin cache validation also pass. Browser checks cover desktop and mobile layouts, completion-only rendering, synthetic-fixture disclosure, safe source links, and an empty console. Credentialed upstream execution was not performed.

## Verified research-intelligence dossier increment

- [x] Projection tests confirm backward-compatible normalization of `EvidenceItem.values` metrics, articles, catalysts, risks, conflicts, unknowns, and monitoring conditions, including safe public URLs, recognized source-quality values, mixed timezone offsets, and sparse legacy evidence.
- [x] Workflow and skill tests confirm newest-cutoff-valid retrieval, adaptive history, primary-source-first news, discovery-only aggregator handling, multi-period fundamentals, explicit source quality, verification status, deduplication, and no-key fallback guidance.
- [x] UI contract and browser checks confirm the evidence-integrity chain, coverage/source/freshness panels, metric and news ledgers, catalysts, risk register, conflicts, unknowns, and monitoring conditions render only for completed runs without controls or executable actions.
- [x] The deterministic ORCL fixture demonstrates the richer structures while labeling every fixture date and timestamp as synthetic and explicitly stating that no live retrieval occurred.
- [x] The full credential-free suite, Ruff, Ruff format, mypy, compileall, build, MCP smoke checks, source-plugin validation, and installed-plugin cache validation pass after the increment.
- [x] Desktop and 390-pixel mobile browser checks show no page-level horizontal overflow; navigation and the metrics ledger scroll independently, metric headers expose column scopes, fixture source links remain non-clickable, and browser logs are empty.

## Verified credential-free proof

- [x] `uv run tradingagents-portable fixture --events` completes the deterministic synthetic ORCL run without provider credentials.
- [x] Fixture tests confirm all configured analyst, research-debate, manager, trader, risk-debate, and portfolio stages.
- [x] Tests confirm the fixture produces typed result data, ordered events, the five report groups, and JSON/Markdown artifacts.
- [x] `run-lifecycle.v1` tests confirm SQLite/WAL restart recovery, optimistic revision conflicts, create/start/receipt/commit/pause/resume/cancel-ack/finalize transitions, and replay of only the interrupted incomplete stage.
- [x] `host-submission.v2` remains the frozen terminal schema; tests independently retain backward-compatible stateless plan/import validation and atomic publication.
- [x] Safe live stage/tool receipts reject credential-shaped fields, unsupported fields, invalid digests, duplicate IDs, disallowed stage capabilities, and incorrect stage/attempt associations. `execution_observed` requires linked start/completion receipts with an output digest matching the checkpoint; receipt batches, retained counts, evidence IDs, cursor pages, and lifecycle record size are bounded.
- [x] Durable result/event fault tests inject failure at every direct-put boundary; restart recovers from the private intent into one canonical atomic bundle, never exposes an orphan result, and keeps lifecycle stages hidden until explicit publication.
- [x] Decision-memory tests confirm SQLite durability, publication gating during finalization, idempotent retry by run ID, at most five same-symbol plus three cross-symbol recalls, later outcome/reflection append, and secret-shaped-key rejection.
- [x] Export tests verify every report path, complete report, result/events, optional lifecycle log, byte counts, and SHA-256 digests. Overwrite accepts only a verified prior bundle and subprocess crash injection confirms journaled recovery between directory renames.
- [x] Host-native tests confirm plan expansion, complete-run validation, recursive credential rejection, five report groups, and CLI round-trip without provider keys.
- [x] A complete point-in-time ORCL run researched by this Codex task was freshly replayed through every durable boundary as `host-fe876e15883a`: 9 evidence records, 4 analyst reports, 2 Bull/Bear turns, Research Manager, Trader, 3 risk turns, Portfolio Manager, 8 artifacts, and 42 linked-receipt/lifecycle/final events. Earlier browser rendering used `host-e19da9daacb2` and remains separate visual evidence.
- [x] Dashboard tests confirm loopback serving and read-only run, events, result, and merged `/view` endpoints, including the `current` alias.
- [x] MCP registration/discovery tests confirm the default credential-free surface has 27 tools and the opt-in legacy server adds only `run_legacy`.
- [x] The published host-submission JSON Schema and importer reject future cutoffs, post-cutoff sources, explicit `null` arrays, malformed provenance, unknown fields, duplicate/dangling evidence references, executable decisions, and credential-shaped keys.
- [x] The generic sequential runner executes the same manifest stages through a four-argument `StageExecutor` contract and projects only each stage's declared context.
- [x] `uv build` includes the workflow manifest and browser assets; an isolated wheel smoke loads both and completes the fixture.
- [x] Manifest tests parse `.codex-plugin/plugin.json` and `.mcp.json`, inspect the bundled skill, and verify the MCP tool surface.
- [x] Credential-free conformance tests validate portable workflow order/counts, decision schemas, signal derivation, evidence references, report groups, and linked receipt contracts. When supplied, the sibling checkout separately matches pinned revision `a33fd4c0f134485a43553a2c23a63cb14adbd88f`; this is identity verification, not upstream behavioral proof.
- [x] CLI tests cover interactive-capable durable setup, control/events, cooperative cancellation, memory, export, and conformance command routing.
- [x] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy --ignore-missing-imports src`, and compileall pass.
- [x] `uv run pytest -q` passes without live credentials.

## Verified safety and boundary proof

- [x] The ORCL fixture is synthetic and does not call a real provider.
- [x] Security tests reject credential-shaped portable configuration and confirm environment credentials are not serialized.
- [x] Dashboard tests reject non-loopback bind addresses and verify escaping/path traversal protections.
- [x] Surface tests confirm there is no broker/order tool or executable action and trade-like outputs are labeled non-executable.
- [x] Lifecycle and memory receipt tests confirm API keys, tokens, authorization fields, and other credential-shaped keys cannot cross portable boundaries.
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
- [ ] Upstream-owned checkpoint creation and resume work end to end in a credentialed legacy process.
- [ ] Live upstream stage events stream during legacy execution; the upstream adapter still has no observer seam.
- [x] A current host harness can execute every workflow stage and atomically import the completed result without API keys.
- [x] Host-native cursor receipts, durable stage-boundary resume, and cooperative cancellation are locally verified.
- [ ] Exact model text, token-level continuation, host hard interruption, and optional push delivery remain harness-specific and are not claimed by portable conformance.

## Verified final-only UI

- [x] The loopback dashboard rendered durable run `host-e19da9daacb2` with Research `Hold`, Trader `Hold`, Portfolio `Hold`, derived signal `HOLD`, 4 analyst cards, 9 safe source links, all merged decision sections, and no run buttons or input controls.
- [x] Markdown-like report content is rendered through DOM/text nodes; literal heading markers are removed and no `innerHTML` execution path is used.
- [x] Browser console inspection returned no warnings or errors for the completed ORCL dossier.

## Verified cross-company matrix

- [x] This Codex task freshly replayed and finalized full durable host-native dossiers for MSFT (`host-0bb0768da623`), JPM (`host-42d7fb642292`), and Tencent `0700.HK` (`host-025683fdba08`) with the `2026-08-01` cutoff; fresh ORCL is `host-fe876e15883a`.
- [x] Every fresh matrix dossier contains four analyst reports, two research-debate turns, three risk-debate turns, the Research Manager, Trader, Portfolio Manager, eight artifacts, 42 linked-receipt/lifecycle/final events, non-executable decisions, and `external_credentials_required=false`.
- [x] Every fresh matrix run rehydrated after a new store instance, exposed exactly one completed decision-memory record, exported 16 content/log files plus a digest manifest, passed every portable observable-invariant check, and separately verified the sibling checkout identity at revision `a33fd4c0f134485a43553a2c23a63cb14adbd88f`.
- [x] Evidence counts were 7 for MSFT and 6 each for JPM and Tencent. No source date exceeded the cutoff, and every retrieval timestamp included a timezone.
- [x] The keyless market evidence tool returned dated snapshots for MSFT, JPM, `0700.HK`, `BRK-B`, `7203.T`, `SAP.DE`, and BABA. The plan contract also expanded the complete 12-stage topology for the four additional symbol formats.
- [x] Browser verification found the correct company/run identity, four analyst cards, one safe link per evidence record, no input or run controls, no literal Markdown headings, and no console warnings/errors for all three dossiers.
- [x] Matrix testing found and fixed two negative-path defects: invalid future plans now return structured guidance instead of a traceback, and legitimate financial authorization fields no longer trigger the credential-key scanner. Actual credential-shaped fields remain rejected.

## Integration decision

Do not treat fake-graph delegation, importability, or credential-free observable conformance as evidence of credentialed live readiness. The host owns reasoning, agent spawning, concrete tools, and hard interruption. The browser remains a finalized-result reader, and no portable surface accepts API keys or performs broker/order execution.
