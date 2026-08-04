# Glossary

- **Purpose:** keep human-facing language and strict technical identifiers unambiguous.
- **Audience:** all readers and contributors.
- **Canonical for:** terminology.
- **Not canonical for:** schema fields or compatibility status.

| Term | Exact meaning |
| --- | --- |
| StockResearchAgents | Harness-neutral capability bundle for contracts, conformance, lifecycle, publication, and completed presentation |
| Research host | Codex, another harness, or an application that owns retrieval, reasoning, credentials, entitlements, and execution |
| Company Analytics | Human name for the primary `company-analytics.v1` workflow and v4 completed composition |
| Evidence-First Company Research | Human name for the implemented `company-research.v2` capability |
| Research Request | Immutable identity, exact cutoff, research mode, objectives, and planned coverage |
| Research Run | One host-executed lifecycle instance |
| Completed Research Dossier | Immutable completed human-facing research artifact, represented by `research_dossier.v3` today |
| RunResult | Portable transport aggregate containing status, capabilities, reports, decisions, artifacts, and topology |
| RunView | Completed read model projected for MCP and the browser; not an authority for research semantics |
| Research Dossier Viewer | Human name for the completed-only browser surface; compatibility APIs still use `dashboard` |
| Coverage receipt | Terminal status for a planned evidence area: complete, partial, missing, stale, conflicting, entitlement-blocked, or not applicable |
| Research Delta | Host-declared change record retained inside a dossier |
| Research Policy | Versioned portable quality rules identified by immutable policy metadata and digest |
| Research Quality Receipt | Immutable sidecar containing policy identity, run provenance, rule results, and decision-support status |
| Forecast | Falsifiable prediction issued at a specific time with a target, horizon, and resolution rule |
| Forecast namespace | Global identity rule requiring every `forecast_id` to begin with its exact `<quality_run_id>.` prefix |
| Claim confidence | Confidence in the support for a claim; not automatically a forecast probability |
| Outcome observation | Later append-only evidence used to resolve a forecast |
| Evaluation | Deterministic comparison of a typed forecast and compatible typed outcome |
| Scorecard | Reproducible evaluation of compatible forecasts and outcomes; insufficient samples remain explicit |
| Authoritative sidecar | Completed analytics or quality artifact embedded in canonical `RunResult.artifacts`; derived indexes can be rebuilt from it |
| Research conclusion | Non-executable analytical conclusion; never an order authorization |
| Exact cutoff | Time instant after which no evidence may influence the research artifact |
| Fixture | Deterministic provider-free demonstration material; never described as current live data |
| Historical replay | Research intentionally reconstructed using only evidence available at a historical cutoff |
| Upstream adapter | Optional adapter that imports an installed upstream `TradingAgentsGraph` without copying its runtime internals |
| Research-data MCP adapter | Host-owned provider bridge that exposes a versioned tool and normalizes results through `SourcePort`; not part of the portable domain |
| Observable parity | Equality of typed stages, information, decisions, safety invariants, and report groups after normalization; never exact prose or runtime internals |
| Legacy transition gate | Machine-readable proof requirement that must be verified before the user-facing upstream executor can be removed |
| Upstream oracle | Exact pinned TradingAgents checkout used for a scoped semantic differential comparison, not factual or investment truth |

## Words to avoid

- Do not use **dashboard** in human-facing product copy when **Research Dossier Viewer** is meant.
- Do not use **report**, **result**, and **dossier** interchangeably.
- Do not use **confidence** as a synonym for probability.
- Do not use **HOLD** to hide insufficient, conflicting, or policy-blocked evidence.
- Do not use **execution**, **trade**, or **approval** for a non-executable conclusion.
