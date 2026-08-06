# Contract guide

- **Purpose:** explain the minimum StockResearchAgents request-to-publication sequence.
- **Audience:** host implementers and reviewers.
- **Canonical for:** integration sequence and artifact responsibilities.
- **Not canonical for:** every JSON field; the checked-in schemas and strict Python models are authoritative for fields.

## Artifact sequence

```text
Research Request
  → 26-stage company-analytics plan
  → caller-owned execution
  → terminal CompanyAnalyticsSubmissionV1
  → strict validation
  → atomic CompanyAnalyticsResultV1 publication
  → RunView / JSON / Markdown / Research Dossier Viewer
```

## Research Request

`CompanyResearchRequest` freezes:

- request identity and exact timestamps;
- truthful `live`, `fixture`, or `historical_replay` mode;
- typed instrument identity;
- objectives, coverage dimensions, history windows, latest-data checks, and stop conditions;
- output language; and
- optional sanitized, non-executable portfolio context.

Start with `examples/company-request.v1.json`.

## Workflow plan

`analytics-plan` and `prepare_company_analytics` return the versioned execution policy plus 26 ordered stage roles, objectives, completion criteria, dependencies, capability IDs, output references, research pack, routing semantics, sequential fallback, and a self-contained bundled analytics JSON Schema with typed analytics records. Exact caller prompts, concrete providers, and model names are absent. Strict Python models remain authoritative for cross-field semantics that JSON Schema cannot fully express.

The two MCP servers are intentionally separate. The coordination MCP exposes Company Analytics planning, `run-control.v1`, terminal validation, publication, and completed-result reads; it exposes no research-data tools. The `research-data-tools.v1` manifest is authoritative for the isolated `stock-research-data-mcp` SourceBatch v1 capability matrix: three SEC tools, two GDELT tools, World Bank macro, and Polymarket Gamma public search/read-only `prediction_markets` metadata. Gamma exposes no wallet, CLOB, or order endpoint; its probabilities are current market-implied observations, not truth, forecasts, or executable signals, and current search cannot reconstruct a historical snapshot. The manifest also records caller-gated prices/indicators/Reddit and denied-unregistered StockTwits; Yahoo Finance/`yfinance` remains caller-owned and terms-permitting, approved OAuth is required for Reddit, and FRED and Alpha Vantage are not defaults.

## Caller-owned intermediate state

The durable analytics lifecycle accepts only safe descriptors before completion:

```text
reference_id
media_type
sha256
byte_length
bounded_summary
safe execution receipts
```

The caller runtime retains raw prompts, tool arguments, source bodies, and intermediate reasoning. A descriptor proves the referenced material existed; it does not authorize the browser to display it.

## Terminal submission

`CompanyAnalyticsSubmissionV1` embeds one `CompanyResearchSubmissionV1`, whose terminal artifact is `ResearchDossierV1`, and adds the analytics bundle, versioned `source-lineage-crosswalk.v1`, run card, hypothesis ledger, research iterations, Research Quality Receipt, and forecast set. The schema rejects unknown fields. A completed publication must carry the canonical manifest digest and the exact ordered set of 26 completed stage receipts; the test-only ORCL fixture cannot claim a live terminal submission. The crosswalk is the provider-neutral inward boundary: it binds each caller source-batch/observation identity and explicit digest scope to one dossier document, one analytics source/license receipt, and the run card's ordered `source_batch_ids`. Every dossier document and analytics source license must resolve exactly once, and canonical URI, SHA-256, terms URI, access, and redistribution semantics must agree. IDs and digests must resolve, timestamps must respect the cutoff model, deterministic analytics must be reproducible, and every `forecast_id` must begin with the exact `<quality_run_id>.` namespace prefix.

Durable lifecycle publication additionally records one coordinator-owned envelope and commit-receipt digest per stage in `run_card.coordinator_commitments`. The terminal envelope digest is normalized by excluding those commitments and stage-output digest values, so the binding covers the publication candidate without recursively hashing a digest into itself.

The completed public value is `CompanyAnalyticsResultV1`. It retains the exact parsed `CompanyAnalyticsSubmissionV1` and the publisher's seven authoritative artifacts:

1. `research_dossier.v1`
2. `analytics_bundle.v1`
3. `run_card.v1`
4. `hypothesis_ledger.v1`
5. `research_iterations.v1`
6. `research_quality.v1`
7. `forecast_set.v1`

Canonical files:

- `src/stock_research_agents/workflow/company-research.v1.json`
- `src/stock_research_agents/workflow/company-research-submission.v1.schema.json`
- `src/stock_research_agents/workflow/company-analytics.v1.json`
- `src/stock_research_agents/workflow/company-analytics-submission.v1.schema.json`
- `src/stock_research_agents/workflow/analytics-bundle.v1.schema.json`
- `src/stock_research_agents/workflow/source-lineage-crosswalk.v1.schema.json`
- `src/stock_research_agents/company_analytics_v1/source_lineage.py`
- `src/stock_research_agents/research_contracts.py`
- `src/stock_research_agents/research_conformance.py`

## Analytics publication

Prefer `analytics-init` or `create_company_analytics_run`, then use shared lifecycle controls across all 26 stages. The durable coordinator accepts only the current first-incomplete stage. The `sequential` runner reports `executor_required` and requires a caller-supplied `LifecycleStageExecutor` to perform each stage. Finalization strictly parses and validates analytics, preserves the canonical content-derived `CompanyAnalyticsResultV1.run_id`, and atomically publishes the result with its seven authoritative artifacts. The durable lifecycle `run_id` remains a separate control handle; completed control state exposes the canonical alias as `result_run_id`. The coordinator stages and publishes the quality outcome index separately, hides it until completion, and can reconstruct it from completed artifacts after a crash. This is recoverable coordination, not a distributed transaction. Call `import_company_analytics` once only when the caller already has the complete payload and does not require checkpoints.

## Durable lifecycle

Use `analytics-init` or `create_company_analytics_run`, then the `run-control.v1` lifecycle operations:

```text
start → receipts → stage commit → pause/resume or cancel → finalize
```

Every mutation uses the latest optimistic revision. Resume starts at the first incomplete stage. Hard interruption of in-flight work remains the caller runtime's responsibility.

The coordinator covers all 26 Company Analytics stages; stages 1–15 produce the embedded research foundation without exposing a second public lifecycle.

## Completed projection

Successful finalization atomically publishes the canonical `CompanyAnalyticsResultV1` and its events. Other indexes are hidden until their publish step and recoverable from the seven canonical artifacts; no cross-store distributed transaction is claimed. `RunView` is a completed read model. The browser and report endpoints project the result without interpreting or recalculating dossier content.

`build_report_artifacts` deterministically derives five non-authoritative report groups from the completed result: **Executive Summary**, **Evidence and Claims**, **Analytics and Valuation**, **Risks and Counterevidence**, and **Monitoring and Quality**. It also derives retained-source provenance, a complete Markdown report, and structured result/event descriptors. These projections may be rebuilt; they are not members of the seven authoritative result artifacts.

## Contract evolution

Strict contracts do not gain fields in place, including optional fields. New semantics use new schema or artifact versions. See the [active contract set](COMPATIBILITY.md).
