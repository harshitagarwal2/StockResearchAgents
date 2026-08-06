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
instructions remain in `skills/stock-research-agents/SKILL.md`. Harnesses own
models, agents, retrieval, credentials, entitlements, and interruption.
StockResearchAgents owns contracts, deterministic validation, durable stage
boundaries, atomic completed publication, and completed-only projection.

These templates do not install, enable, force, or approve the optional Codex
Chrome integration. A user may select an injected, host-controlled Chrome
bridge for read-only interactive research on an approved public HTTPS domain,
including a signed-in source gap or an underlying publisher page. Chrome-for-all
routing is prohibited: typed SEC, GDELT, World Bank, and Polymarket API/MCP
routes remain preferred. The host adapter—not Chrome—normalizes retained page
evidence into StockResearchAgents receipts. If Chrome is unavailable or access is denied,
the host records the attempt; it becomes a coverage gap only when Chrome was
required or explicitly selected. See [Harness
integration](../docs/INTEGRATION.md#optional-codex-adapter).
