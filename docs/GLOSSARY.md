# Glossary

- **Purpose:** keep human-facing language and strict technical identifiers unambiguous.
- **Audience:** all readers and contributors.
- **Canonical for:** terminology.
- **Not canonical for:** schema fields or contract status.

| Term | Exact meaning |
| --- | --- |
| StockResearchAgents | Harness-neutral capability bundle for contracts, validation, lifecycle, publication, and completed presentation |
| Caller runtime | Codex, another harness, or an application that owns retrieval, reasoning, credentials, entitlements, and execution |
| Company Analytics | Human name for the one public `company-analytics.v1` product profile |
| Evidence-First Company Research | Human name for the embedded `company-research.v1` dossier foundation |
| Research Request | Immutable identity, exact cutoff, research mode, objectives, and planned coverage |
| Research Run | One caller-executed lifecycle instance |
| Completed Research Dossier | Immutable completed human-facing research artifact, represented by `research_dossier.v1` today |
| CompanyAnalyticsResultV1 | Strict completed publication containing the exact `CompanyAnalyticsSubmissionV1`, seven authoritative artifacts, canonical content-derived result ID, timestamps, warnings, and non-executable status |
| Lifecycle run ID | Durable `run-control.v1` handle created before execution; distinct from the canonical completed result ID |
| Result run ID | Canonical `CompanyAnalyticsResultV1.run_id`; exposed after durable completion as `control.result_run_id` |
| RunView | Completed read model projected for MCP and the browser; not an authority for research semantics |
| Research Dossier Viewer | Completed-results-only browser surface with no research or lifecycle controls |
| Coverage receipt | Terminal status for a planned evidence area: complete, partial, missing, stale, conflicting, entitlement-blocked, or not applicable |
| Research Delta | Host-declared change record retained inside a dossier |
| Research Policy | Versioned quality rules identified by immutable policy metadata and digest |
| Research Quality Receipt | Immutable sidecar containing policy identity, run provenance, rule results, and decision-support status |
| Forecast | Falsifiable prediction issued at a specific time with a target, horizon, and resolution rule |
| Forecast namespace | Global identity rule requiring every `forecast_id` to begin with its exact `<quality_run_id>.` prefix |
| Claim confidence | Confidence in the support for a claim; not automatically a forecast probability |
| Outcome observation | Later append-only evidence used to resolve a forecast |
| Evaluation | Deterministic comparison of a typed forecast and type-matched outcome |
| Scorecard | Reproducible evaluation of type-matched forecasts and outcomes; insufficient samples remain explicit |
| Authoritative artifact | One of the seven completed artifacts embedded in canonical `CompanyAnalyticsResultV1.artifacts`; derived indexes and report projections can be rebuilt from them |
| Research conclusion | Non-executable analytical conclusion; never an order authorization |
| Exact cutoff | Time instant after which no evidence may influence the research artifact |
| Fixture | Deterministic provider-free test material; never a public profile or current live data |
| Historical replay | Research intentionally reconstructed using only evidence available at a historical cutoff |
| Research-data MCP adapter | Caller-owned provider bridge that exposes a versioned tool and normalizes results through `SourcePort`; separate from the StockResearchAgents coordination core |
| Runtime consistency | Equality of typed stages, terminal information, safety invariants, and report groups after normalization; never exact prose or runtime mechanics |

## Words to avoid

- Use **Research Dossier Viewer** for the completed-results-only browser surface.
- Do not use **report**, **result**, and **dossier** interchangeably.
- Do not use **confidence** as a synonym for probability.
- Do not use **HOLD** to hide insufficient, conflicting, or policy-blocked evidence.
- Do not use **execution**, **trade**, or **approval** for a non-executable conclusion.
