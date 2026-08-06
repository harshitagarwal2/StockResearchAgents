# ADR 0002: Evolve strict contracts through versioned composition

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

StockResearchAgents models reject unknown fields. Adding even optional fields to a strict schema can break readers and silently change semantics across harnesses.

## Decision

Strict contracts do not gain fields in place. New semantics use new schema or artifact versions. The public `company-analytics.v1` profile composes `CompanyAnalyticsSubmissionV1` around the embedded `CompanyResearchSubmissionV1` / `ResearchDossierV1` foundation. Human-facing language never renames wire identifiers.

## Scope and non-goals

This decision covers `company-analytics.v1`, its embedded `company-research.v1` foundation, `run-control.v1`, and quality artifacts. The deterministic ORCL fixture remains test-only and outside public profile discovery. Documentation-only wording does not require a new contract version.

## Consequences

- Existing strict readers continue to work unchanged.
- New artifact versions require explicit projections and validation tests.
- Version maps are more visible but avoid hidden reinterpretation.
- Research Quality remains a typed outer sidecar rather than fields added to `ResearchDossierV1`.

## Alternatives considered

- Add optional fields to research: rejected because strict readers reject unknown content and semantics would drift.
- Add a second public profile for the research foundation: rejected because it would split one product contract into competing entry points.
- Use an untyped extension dictionary: rejected because it weakens validation and transport-neutrality.

## Contract impact

`docs/COMPATIBILITY.md` records the active contract graph. Discovery advertises `company-analytics.v1` as the one public product profile.

## Validation evidence

Schema tests reject unknown fields and discovery tests assert the single public Company Analytics profile plus its embedded foundation.
