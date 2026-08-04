# ADR 0005: Host-native core and gated legacy retirement

- **Status:** Accepted
- **Date:** 2026-08-03

## Context

The portable contracts, lifecycle, publication, memory, exports, and completed viewer no longer require LangGraph. However, concrete research-data MCP adapters, behavioral upstream conformance, representative live evidence, saved-result migrations, and a published deprecation cycle are incomplete. Removing the opt-in upstream executor now would make parity less measurable and could strand compatibility users.

## Decision

Make the host-native portable core the target product architecture. Codex, generic full/compatible hosts, the sequential fallback, and tools-only MCP clients remain thin adapters. Concrete research-data MCP implementations live in host-adapter packages and normalize through a versioned `SourcePort`; provider SDKs and credentials do not enter the portable domain.

Retain the optional upstream executor until every machine-readable transition gate passes. Then remove only its user-facing execution surfaces at a later major version, after one published deprecation release. Preserve frozen schemas, readers, historical artifacts, and copy-on-write migrations. Keep the exact upstream pin as a scoped development/CI semantic oracle rather than a normal runtime dependency.

## Consequences

- Current legacy removal and behavioral-parity claims are blocked.
- Declared data capabilities are not described as concrete MCP tools until an adapter is registered and tested.
- Upstream comparisons use typed observable semantics, never exact text or runtime internals.
- Saved-result migration becomes a hard compatibility requirement.
- A paper exchange, if created, uses a separate package, namespace, and state store.

## Alternatives

- **Delete legacy immediately:** rejected because it removes the comparison path before replacement proof and migration exist.
- **Keep legacy forever:** rejected because the target product should not require LangGraph once observable parity is proven.
- **Put provider clients in the portable core:** rejected because it violates dependency inversion and host ownership of credentials, entitlement, and sessions.
- **Compare exact generated text:** rejected because it couples conformance to models, prompts, token scheduling, and runtime mechanics.

## Evidence required before transition

See [Legacy executor transition](../LEGACY_TRANSITION.md), [Research-data MCP adapters](../RESEARCH_DATA_MCP.md), and their machine-readable manifests. No single fixture, Codex run, or upstream commit identity is sufficient.
