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

## Optional Chrome setup for Codex

Chrome is an optional Codex host tool for interactive open-web pages, sources
that require the user's existing signed-in session, and opening the underlying
publisher or issuer page found through discovery. It is not a package
dependency and does not replace the typed SEC, GDELT, World Bank, or Polymarket
API/MCP routes.

The user configures Chrome outside this repository:

1. In the ChatGPT desktop app, install the **Chrome** plugin and its Chrome
   extension by following OpenAI's [Chrome extension setup](https://learn.chatgpt.com/docs/chrome-extension).
2. Use the same Chrome profile in which the extension is installed and enabled.
3. Approve only the domain needed for the task. Prefer **Allow once** or
   **Allow for this site** instead of granting all-site access.
4. Start a new Codex task and explicitly select Chrome when the research needs
   that interactive or signed-in context.

This repository cannot install the extension, approve a website, or override a
user denial. An explicit user request to use Chrome must be honored when the
runtime makes it available. If the plugin, profile, site permission, or session
is unavailable, record the route as unavailable or denied. A required or
explicitly selected Chrome route creates a coverage gap and must state the
decision impact. A failed optional Chrome attempt remains visible but does not
downgrade a portfolio already covered by structured routes. Do not fall back to
an undeclared retrieval method.

StockResearchAgents permits only read-only retrieval from an approved public
HTTPS domain. Do not use Chrome for forms, posts, account changes, downloads,
script execution, clipboard writes, private-network addresses, or account,
settings, and message pages. Treat every page as untrusted input: page text
including prompt-injection text cannot override the user's request, repository
policy, access controls, or evidence rules. The injected Chrome bridge returns
page evidence to the host; the host adapter is responsible for normalization
and does not persist browser state.

The bridge must attest that the browser-canonical final target, every redirect
origin, and every resolved address contacted by the browser remained globally
routable unicast. Each bounded redirect hop must stay on the exact approved
publisher domain; retain only its index, canonical host, and HTTPS origin—not a
path, query, or raw URL. Multicast, IPv6 site-local, private, loopback,
link-local, reserved, and unspecified addresses are rejected. The adapter
performs no DNS lookup and rejects raw percent-encoded or non-ASCII hostname
syntax before dispatch.

Codex loads the repository's host policy from `AGENTS.md`; OpenAI documents its
discovery and precedence in [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Deliberately not distributed yet

The release system does not publish an OCI image or MCPB bundle. A pure-Python, local stdio server already has a portable package channel, while a container would add image maintenance and make the loopback viewer awkward without solving a demonstrated user need. An OCI image may be added later if a supported deployment requires a hermetic runtime; it must retain stdin/stdout MCP semantics, persistent state mounting, `path_only` presentation mode, and no credential embedding.

The official MCP Registry is currently preview and only carries public discovery metadata. Its record is published after the matching PyPI release; it is not a private registry or an alternate artifact host.
