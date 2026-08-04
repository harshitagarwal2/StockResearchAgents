# Architecture diagram sources

## Purpose

This directory is canonical for the Mermaid sources behind the rendered architecture diagrams in `assets/architecture/`.

## Rendering

Run:

```bash
./scripts/render_architecture_diagrams.sh
```

The script pins Mermaid CLI so the repository does not gain a Node runtime dependency. Commit both the `.mmd` source and regenerated `.svg` output in the same change.

The checked-in Puppeteer configuration uses the standard macOS Google Chrome path. On another platform, override `executablePath` locally or use Mermaid CLI's bundled browser installation before rendering.

## Diagram grammar

- Solid arrows carry immutable or validated data.
- Dashed arrows are queries, references, or host-declared relationships.
- Double-bordered nodes are completed immutable artifacts.
- Diamonds are real validation or publication gates.
- Cobalt identifies interfaces, aqua verified state, amber incomplete state, and red rejected or prohibited state.
- Labels, shapes, and line styles carry meaning; color never stands alone.

Every source must include `accTitle` and `accDescr`. Every rendered diagram must be followed by a textual explanation in its owning document.
