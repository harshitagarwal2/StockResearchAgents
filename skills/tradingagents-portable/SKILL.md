---
name: tradingagents-portable
description: Run StockResearchAgents as evidence-first, point-in-time company research through the harness-neutral company-analytics.v1 workflow, including adaptive multi-source web retrieval, deterministic analytics, forecasts, outcome scoring, and a completed-only report. Use for company or security research in Codex or another MCP-capable harness without placing model/provider API keys, browser credentials, raw licensed content, or broker authority inside the portable core.
---

# StockResearchAgents

Use `company-analytics.v1` as the primary profile. Treat StockResearchAgents as a contract, analytics, publication, and read-model capability—not as the model or data provider.

Keep these authorities separate:

- Let the active harness own web/browser/provider retrieval, model reasoning, native agents, authentication, entitlements, and hard interruption.
- Let Portable own the 26-stage workflow contract, strict point-in-time and terminal validation, deterministic calculations, research-quality records, atomic completed publication, and completed-only projection. The host attests intermediate completion criteria; Portable records opaque nonterminal envelopes as committed, not independently verified content.
- Never put an API key, token, cookie, authorization value, provider configuration, raw source body, unrestricted tool argument, or broker/order instruction into a portable call.

## Run company analytics

1. Resolve the exact instrument identity. Do not guess an exchange, share class, fund, or crypto asset from an ambiguous symbol.
2. Set `requested_at` and `cutoff_at` to exact timezone-aware instants. Use the current instant as the cutoff for a current-research request unless the user asks for a historical replay.
3. Declare a truthful `research_mode`: `live` only after live retrieval; `fixture` for synthetic test data; `historical_replay` for retained as-of evidence.
4. Call `discover_capability`, then `prepare_company_analytics` with a schema-valid company request, execution mode, and the most suitable research pack. Default to `initiating-coverage.v1` for a full company picture and `compatible` when the harness lacks native subagents. Execute the returned `stage-instructions.v1` roles, objectives, completion criteria, dependencies, capabilities, and output refs; exact prompt wording remains host-owned. The returned v4 schema is self-contained and includes typed analytics records; use the strict Python contracts as authoritative for cross-field semantics.
5. Execute dependency-ready stages in parallel only for a stateless host plan. In a durable full-mode run, commit exactly the current first-incomplete stage, accept the returned next stage, and preserve that order even if host tools gathered supporting evidence concurrently. Do not omit stages merely because the harness lacks subagents.
6. Execute the source-portfolio plan below with host-owned web, browser, connector, or research-data tools. Do not stop after the first successful provider when more explicit routes are configured: use `SourcePortfolioCollector` for same-capability fan-out, retain its `SourcePortfolioReceipt`, and carry the receipt's ordered route-qualified `source_batch_ids` into the run card and source-lineage crosswalk. GDELT and search results are discovery evidence only: open the underlying issuer, regulator, exchange, macro authority, or attributable publisher page before treating a claim as verified. Normalize only bounded evidence, locators, hashes, timestamps, and permitted extracts into the terminal contracts. Preserve SourceBatch/observation identity, digest scope, dossier document ID, analytics source/license receipt, and entitlement translation in the versioned source-lineage crosswalk.
7. Produce deterministic analytics for fundamentals, ratios, valuation, consensus, positioning, catalysts, and declared experiments. Preserve input IDs, units, periods, rounding, assumptions, implementation digests, and point-in-time dataset receipts.
8. Issue falsifiable hypotheses and explicit forecasts only when their target, horizon, resolution rule, evidence, and cutoff are defined. Namespace every `forecast_id` globally with the exact `<quality_run_id>.` prefix. Never reinterpret confidence, rating strength, or risk severity as a forecast probability.
9. Assemble one complete `host-submission.v4` wrapper containing the unchanged v3 request/dossier plus analytics, source-lineage crosswalk, run card, hypothesis ledger, research iterations, quality receipt, and forecast set. The run card must bind the shipped workflow digest, selected execution mode, and exact ordered 26-stage receipt set.
10. Prefer `create_company_analytics_run` for a durable run. Use the shared start, receipt, stage-commit, pause/resume, cancellation, event, and finalize controls with the latest optimistic revision across all 26 stages. Resume from the first incomplete stage; replay interrupted in-flight host work. Treat nonterminal stage events as durable commitments, not proof that Portable read host-owned content. The final stage must contain the complete v4 payload and pass strict v4 plus coordinator-commitment validation. Treat completed `RunResult.artifacts` as the atomically published authoritative sidecars. The quality outcome index is recoverable derived state, not part of a distributed transaction.
11. After a successful `finalize_host_run` or `import_company_analytics`, inspect its `presentation` receipt. When
    `status` is `ready`, return or open its run-specific `url`; in Codex App, show that local URL as the completed end
    product. When `status` is `path_only`, render `get_run_view` inline. When `status` is `unavailable`, keep the
    completed research result and retry presentation with `launch_research_report`; `launch_local_dashboard` remains a
    compatibility alias. Never launch one page per company, never open a browser before completion, and never present
    private partial-stage material as a completed result. Use `import_company_analytics` only when the host already has
    one complete v4 payload and does not need lifecycle checkpoints.
