# Contributing

StockResearchAgents is an incubation repository for a harness-neutral research capability. Changes must preserve the host/portable authority boundary and completed-only publication model.

## Start here

1. Read [Design](DESIGN.md) for product language and UX rules.
2. Read [Architecture](docs/ARCHITECTURE.md) for boundaries and module ownership.
3. Read [Compatibility](docs/COMPATIBILITY.md) before changing any public contract.
4. Run the safe demo in [Getting started](docs/GETTING_STARTED.md).

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run python scripts/check_docs.py
```

Prefer targeted tests while iterating, then run the complete validation set before handoff.

## Release changes

- Keep `src/tradingagents_portable/_version.py`, `.codex-plugin/plugin.json`, and `server.json` aligned for a stable release.
- Run `uv run python scripts/verify_release_metadata.py --tag v<VERSION> --require-stable` before creating a release tag.
- Follow [Releasing](docs/RELEASING.md); do not add package-index tokens, registry credentials, or live-provider credentials to the repository or workflow inputs.

## Change rules

- Keep retrieval, credentials, prompts, provider clients, entitlements, and native scheduling in the host.
- Keep browser code presentation-only.
- Never add broker, order, fill, approval, or portfolio-mutation authority.
- Never put credentials, raw provider payloads, or non-redistributable content in portable state.
- Preserve exact-cutoff and truthful research-mode semantics.
- Treat frozen schemas as frozen; introduce parallel profiles for new semantics.
- Preserve unrelated worktree changes.
- Add negative tests for credentials, unknown fields, post-cutoff evidence, unresolved references, and partial-result visibility.

## Documentation changes

- Update the canonical owner document instead of copying rules.
- Keep Mermaid sources and SVG renders in sync with `./scripts/render_architecture_diagrams.sh`.
- Use stable human-facing vocabulary from [Glossary](docs/GLOSSARY.md).
- Mark planned behavior explicitly; never present a design as implemented proof.

## Pull-request evidence

Include:

- user-visible outcome;
- changed contracts or compatibility impact;
- targeted and full verification commands;
- screenshots or diagram renders when presentation changes;
- remaining live-provider or licensed-data gaps; and
- confirmation that no executable trading authority was introduced.
