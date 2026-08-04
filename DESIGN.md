# Design

## Source of truth

- **Status:** Active
- **Last refreshed:** 2026-08-03
- **Primary product surfaces:** Python package, CLI, MCP server, Codex plugin, JSON/Markdown exports, and the Research Dossier Viewer.
- **Canonical for:** product language, user journeys, information architecture, visual language, accessibility, and completed-result interaction rules.
- **Not canonical for:** wire schemas, module ownership, persistence internals, compatibility guarantees, or test evidence.
- **Evidence reviewed:** `README.md`, `docs/ARCHITECTURE.md`, `docs/FEATURE_PARITY.md`, `docs/VALIDATION.md`, `.codex-plugin/plugin.json`, `skills/tradingagents-portable/`, `src/tradingagents_portable/web/`, workflow manifests, tests, and the upstream TradingAgents architecture renders.

## Brand

- **Personality:** forensic, calm, explicit, evidence-led, and technically rigorous.
- **Trust signals:** exact cutoffs, visible research mode, source locators, entitlement status, calculation lineage, limitations, typed validation receipts, and completed-only publication.
- **Avoid:** trading-terminal aesthetics, provider-logo collages, glossy financial charts without provenance, anthropomorphic trader imagery, execution language, fabricated precision, and green/red-only bullish/bearish semantics.

## Product goals

- **Goals:** make a completed company-research artifact understandable, auditable, portable across harnesses, and safe to inspect; let a new contributor understand the authority boundary in under five minutes.
- **Non-goals:** retrieve data inside the portable core, own model reasoning, provide financial advice, execute orders, expose credentials, or turn the browser into a research/runtime console.
- **Success signals:** users can identify what the host owns, what Portable guarantees, why a conclusion was reached, which evidence is missing, and whether the displayed artifact is completed and non-executable.

## Personas and jobs

- **Primary personas:** research reader, Codex user, harness integrator, contract implementer, maintainer/reviewer, and compliance or provenance auditor.
- **User jobs:** run a safe demo; connect a host; validate a terminal dossier; receive and open its completed page without launching a company-specific UI; inspect a completed conclusion; trace a claim to evidence; export a reproducible artifact; understand a failed or incomplete run.
- **Key contexts of use:** local development, Codex tasks, generic MCP clients, CI conformance, historical replay, and read-only review after publication.

## Information architecture

- **Primary navigation:** product promise → safe demo → choose-your-path routing → completed dossier → architecture/integration/reference material.
- **Core routes/screens:** empty viewer state, completed dossier, source/evidence appendix, lifecycle and export APIs; a future dossier comparison is a separate completed-result projection.
- **Content hierarchy in the viewer:**
  1. Research conclusion and explicit non-executable status.
  2. Evidence integrity, coverage gaps, conflicts, and limitations.
  3. Thesis and countercase.
  4. Company evidence, filings, guidance, peers, and factors.
  5. Valuation and risk.
  6. Monitoring, prior outcomes, and research changes.
  7. Method, provenance, and raw audit appendix.
- **Documentation hierarchy:** `README.md` routes tasks; this file owns product design; `docs/ARCHITECTURE.md` owns implementation structure; `docs/CONTRACTS.md` owns integration sequences; `docs/COMPATIBILITY.md` owns version mapping; `docs/VALIDATION.md` owns proof.

## Design principles

1. **Evidence before assertion.** Important conclusions expose their source, calculation, limitation, or unresolved conflict.
2. **Completed means published.** Partial lifecycle state never looks like a dossier.
3. **Plain language outside, strict identifiers inside.** Human labels clarify the product while wire IDs remain stable and versioned.
4. **Missing is a result.** Stale, conflicting, unavailable, or entitlement-blocked evidence is visible—not silently replaced.
5. **Projection is not authority.** CLI, MCP reads, and the browser render typed state; they do not invent research or scores.
6. **One viewer, explicit run identity.** Completion returns a URL pinned to the published run; later companies reuse the same application instead of generating another page or server.
- **Tradeoffs:** auditability and compatibility take precedence over compact payloads, animated UI, or a smaller number of visible limitations.

## Stable vocabulary

| Use | Meaning | Do not substitute |
| --- | --- | --- |
| StockResearchAgents | Product and capability bundle | trading app, prediction engine |
| Evidence-First Company Research | Implemented primary capability | company-research v2 in reader-facing prose |
| Completed Research Dossier | Immutable human-facing artifact | report, result, dashboard |
| Research Dossier Viewer | Completed-only read surface | live dashboard, operator console |
| Research Quality | Planned policy, forecast, outcome, and evaluation capability | confidence engine, prediction pipeline |
| Research Quality Receipt | Planned reproducibility and rule-evaluation artifact | generic evaluation receipts |
| Research conclusion | Non-executable analytical conclusion | trade, order, signal authorization |

Technical identifiers such as `company-research.v2`, `host-submission.v3`, `research_dossier.v3`, `RunView`, stage IDs, and compatibility commands remain unchanged.

## Visual language