12. After a forecast resolves, append a typed observation with `record_research_outcome`; inspect reproducible records with `get_research_quality`. Corrections must supersede earlier observations rather than overwrite history.

CLI adapter equivalents are `analytics-plan`, `analytics-init`, shared `host-*` / `run-*` lifecycle commands, `analytics-import`, `quality-outcome`, and `quality-show`.

## Retrieve current and historical evidence

Start with the newest evidence actually available at `cutoff_at`. Confirm later amendments, corrections, official results, guidance, and the latest completed market session before relying on older material.

Keep the two MCP surfaces distinct. The coordination server registers no research-data tools. The separate research-data server, launched with the preferred `stock-research-data-mcp` executable, registers seven SourceBatch v1 public tools by default: SEC regulatory filings, fundamentals, and financial statements; GDELT company and global news metadata plus publisher links; World Bank macro observations; and credential-free `prediction_markets` search through Polymarket Gamma as `research_data_get_prediction_markets`. Its manifest key remains `tradingagents-research-data` for compatibility. Treat World Bank values as current-vintage only because its API cannot reconstruct historical revision lineage. Use Polymarket only when a prediction market is decision-relevant. Gamma returns public, read-only market metadata; it exposes no wallet, CLOB, order, position, or trading endpoint. Treat its probabilities as current market-implied observations—not truth, forecasts, or executable signals—and do not use current search to reconstruct a historical snapshot. Prices and indicators require a licensed host `SourcePort`; Reddit requires host-owned approved OAuth; neither is registered by default. StockTwits is denied and unregistered. FRED and Alpha Vantage are not defaults. Use lawful host sources for the remaining market-data and social gaps, and never silently substitute fixture or replay data for live retrieval.

Build a decision-relevant source portfolio before synthesis. For a normal full-company run, attempt every applicable lane and record a coverage receipt even when a lane is unavailable:

1. **Regulator and filings:** the latest annual and quarterly filing, subsequent current reports, material exhibits, amendments, proxy, and relevant ownership or registration filings. For a non-US issuer, use its primary regulator or exchange equivalent.
2. **Issuer first-party:** the latest earnings release, investor presentation, prepared remarks or webcast materials, guidance, capital-allocation statements, product or legal announcements, and the issuer's IR archive. Treat the issuer as authoritative about what it said, not as independent validation of the claim.
3. **Financial history and market state:** point-in-time statements, at least five fiscal years and eight comparable quarters when available, the latest completed market session, liquidity/volatility, valuation history, and explicitly versioned technical calculations. If the host lacks an entitled market source, mark the lane unavailable instead of estimating prices.
4. **Independent reporting:** open attributable reporting from multiple independent publishers. Target at least three publisher domains and more when the company is controversial, event-driven, internationally exposed, or thinly covered. Do not count syndicated duplicates as independent corroboration.
5. **Industry and peers:** primary evidence from material competitors, customers, suppliers, industry bodies, regulators, or standards organizations. Use at least two justified peers when peers are decision-relevant.
6. **Macro and policy:** official central-bank, statistics-agency, trade, labor, commodity, or multilateral data that directly affects the thesis. Prefer released observations and vintages over commentary.
7. **Expectations and positioning:** entitled consensus estimates, rating changes, short interest, institutional ownership, options or fund-flow data, and lawful social evidence only when available. Keep expectations separate from reported facts and label sampling or entitlement bias.
8. **Adversarial checks:** search for restatements, auditor changes, enforcement, litigation, security incidents, executive departures, financing stress, customer concentration, accounting disagreements, and credible counter-theses.

