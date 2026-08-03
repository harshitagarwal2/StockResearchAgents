# TradingAgents Portable architecture

## Purpose

This repository is an incubation environment for consuming upstream TradingAgents research through a portable CLI/MCP boundary and presenting the completed output as a read-only dossier.

The portable layer is an adapter and projection surface, not a second TradingAgents execution engine. Complete live feature execution remains owned by upstream `TradingAgentsGraph`.

## Boundary

TradingAgents Portable owns:

- versioned run, workflow, event, evidence, decision, artifact, and dashboard contracts;
- the deterministic ORCL demonstration fixture;
- harness-neutral MCP tools and a Codex plugin/skill bundle;
- the post-run dossier projection, inline MCP view, loopback browser UI, and JSON/Markdown artifacts;
- conformance tests and the feature-parity ledger.

The main TradingAgents repository remains the source of truth for:

- production prompts and agent behavior;
- provider clients and credential precedence;
- data-vendor implementations;
- LangGraph execution, legacy checkpoints, reports, and decision memory.

The thin upstream adapter imports and calls that implementation. It must not copy or fork its business logic.

The installable `upstream` extra pins the official base commit used for conformance. A compatible checkout supplied through `TRADINGAGENTS_LEGACY_PATH` takes precedence, so an alternate branch such as PR #1195 can add a provider without changing the portable contracts. Credentials and Codex OAuth state remain owned and read by upstream; the portable layer forwards only environment-variable names and never serializes their values.

## Runtime shape

```mermaid
flowchart LR
    H["CLI or MCP client"] --> P["Portable typed request"]
    P --> F["Deterministic ORCL fixture"]
    P --> A["Thin upstream adapter"]
    A --> G["TradingAgentsGraph"]
    F --> C["Completed portable result"]
    G --> C
    C --> V["Merged read-only dossier"]
    V --> E["Inline MCP view"]
    V --> B["Loopback browser UI"]
    V --> T["JSON and Markdown artifacts"]
```

No UI projection owns workflow logic. The dossier exists only after execution completes; it is not a setup, orchestration, live-progress, cancellation, or resume surface.

## Workflow contract

For effective analysts `A`, research depth `N`, and risk depth `R`, a complete run contains:

1. each effective analyst in canonical order;
2. exactly `2 × N` alternating bull/bear research turns;
3. Research Manager;
4. Trader analytical proposal;
5. exactly `3 × R` aggressive/conservative/neutral risk turns;
6. terminal Portfolio Manager decision.

For live execution, the portable layer passes the supported non-secret request settings to upstream and projects the completed logical state. Provider behavior, data access, workflow decisions, and checkpoint mechanics remain upstream responsibilities.

## Execution modes

- **Fixture:** deterministic, credential-free, network-free ORCL run used for local proof and conformance.
- **Upstream delegation:** accepts arbitrary Yahoo-style company/instrument symbols through CLI or MCP, calls upstream `TradingAgentsGraph`, and maps completed state into portable contracts without copying business logic.
- **Host-native execution:** a declared future boundary; no host-native stage executor exists.

The fixture and fake-graph tests prove the portable contracts, delegation seam, result mapping, and post-run UI projection. They do not prove live provider credentials, data-vendor access, checkpoint resume, or successful credentialed upstream execution. Live stage streaming is unavailable because the current adapter receives completed state rather than upstream stage callbacks.

## Dashboard model

The dashboard is a completed-run dossier centered on a decision-provenance ribbon:

`evidence → analysts → research debate → manager → trader → risk debate → portfolio`

It exposes available completed-run data:

- run identity, request settings, capability/runtime provenance, and final status;
- every analyst report and every available debate turn, with aggregate role-history fallback for completed upstream state;
- Research Manager, Trader, all three risk roles, and Portfolio Manager outputs;
- structured evidence/provenance when the executor supplies it, plus the complete upstream report text otherwise;
- available source dates, providers, degradation, and diagnostics without inventing missing metadata;
- legacy reports/logs plus structured JSON, projected events, and Markdown artifacts.

It does not expose controls for configuration, launch, orchestration, live progress, cancellation, checkpoint cleanup, or resume. The HTTP API is read-only and includes the merged dossier at `GET /api/runs/{run_id}/view` and `GET /api/runs/current/view`.

Trade-like fields are always labeled `non_executable_analytical_scenario`; no projection may expose an order action.

## Incubation exit criteria

Any proposal back to the main project must distinguish verified portable behavior from runtime-unverified upstream behavior. At minimum:

- the deterministic ORCL flow completes every required stage and report section;
- the plugin and skill manifests validate;
- the exact MCP stdio command starts cleanly and tools are discoverable;
- the loopback server binds only to loopback and serves the same run/result/events/view projections;
- backend, UI-contract, security, and integration tests pass without network or secrets;
- the adapter delegates arbitrary supported symbols to `TradingAgentsGraph`, maps completed state, and fails with typed setup guidance when unavailable;
- live provider execution and checkpoint resume remain explicitly unverified until credentialed evidence exists;
- host-native execution and live upstream event streaming remain explicitly unimplemented;
- there is no broker/order execution surface;
- an independent review confirms that no business logic was duplicated from the sibling repository.

## Main-repository migration

If migration is approved, move contracts and tests first, then the thin adapter, then the post-run dossier. Preserve the main repository's CLI and public Python API. Do not replace or fork `TradingAgentsGraph`; it remains the execution authority.
