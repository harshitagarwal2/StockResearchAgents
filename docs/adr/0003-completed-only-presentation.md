# ADR 0003: Present completed research only

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

Partial stages may be inconsistent, contain material the host must retain privately, or fail terminal validation. Presenting them as research would confuse progress with an authoritative completed artifact.

## Decision

The browser and public completed read models expose only atomically published results. Lifecycle progress, partial stage state, host reasoning, and tool material remain in CLI/MCP or native host surfaces. The browser binds only to loopback and contains no research, provider, lifecycle, credential, or execution controls.

## Scope and non-goals

This decision governs the Research Dossier Viewer and any future completed dossier comparison or Research Quality view. It does not prevent hosts from showing their own native progress UI outside the StockResearchAgents completed-result surface.

## Consequences

- Readers know that a visible dossier passed terminal validation.
- The viewer remains simple, safe, and harness-neutral.
- Users monitor in-progress work through host/MCP lifecycle tools instead of the browser.
- Future scorecards must be completed typed projections; browser-side scoring is prohibited.

## Alternatives considered

- Stream every stage into the viewer: rejected because it exposes partial and potentially unsafe state.
- Add pause/resume controls to the viewer: rejected because presentation would gain runtime authority.
- Let JavaScript derive conclusions: rejected because the browser would become a second business-logic implementation.

## Contract impact

Presentation is exposed through the Research Dossier Viewer and completed-result endpoints only. The viewer has no partial-stage or run-control path.

## Validation evidence

Viewer and lifecycle tests prove loopback binding, path safety, completed-only visibility, and static rendering behavior.