The targets above are coverage goals, not permission to invent evidence or evade access controls. Attempt every explicit applicable route and receipt failures; never treat the first usable result as proof that a lane is fully covered. A run may complete with fewer sources only when it names the failed attempts, entitlement or availability gaps, source concentration, and decision impact. Do not count multiple URLs from the same filing, issuer site, wire story, or syndicated article as source diversity. Preserve exact duplicates, near-duplicate clusters, and conflicting values in lineage rather than silently discarding disagreement.

Apply an adaptive lookback:

- Cover structural history and at least one meaningful business cycle when available.
- Shorten the window for a young issuer or event-focused pack.
- Extend it when older evidence changes trend, cyclicality, restatement lineage, capital allocation, valuation range, catalyst, risk, conflict, or monitoring conclusions.
- Stop when older evidence no longer changes decision-relevant coverage; do not add repetitive history for volume.

For every retained source, distinguish `published_at`, `available_at`, `retrieved_at`, and `cutoff_at`. Distinguish a metric's information vintage (`as_of_at`) from its economic period (`period_end`). Never treat retrieval time alone as proof of freshness.

Open the underlying primary source or attributable reporting; never treat a search snippet, GDELT observation time, aggregator headline, or generated summary as a publication timestamp or verified evidence. Mark missing, stale, conflicting, unavailable, unverified, or entitlement-blocked evidence explicitly. Complete means declared decision-relevant coverage, not an exhaustive web guarantee.

## Respect licensing and safety

Use only sources the host is entitled to access and process. Do not bypass paywalls, CAPTCHAs, robots controls, authentication, or publisher restrictions. Reddit must use host-owned approved OAuth access; do not copy the upstream project's anonymous RSS fallback. Yahoo Finance or `yfinance` data must remain an explicit host-owned, terms-compatible market-data route rather than a credential-free default. FRED and Alpha Vantage are not credential-free defaults. Seeking Alpha and other licensed services may be referenced only through lawful host access and redistribution rights. When redistribution is prohibited, retain only permitted metadata, a locator/hash, and a limitation—never copied article or transcript bodies.

Keep facts, guidance, estimates, assumptions, inferences, theses, counterclaims, and counterevidence distinct. Ground every decision-relevant claim, preserve calculation lineage, explain peer selection, expose disagreement, and make limitations visible.

Return prototype research, not personalized financial advice. The capability must never place, simulate, approve, size for execution, submit, modify, or cancel an order.

## Preserve compatibility

Use `company-research.v2` and `host-submission.v3` only when a consumer needs the frozen 15-stage dossier profile. Its durable `company-init` / `create_company_research_run` lifecycle remains valid for those 15 stages.

Use `financial-research.v1` and `host-submission.v2` only for compatibility. The optional upstream LangGraph adapter may reproduce upstream runtime mechanics when installed and credentialed, but it is not the portable execution core. It remains available and is not yet deprecated; do not claim it can be removed until the machine-readable transition gates, saved-result migrations, scoped upstream semantic oracle, live/failure matrix, and published deprecation release are all verified.

For legacy compatibility, preserve the upstream `checkpoint_enabled` setting and upstream decision/report persistence as adapter-owned behavior; neither proves portable analytics resume. Continue to honor the legacy adaptive-history policy: ordinary coverage may target five fiscal years and eight comparable quarters before expanding or stopping by decision relevance.

Use `run_fixture` only as a credential-free synthetic compatibility proof. Treat every fixture value as test data, never as live or current company research.

Target complete observable feature and information parity across harnesses; do not require exact generated text or runtime-mechanism parity. The typed contracts are implemented, but behavioral parity and legacy-removal proof remain incomplete. Codex subagents, another harness's agents, LangGraph nodes, or one sequential host agent may implement the same declared stages. Token scheduling, checkpoints inside an LLM response, provider clients, and agent-spawn APIs remain adapter-specific.
