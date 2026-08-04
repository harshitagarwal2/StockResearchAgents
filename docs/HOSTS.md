# Harnesses and installation

- **Purpose:** provide one install and MCP-launch path for any compatible host without coupling the portable core to a particular agent product.
- **Audience:** end users, host integrators, and release owners.
- **Canonical for:** distribution channels and host launch adapters.
- **Not canonical for:** portable workflow contracts or host-provider responsibilities.

## Choose an installation path

| Need | Supported path | Stability boundary |
| --- | --- | --- |
| Normal CLI or MCP use | PyPI package through `uv tool`, `pipx`, or `pip` | Pin an exact released version. |
| A reproducible source review | Git installation at a full release tag or commit SHA | Never use a moving branch for a durable integration. |
| Inspect release artifacts | GitHub Release wheel, source distribution, and `SHA256SUMS` | Verify the checksum before manual installation. |
| Develop or adapt the host | Source checkout plus `uv sync` | The root host configs launch this checkout. |
| Validate a pre-release | TestPyPI workflow | Not a normal user installation channel. |
| Discover the primary coordination MCP | Official MCP Registry entry | Discovery metadata only; the artifact still comes from PyPI. |

After a version is published, install the CLI with one of these commands:

```bash
uv tool install "tradingagents-portable==<VERSION>"
# or
pipx install "tradingagents-portable==<VERSION>"
# or, for an application environment
python -m pip install "tradingagents-portable==<VERSION>"
```

The preferred commands are `stock-research-agents`, `stock-research-agents-mcp`, and `stock-research-data-mcp`. The older `tradingagents-portable*` commands remain compatibility aliases; see [Compatibility](COMPATIBILITY.md).

For a reviewable direct-Git installation, pin a release tag or full commit:

```bash
python -m pip install "tradingagents-portable @ git+https://github.com/harshitagarwal2/StockResearchAgents.git@v<VERSION>"
```

## MCP from an installed package

Any stdio MCP client can run the coordination server with `uvx`:

```bash
uvx --from "tradingagents-portable==<VERSION>" stock-research-agents-mcp
```

After a normal Python installation, the equivalent is:

```bash
python -m tradingagents_portable.mcp_server
```

For a remote or headless host, set `STOCKRESEARCHAGENTS_PRESENTATION_MODE=path_only`. The viewer is intentionally loopback-only; share completed JSON/Markdown exports rather than attempting to expose its local URL.

## Source-checkout host adapters

The checked-in adapters intentionally contain no research workflow logic. They call the same CWD-independent launchers, which execute the portable stdio servers from a source checkout.

| Host | Checked-in adapter | What the user does |
| --- | --- | --- |
| Claude Code | [`.mcp.json`](../.mcp.json) and [`CLAUDE.md`](../CLAUDE.md) | Approve the project MCP servers. |
| OpenCode | [`opencode.json`](../opencode.json) | Open the repository; OpenCode loads project configuration from its root. |
| Hermes Agent | [Hermes YAML template](HERMES_MCP_CONFIG.yaml) | Merge the template into `~/.hermes/config.yaml` with an absolute repository path. |
| Other MCP client | [`scripts/run-stock-research-mcp`](../scripts/run-stock-research-mcp) | Configure the client to run the launcher or use the installed-package command above. |

Claude Code documents project `.mcp.json` servers and project skills; OpenCode documents root `opencode.json` local MCP servers; Hermes documents user-level `mcp_servers` configuration. These formats are adapters only. The host still owns model choice, agents, retrieval, credentials, entitlements, prompts, and scheduling.

## Deliberately not distributed yet

The release system does not publish an OCI image or MCPB bundle. A pure-Python, local stdio server already has a portable package channel, while a container would add image maintenance and make the loopback viewer awkward without solving a demonstrated user need. An OCI image may be added later if a supported deployment requires a hermetic runtime; it must retain stdin/stdout MCP semantics, persistent state mounting, `path_only` presentation mode, and no credential embedding.

The official MCP Registry is currently preview and only carries public discovery metadata. Its record is published after the matching PyPI release; it is not a private registry or an alternate artifact host.
