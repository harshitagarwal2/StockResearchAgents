# ADR 0001: Separate host execution from portable authority

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

Different harnesses provide different model, tool, credential, entitlement, agent, and interruption systems. Embedding one runtime would make the capability harness-specific and duplicate upstream TradingAgents internals.

## Decision

The research host owns model reasoning, retrieval, prompts, credentials, entitlements, source terms, native scheduling, and hard interruption. StockResearchAgents owns versioned contracts, deterministic conformance, bounded stage receipts, lifecycle state, atomic completed publication, exports, and completed read models.

The portable core never accepts provider credentials and never gains broker or order authority.

## Scope and non-goals

This decision covers Python, CLI, MCP, Codex, generic harness adapters, and the optional upstream compatibility adapter. It does not standardize how a host spawns agents or retrieves evidence.

## Consequences

- The same workflow semantics can run in multiple harnesses.
- Live research quality remains dependent on host evidence and behavior.
- Portable conformance can fail closed without owning the provider.
- No single skill file is universally executable; MCP plus versioned contracts form the portable boundary.

## Alternatives considered

- Embed LangGraph as the core runtime: rejected because it would make orchestration and persistence harness-specific.
- Copy upstream prompts/providers: rejected because adapters can call upstream without forking business logic.
- Let the browser retrieve data: rejected because it would violate credential, licensing, and authority boundaries.

## Compatibility impact

Adapters may change, but the host-submission and completed-result contracts remain versioned and portable.

## Validation evidence

See `docs/VALIDATION.md` for credential rejection, loopback-only presentation, manifest neutrality, sequential fallback, and completed-publication tests.
