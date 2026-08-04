# Architecture poster sources

## Purpose

These standalone HTML/CSS files are canonical for the polished PNG architecture posters in `assets/architecture/`.

## Rendering

Run:

```bash
./scripts/render_architecture_posters.sh
```

The renderer uses local headless Chrome at the standard macOS application path. Override `CHROME_BIN` on another platform.

The posters are explanatory onboarding assets. Mermaid sources in `docs/diagrams/` remain the canonical diagrams-as-code for exact nodes, edges, and sequence semantics.

## Rules

- Keep a fixed 1800 × 1000 canvas for stable README rendering.
- Use the viewer's ink/paper/cobalt/aqua/amber visual language.
- Label planned capabilities explicitly.
- Never introduce provider logos, broker/order imagery, execution arrows, or partial-result paths into the viewer.
- Regenerate and visually inspect every poster after changing the source.
