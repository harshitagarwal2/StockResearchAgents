# ADR 0007: Separate StockResearchAgents branding from frozen compatibility identities

- **Status:** Accepted
- **Date:** 2026-08-04
- **Decision owners:** StockResearchAgents maintainers

## Context

The independent portable repository was originally exposed as TradingAgents Portable while its contracts, Python imports, commands, state paths, plugin identity, workflow hashes, and saved artifacts accumulated compatibility obligations. Renaming every matching string would change canonical workflow digests, break persisted readers, create duplicate MCP servers, and invalidate the legacy-removal inventory.

The repository also retains an optional adapter to TauricResearch/TradingAgents. That adapter is useful for observable conformance, but upstream LangGraph mechanics and business logic are not the portable core.

## Decision

Adopt `StockResearchAgents` as the public repository, documentation, UI, plugin display, executable alias, and contributor brand.

Use additive preferred commands:

- `stock-research-agents`;
- `stock-research-agents-mcp`; and
- `stock-research-data-mcp`.

Retain the existing distribution name, Python imports, plugin/skill machine identity, MCP server keys, environment fallbacks, state paths, schema IDs, workflow IDs and hashes, media types, artifact kinds, serialization markers, migrations, and old command aliases for compatibility. Do not register duplicate branded MCP server keys. Do not add a second alias for the legacy MCP while its exact inventory is frozen.

Keep TauricResearch/TradingAgents intact and external. CI checks out the exact pinned revision in a clean temporary path for conformance. A dirty sibling clone is a development workspace, not proof. The optional adapter may call upstream; the portable core must not copy or vendor upstream workflow business logic.

## Scope and non-goals

This ADR changes product branding and additive entry points. It does not:

- claim complete live-provider or feature-parity proof;
- authorize removal of any legacy surface;
- change a frozen wire or persistence identity;
- merge local divergent Git history automatically;
- make the upstream checkout a production dependency; or
- narrow the underlying security-research contracts even though the product name is equity-first.

## Consequences

- Users see one StockResearchAgents product and completed viewer.
- Existing scripts, saved results, state, Codex invocation, MCP configurations, and imports continue to work.
- Some technical names continue to contain `tradingagents-portable`; documentation labels them as compatibility identities rather than unfinished branding.
- Repository and plugin-release tooling must validate both preferred and compatibility surfaces.
- A later technical-identity cleanup requires an explicit major-version migration, not a cosmetic edit.

## Alternatives considered

### Rename every identifier in place

Rejected because it would break saved data, hashes, imports, installed plugins, and the transition verifier.

### Keep the old public name

Rejected because it obscures the independent product boundary and the requested repository identity.

### Vendor upstream TradingAgents

Rejected because it duplicates business logic, couples the portable core to LangGraph/provider internals, and weakens clean-room conformance.

## Compatibility impact

The compatibility matrix in `docs/COMPATIBILITY.md` is authoritative. The legacy inventory in `workflow/legacy-transition.v1.json` remains unchanged and removal remains blocked until every signed gate passes.

## Validation evidence

- Plugin and skill validators pass after the display rename.
- New CLI aliases launch the existing implementation.
- Legacy-removal verification remains inventory-valid and reports `removal_allowed: false`.
- CI and the optional dependency resolve the same exact upstream revision.
- Full tests, documentation checks, architecture rendering, lint, format, and type checks cover the renamed surfaces.
