# Getting started

- **Purpose:** produce and inspect one safe completed result in under five minutes.
- **Audience:** first-time users and contributors.
- **Canonical for:** the first local success path.
- **Not canonical for:** live-provider behavior or host-adapter implementation.

## Prerequisites

- Python 3.11 or newer.
- [`uv`](https://docs.astral.sh/uv/).
- No API key or provider credential is needed for the deterministic fixture.

## Run the fixture

```bash
uv sync
uv run stock-research-agents fixture --events
```

The JSON output must identify ORCL, fixture data, a completed status, a non-executable conclusion, and a
`presentation` receipt. In the default local mode, open `presentation.url`; it already points to this exact completed
run. Fixture values prove contract behavior, not current research quality.

## Open the Research Dossier Viewer

```bash
uv run stock-research-agents report --fixture
```

This foreground command remains useful for diagnostics or an explicitly selected port. Normal completed CLI and
MCP workflows ensure the shared viewer automatically and return the URL without blocking. The preferred human-facing
name is **Research Dossier Viewer**; `dashboard` remains a compatibility command.

The viewer:

- binds only to an explicit loopback address;
- reads a completed canonical projection;
- performs no retrieval, reasoning, calculation, lifecycle mutation, or order action; and
- remains empty when no completed dossier is available.

## Plan a company-analytics run

```bash
uv run stock-research-agents analytics-plan \
  --input examples/company-request.v3.json \
  --output plan.json
```

The output tells a host which 26 stages to execute, which capability IDs each stage may use, which research pack applies, and includes a self-contained bundled v4 schema with typed analytics records. It does not run models or retrieve company data. Strict Python validation remains authoritative for cross-field rules such as the `<quality_run_id>.` forecast namespace.

## Inspect MCP discovery

```bash
uv run stock-research-agents-mcp
```

An MCP client should call `discover_capability` before assuming a tool, workflow, or runtime capability exists.

## Expected safety signals

- Research mode is visibly `fixture`, `live`, or `historical_replay`.
- Investment-style output says `non_executable`.
- Missing or licensed evidence remains visible.
- No portable payload contains credentials or provider configuration.
- The viewer cannot see partial stage output.

## Troubleshooting

**The viewer shows an old run.** Open the exact `presentation.url` returned by the completed operation. The bare
viewer URL intentionally resolves the durable `current` alias. See [Operations](OPERATIONS.md#state-directory).

**`analytics-plan` rejects the example.** Run `uv sync`, verify Python 3.11+, and run the targeted tests in [Validation](VALIDATION.md).

**The plugin can plan but not retrieve live data.** That is the product boundary. The active Codex task or other host must retrieve and reason over evidence, then submit the typed result.

**The optional `research` command asks for credentials.** That command delegates to upstream TradingAgents and is outside the default credential-free plugin server.
