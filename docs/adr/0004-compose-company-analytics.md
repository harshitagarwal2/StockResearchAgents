# ADR 0004: Compose Company Analytics around frozen v3

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

The evidence-first v3 dossier is frozen, while richer research needs deterministic analytics, research packs, hypotheses, experiments, forecasts, and outcome scoring. Adding optional fields to v3 would weaken strict readers and couple new capabilities to an old contract.

## Decision

Introduce `company-analytics.v1` and `host-submission.v4` as an outer composition. V4 embeds one unchanged v3 submission and adds versioned analytics, run-card, hypothesis, iteration, quality, and forecast sidecars. Keep web retrieval and reasoning host-owned. Publish the complete composition atomically and expose it only through completed read models.

Use ports and adapters so Codex, generic MCP clients, a sequential host, and the optional legacy LangGraph runtime can execute equivalent workflow semantics without sharing runtime mechanics.

## Scope and non-goals

This decision defines contract composition, dependency direction, lifecycle, and publication. It does not grant provider credentials, licensed-source access, browser bypass, broker authority, or a guarantee of exhaustive/correct live research.

## Consequences

- Frozen v3 readers remain valid.
- New analytics can evolve behind explicit versions.
- Host adapters stay replaceable and credentials remain outside portable state.
- The completed viewer can merge dossier and sidecars without calculating.
- Hosts can checkpoint all 26 stages through the profile-driven durable coordinator, committing one first-incomplete stage at a time, or import one complete v4 bundle atomically.
- Completed `RunResult.artifacts` are authoritative sidecars; the quality outcome index is hidden until publish and recoverable from those artifacts without a distributed transaction.

## Alternatives

- **Widen v3:** rejected because strict frozen readers would break or silently diverge.
- **Fork the entire application:** rejected because it duplicates contracts, calculations, and fixes.
- **Make LangGraph the portable core:** rejected because node/checkpoint APIs are runtime-specific.
- **Put live retrieval inside Portable:** rejected because credentials, entitlements, terms, and browser sessions belong to the host.

## Compatibility impact

V1/v2 and v2/v3 workflows remain preserved. V4-aware readers consume sidecars; older readers may continue to consume the embedded v3 artifact through compatible projections.

## Validation evidence

Contract, conformance, CLI/MCP, profile-driven lifecycle, crash-recovery, deterministic analytics, quality-store, multi-symbol, and completed-view tests exercise the composed profile. Live-source correctness and long-horizon forecast skill remain host/evaluation proof gaps.
