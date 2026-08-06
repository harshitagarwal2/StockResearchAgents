# ADR 0001: Separate caller execution from core authority

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

Different harnesses provide different model, tool, credential, entitlement, agent, and interruption systems. Embedding one runtime would make the capability harness-specific and couple the contracts to that runtime's internals.

## Decision

The caller runtime owns model reasoning, retrieval, prompts, credentials, entitlements, source terms, native scheduling, and hard interruption. The StockResearchAgents core owns versioned contracts, deterministic validation, bounded stage receipts, lifecycle state, atomic completed publication, exports, and completed read models.

The StockResearchAgents core never accepts provider credentials and never gains broker or order authority.

## Scope and non-goals

This decision covers Python, CLI, MCP, Codex, and generic harness adapters. It does not standardize how a caller runtime spawns agents or retrieves evidence.

## Consequences

- The same workflow semantics can run in multiple harnesses.
- Live research quality remains dependent on caller evidence and behavior.
- Core validation can fail closed without owning the provider.
- No single skill file is universally executable; the coordination MCP plus versioned contracts form the cross-harness boundary.

## Alternatives considered

- Embed a specific graph runtime as the core: rejected because it would make orchestration and persistence harness-specific.
- Bundle model prompts and provider clients: rejected because caller adapters own those mechanisms.
- Let the browser retrieve data: rejected because it would violate credential, licensing, and authority boundaries.

## Contract impact

Adapters may change, but `CompanyAnalyticsSubmissionV1` and the completed-result contracts remain versioned and transport-neutral.

## Validation evidence

See `docs/VALIDATION.md` for credential rejection, loopback-only presentation, manifest neutrality, sequential fallback, and completed-publication tests.
