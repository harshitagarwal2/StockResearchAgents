# Contract guide

- **Purpose:** explain the minimum portable request-to-publication sequence.
- **Audience:** host implementers and reviewers.
- **Canonical for:** integration sequence and artifact responsibilities.
- **Not canonical for:** every JSON field; the checked-in schemas and strict Python models are authoritative for fields.

## Artifact sequence

```text
Research Request
  → 26-stage company-analytics plan
  → host-owned execution
  → terminal host-submission.v4
  → strict conformance
  → atomic completed publication
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

Start with `examples/company-request.v3.json`.

## Workflow plan

`analytics-plan` and `prepare_company_analytics` return the versioned execution policy plus 26 ordered stage roles, objectives, completion criteria, dependencies, capability IDs, output references, research pack, routing semantics, sequential fallback, and a self-contained bundled v4 JSON Schema with typed analytics records. Exact host prompts, concrete providers, and model names are absent. Strict Python models remain authoritative for cross-field semantics that JSON Schema cannot fully express.

The `research-data-tools.v1` manifest is authoritative for the implemented SourceBatch v1 capability matrix. It records six default public tools on the isolated server launched by `stock-research-data-mcp`, host-gated prices/indicators/Reddit, and denied-unregistered StockTwits; `tradingagents-research-data` remains the manifest compatibility key. None of these tools is registered on the coordination MCP. The separate `legacy-transition.v1` manifest remains authoritative for the blocked executor-removal gates; partial research-data coverage does not make removal eligible.

## Host-owned intermediate state

The durable analytics lifecycle accepts only safe descriptors before completion:

```text
reference_id
media_type
sha256
byte_length
bounded_summary
safe execution receipts
```

The host retains raw prompts, tool arguments, source bodies, and intermediate reasoning. A descriptor proves the referenced material existed; it does not authorize the browser to display it.

## Terminal submission

`host-submission.v4` embeds one unchanged `host-submission.v3` and adds the analytics bundle, versioned `source-lineage-crosswalk.v1`, run card, hypothesis ledger, research iterations, Research Quality Receipt, and forecast set. The schema rejects unknown fields. A completed publication must carry the canonical manifest digest and the exact ordered set of 26 completed stage receipts; a reduced fixture cannot claim terminal completion. The crosswalk is the provider-neutral inward boundary: it binds each host source-batch/observation identity and explicit digest scope to one dossier document, one analytics source/license receipt, and the run card's ordered `source_batch_ids`. Every dossier document and analytics source license must resolve exactly once, and canonical URI, SHA-256, terms URI, access, and redistribution semantics must agree. IDs and digests must resolve, timestamps must respect the cutoff model, deterministic analytics must be reproducible, and every `forecast_id` must begin with the exact `<quality_run_id>.` namespace prefix.

Durable lifecycle publication additionally records one coordinator-owned envelope and commit-receipt digest per stage in `run_card.coordinator_commitments`. The terminal envelope digest is normalized by excluding those commitments and stage-output digest values, so the binding covers the publication candidate without recursively hashing a digest into itself.

Canonical files:

- `src/tradingagents_portable/workflow/company-research.v2.json`
- `src/tradingagents_portable/workflow/host-submission.v3.schema.json`
- `src/tradingagents_portable/workflow/company-analytics.v1.json`
- `src/tradingagents_portable/workflow/host-submission.v4.schema.json`
- `src/tradingagents_portable/workflow/analytics-bundle.v1.schema.json`
- `src/tradingagents_portable/workflow/source-lineage-crosswalk.v1.schema.json`
- `src/tradingagents_portable/company_analytics_v1/source_lineage.py`
- `src/tradingagents_portable/research_contracts.py`
- `src/tradingagents_portable/research_conformance.py`

## Analytics publication

Prefer `analytics-init` or `create_company_analytics_run`, then use shared lifecycle controls across all 26 stages. The durable coordinator accepts only the current first-incomplete stage. Finalization strictly parses and validates v4, rebinds result/event report descriptors to the lifecycle `run_id`, and atomically publishes the completed `RunResult` with authoritative sidecar artifacts. It stages and publishes the quality outcome index separately, hides it until completion, and can reconstruct it from completed artifacts after a crash. This is recoverable coordination, not a distributed transaction. Call `import_company_analytics` once only when the host already has the complete payload and does not require checkpoints.

## V3 durable lifecycle

Use `company-init` or `create_company_research_run`, then the shared lifecycle operations:

```text
start → receipts → stage commit → pause/resume or cancel → finalize
```

Every mutation uses the latest optimistic revision. Resume starts at the first incomplete stage. Hard interruption of in-flight host work remains the host's responsibility.

The v3 and analytics profiles use profile-driven coordinators: v3 covers its 15 stages and analytics covers all 26 stages without duplicating the shared control protocol.

## Completed projection

Successful finalization atomically publishes the canonical `RunResult`, its events, reports, and embedded authoritative artifacts. Other indexes are hidden until their publish step and recoverable from canonical completed artifacts; no cross-store distributed transaction is claimed. `RunView` is a completed read model. The browser and report aliases render it without interpreting or recalculating dossier content.

Every completed compatibility report also carries two derived, non-authoritative audit sidecars:

- `report.provenance` lists the evidence retained by each analyst, its supplied source-date and retrieval-time ranges, and source references. It explicitly says that it is **not** a full host tool-call ledger or a claim about every retrieval attempt.
- `analysis.decision_consistency` compares only canonical structured research, trader, portfolio, and processed-signal fields. A divergence is marked `review_required`, not rewritten or rejected: a later risk/portfolio stage may legitimately change the analytical stance. The receipt never parses free-form model prose or grants execution authority.

The compatibility debate importer likewise preserves a single ordered response chain. The opening research turn may not claim to rebut an unstated opponent; the opening risk turn explicitly responds to the trader proposal, and later turns identify the immediately preceding speaker. This prevents a host from presenting a fabricated debate lineage as completed evidence.

## Contract evolution

Frozen contracts are semantically frozen, including optional fields. New semantics use parallel profiles and artifact kinds. See [Compatibility](COMPATIBILITY.md).
