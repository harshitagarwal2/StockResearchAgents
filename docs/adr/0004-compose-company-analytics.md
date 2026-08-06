# ADR 0004: Compose Company Analytics around base research

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

The evidence-first research dossier is a strict foundation, while the product also needs deterministic analytics, research packs, hypotheses, experiments, forecasts, and outcome scoring. Adding optional fields to the dossier would weaken strict readers and couple distinct responsibilities.

## Decision

Use `company-analytics.v1` as the one public product profile and `CompanyAnalyticsSubmissionV1` as its outer terminal composition. Publish one strict `CompanyAnalyticsResultV1` that retains the exact submission and seven authoritative artifacts: dossier, analytics bundle, run card, hypothesis ledger, research iterations, quality receipt, and forecast set. Keep web retrieval and reasoning caller-owned. Expose the result only through completed read models and deterministic report projections.

Use ports and adapters so Codex, generic MCP clients, native-agent runtimes, and caller-supplied sequential executors can execute equivalent workflow semantics without sharing runtime mechanics.

## Scope and non-goals

This decision defines contract composition, dependency direction, lifecycle, and publication. It does not grant provider credentials, licensed-source access, browser bypass, broker authority, or a guarantee of exhaustive/correct live research.

## Consequences

- Base research readers remain valid.
- New analytics can evolve behind explicit versions.
- Host adapters stay replaceable and credentials remain outside StockResearchAgents state.
- The completed viewer can merge dossier and sidecars without calculating.
- Hosts can checkpoint all 26 stages through the profile-driven durable coordinator, committing one first-incomplete stage at a time, or import one complete analytics bundle atomically.
- The exact `CompanyAnalyticsSubmissionV1` and seven `CompanyAnalyticsResultV1.artifacts` are authoritative; report groups, the viewer, and the quality outcome index are derived projections, with the index hidden until publish and recoverable without a distributed transaction.

## Alternatives

- **Widen research:** rejected because strict frozen readers would break or silently diverge.
- **Fork the entire application:** rejected because it duplicates contracts, calculations, and fixes.
- **Make a graph framework the StockResearchAgents core:** rejected because node/checkpoint APIs are runtime-specific.
- **Put live retrieval inside the core:** rejected because credentials, entitlements, terms, and browser sessions belong to the caller runtime.

## Contract impact

The embedded `CompanyResearchSubmissionV1` remains strict. Analytics-aware readers consume the outer sidecars, while dossier readers consume the embedded `ResearchDossierV1` projection.

## Validation evidence

Contract, validation, CLI/MCP, `run-control.v1`, crash-recovery, deterministic analytics, quality-store, multi-symbol, and completed-view tests exercise the composed profile. Live-source correctness and long-horizon forecast skill remain host/evaluation proof gaps.
