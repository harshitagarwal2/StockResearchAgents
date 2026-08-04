# Installed-package host adapters

These templates connect Claude Code, OpenCode, and Hermes Agent to the same
installed StockResearchAgents stdio servers. They contain transport and process
configuration only; they do not copy prompts, workflow stages, analytics,
provider logic, credentials, or research state.

Install the Python package so `stock-research-agents-mcp` and
`stock-research-data-mcp` are on the host's `PATH`, then copy or merge the
template for that host:

- `claude-code/.mcp.json`
- `opencode/opencode.json`
- `hermes/config.yaml`

`host-adapters.v1.json` is the machine-readable interface shared by the three
templates. Source checkouts use the paired `source_launcher` entries; installed
packages use `installed_command`. Both launch the same MCP modules and expose
the same tool surfaces.

The canonical host workflow remains `company-analytics.v1`, and its reusable
instructions remain in `skills/tradingagents-portable/SKILL.md`. Harnesses own
models, agents, retrieval, credentials, entitlements, and interruption.
StockResearchAgents owns contracts, deterministic validation, durable stage
boundaries, atomic completed publication, and completed-only projection.
