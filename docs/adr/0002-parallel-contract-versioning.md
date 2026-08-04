# ADR 0002: Evolve strict contracts through parallel profiles

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

Portable models reject unknown fields. Adding even optional fields to a frozen schema can break strict readers and silently change semantics across harnesses.

## Decision

Frozen contracts are semantically frozen. New semantics use parallel workflow profiles, terminal schemas, and artifact kinds. Discovery advertises compatibility explicitly. Human-facing aliases may improve language but never rename wire identifiers.

## Scope and non-goals

This decision covers `financial-research.v1`, `host-submission.v2`, `run-lifecycle.v1`, `company-research.v2`, `host-submission.v3`, and future quality artifacts. It does not require a new version for documentation-only wording.

## Consequences

- Existing consumers continue to work unchanged.
- New profiles require explicit projections and conformance tests.
- Version maps are more visible but avoid hidden reinterpretation.
- Future Research Quality data must be a parallel sidecar rather than fields added to `research_dossier.v3`.

## Alternatives considered

- Add optional fields to v3: rejected because strict readers reject unknown content and semantics would drift.
- Replace old profiles immediately: rejected because compatibility evidence and migrations would be insufficient.
- Use an untyped extension dictionary: rejected because it weakens conformance and portability.

## Compatibility impact

`docs/COMPATIBILITY.md` is the canonical version map. Old profiles remain discoverable until an explicit major-version removal decision.

## Validation evidence

Schema tests reject unknown fields and discovery tests retain both compatibility and company-research profiles.
