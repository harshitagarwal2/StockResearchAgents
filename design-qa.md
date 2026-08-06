# Design QA — architecture diagrams

## Comparison target

- **Source visual truth:** unavailable. No Figma board, mockup, or other source design was available in this session. The existing `system-context.svg` was inspected only as a repository visual-language reference; it is not an equivalent target for the newly added flows.
- **Implementation renders:** all seven checked-in architecture diagrams, each with Mermaid source plus generated SVG and PNG assets.
- **Capture:** the generated PNG previews were inspected directly at native dimensions; each preview is also linked to its full-size SVG in `docs/diagrams/README.md`.
- **Viewport and density:** static diagram assets; no browser CSS viewport or device scale factor applies. The PNGs are generated at 2x scale for readable GitHub previews, but no same-state source target exists for pixel-level comparison.

## Full-view evidence

All seven diagrams render as parseable SVGs and PNGs and use the existing technical-diagram grammar: cobalt for contracts/gates, aqua for validated or durable state, amber for host-owned work, red for rejected or incomplete state, double borders for completed artifacts, and dashed arrows for non-authoritative relationships.

Focused-region comparison was not performed because there is no equivalent visual target for either the source-to-dossier or lifecycle flow. The capture confirms that labels, state shapes, arrows, and color semantics are visible; it cannot establish Figma-level visual fidelity.

## Findings

- [P1] No visual source target is available.
  - Location: architecture-diagram design QA.
  - Evidence: Product Design context preflight found no saved reference or approved Figma architecture board for a pixel-level comparison.
  - Impact: a fidelity comparison cannot be made; visual consistency is assessed only against the repository's documented diagram grammar.
  - Fix: provide a Figma board or approved diagram mockup, then recapture both the board and the rendered SVGs at matched dimensions for a comparison iteration.

## Required fidelity surfaces

- **Fonts and typography:** inherited Avenir Next / Segoe UI / sans-serif stack is visible in the rendered SVGs; no source target exists to verify exact weight, line height, or wrapping.
- **Spacing and layout rhythm:** the flows use stacked or vertical layouts where practical so labels remain readable in GitHub's content column; the lifecycle flow was simplified to reduce cross-flow ambiguity. No source target exists for pixel-level spacing comparison.
- **Colors and visual tokens:** all implementation colors use the checked-in Mermaid grammar; no source token sheet or Figma styles are available to compare.
- **Image quality and asset fidelity:** each diagram has a white-background SVG and a 2x PNG fallback; neither format uses external imagery, logos, or substitute assets.
- **Copy and content:** labels were reviewed against the architecture’s authority, lifecycle, and completed-only invariants.

## Implementation checklist

1. Add an editable Figma architecture board or an approved diagram mockup.
2. Capture the selected board and both SVG renders at matched dimensions.
3. Re-run design QA with a side-by-side visual comparison and resolve any P0–P2 findings.

## Comparison history

1. Initial lifecycle render had overly dispersed recovery paths; its Mermaid layout was simplified before final capture.
2. GitHub iteration added white backgrounds, PNG preview links to full SVGs, responsive SVG metadata, top-level font configuration, and narrower stacked layouts.
3. Final capture confirms that all seven SVG/PNG pairs render and documentation validation passes, but pixel-level design fidelity remains blocked on the missing source target.

final result: blocked