- **Color:** ink and paper dominate. Cobalt marks references and selected paths; aqua marks verified structure; amber marks partial, stale, or conflicted state; red marks failed, missing, or prohibited state. Every color state also has text and shape treatment.
- **Typography:** editorial serif display type, highly readable sans-serif body copy, condensed utility labels, and monospace for wire identifiers, hashes, and receipts.
- **Spacing/layout rhythm:** document-like vertical rhythm; generous section separation; compact ledgers only for exact mappings.
- **Shape/radius/elevation:** restrained borders and subtle elevation; double-border documents denote immutable artifacts; diamonds are reserved for real gates.
- **Motion:** modest reveal and focus only; respect reduced motion. Architecture diagrams remain static.
- **Imagery/iconography:** evidence chains, receipts, timelines, and publication gates. Do not use broker, order, fill, or execution imagery.

## Diagram grammar

- Mermaid files in `docs/diagrams/` are canonical; SVGs in `assets/architecture/` are committed renders.
- Solid arrows carry validated or immutable data. Dashed arrows are queries, references, supersession, or host-declared relationships.
- Diagrams have meaningful alt text, internal accessible titles/descriptions, and a prose explanation immediately after the image.
- Text remains searchable; no text-to-path conversion. Meaning must survive grayscale and color-vision differences.
- Keep diagrams small enough to understand in one pass and label authority and temporal boundaries directly.

## Components

- **Existing components to reuse:** masthead receipt, status chips, report hero, decision aperture, evidence ledger, definition lists, trace legend, timeline, source cards, limitation callouts, and appendix accordions.
- **New/changed components:** canonical Research Dossier Viewer wordmark; Research Quality Receipt panel only after typed data exists; explicit insufficient/conflicted/policy-blocked states; completed dossier comparison view only after a server-side typed projection exists.
- **Variants and states:** fixture/live/historical-replay; complete/partial/missing/stale/conflicting/entitlement-blocked/not-applicable; completed/unavailable; future open/resolved/unscored/insufficient-sample states.
- **Token/component ownership:** `src/tradingagents_portable/web/styles.css` owns tokens; `index.html` owns semantics; `app.js` only renders validated `RunView` data.

## Accessibility

- **Target standard:** WCAG 2.2 AA for the viewer and documentation assets.
- **Keyboard/focus behavior:** preserve skip navigation, visible focus, logical tab order, and native disclosure behavior.
- **Contrast/readability:** text contrast at least 4.5:1 and meaningful non-text graphics at least 3:1; do not place small aqua text on white.
- **Screen-reader semantics:** semantic landmarks, labeled sections, descriptive links, diagram `<title>`/`<desc>`, and text alternatives for visual state.
- **Reduced motion and sensory considerations:** honor `prefers-reduced-motion`; never rely on animation, color, or spatial position alone.

## Responsive behavior

- **Supported breakpoints/devices:** desktop, 760 px tablet/narrow desktop, and 320 px mobile reading width.
- **Layout adaptations:** multi-column ledgers stack; long IDs wrap safely; navigation becomes horizontally scrollable or stacked; diagrams may scroll within a labeled region rather than shrink below readable type.
- **Touch/hover differences:** every hover affordance has a focus/touch equivalent; source links retain sufficiently large targets.
- **Print:** hide sticky navigation and nonessential controls, prevent clipped ledgers, retain source locators, and preserve explicit status labels.

## Interaction states

- **Loading:** neutral status with no implied research completion.
- **Empty:** explain that no completed dossier is available and that the viewer does not run research.
- **Error:** show a typed failure or unavailable state without exposing stack traces, paths, secrets, or partial dossier content.
- **Success:** return a versioned presentation receipt, then display only the selected completed canonical result with mode, cutoff, completion time, and non-executable notice.
- **Disabled:** use only for future controls; the current viewer is read-only by design.
- **Offline/slow network:** loopback reads fail explicitly and retain the empty viewer shell; no cached result is treated as current without its run identity.

## Content voice

- **Tone:** direct, precise, non-promotional, and honest about proof boundaries.
- **Terminology:** use the stable vocabulary above; reserve code identifiers for compatibility/reference sections.
- **Microcopy rules:** say what is missing and why; distinguish fixture from live; distinguish HOLD from insufficient evidence; use “non-executable” near every investment-style conclusion.
- **Prohibited labels:** guaranteed, complete market picture, prediction engine, execution, approved trade, autonomous trader, or calibrated accuracy without defined cohorts and sufficient observations.

## Implementation constraints

- **Framework/styling system:** packaged static HTML/CSS/JavaScript served by Python; no frontend framework or browser-side business logic.
- **Design-token constraints:** extend the existing CSS custom properties before adding new tokens.
- **Performance constraints:** bounded completed payloads, no external UI assets, and no required network requests after the local page loads.
- **Compatibility constraints:** strict wire schemas and compatibility commands remain stable; human-facing aliases are additive.
- **Test/screenshot expectations:** static safety, accessibility landmarks, loopback binding, completed-only visibility, responsive CSS, forced-colors, print behavior, documentation links, and diagram source/render pairs.

## Open questions

- [ ] Define the minimum resolved cohort for each future Research Quality score / quality owner / blocks scorecard claims.
- [ ] Decide whether a future completed dossier comparison is packaged in the same server or a separate read-model endpoint / architecture owner / affects viewer routing.
- [ ] Establish a cross-platform Mermaid rendering path beyond the checked-in macOS Chrome configuration / tooling owner / affects diagram regeneration only.
