# Harness integration

- **Purpose:** explain how Codex, MCP clients, Python applications, and other harnesses consume the same portable capability.
- **Audience:** plugin users and host-adapter implementers.
- **Canonical for:** adapter modes and host responsibilities.
- **Not canonical for:** wire-field definitions or persistence internals.

## Integration principle

The host owns retrieval and reasoning. StockResearchAgents owns the portable boundary: contracts, conformance, lifecycle, publication, exports, and completed projections.

No adapter may move credentials, provider configuration, raw prompts, unrestricted tool arguments, or copyrighted source bodies into portable state.

The primary plan supplies `stage-instructions.v1`: stable roles, objectives, and completion criteria are portable semantics, while exact prompt wording and runtime scheduling remain adapter-owned. A compatible host may pass each returned stage and context to `run_sequential_company_lifecycle`; a full host may map the same stage contracts to native agents or tasks.

## Capability modes

| Mode | Host capability | Portable behavior |
| --- | --- | --- |
| Full | Native subagents, parallel tools, structured output | Adapter required: Portable defines the contract, while the host must supply and verify native-agent execution |
| Compatible | One agent plus tools | Locally ready: the implemented sequential runner executes the same stages in order |
| Tools-only | MCP client controls orchestration | Partial/adapter required: coordination and import are implemented, but the client owns execution and live research coverage is incomplete |

The workflow meaning and terminal contract are stable across modes. Agent spawning, tool transport, and interruption remain adapter-specific. This is the **observable parity target**, not proof that every mode is live-complete today and not runtime-mechanism parity.

Tools-only coordination is implemented, but tools-only **live research** is incomplete until separately configured provider-neutral research-data MCP adapters pass [their contract](RESEARCH_DATA_MCP.md). The default server must not register placeholder retrieval tools or imply that a semantic capability is available.

## Codex plugin

The repository contains:

- `.codex-plugin/plugin.json` — plugin interface metadata;
- `.agents/plugins/marketplace.json` — local marketplace entry;
- `.mcp.json` — credential-free MCP server definition; and
- `skills/tradingagents-portable/` — the host instructions.

Install or add the repository as a local Codex plugin, then invoke `$tradingagents-portable` from a Codex task. Codex supplies model reasoning, live web/browser access, and optional subagents. The skill uses `company-analytics.v1` and returns only a completed result.

The plugin requires no model or market-data API key inside portable inputs. Any authenticated source access belongs to Codex or another host connector and remains outside portable state.

## MCP

Start the server:

```bash
uv run stock-research-agents-mcp
```

Recommended client sequence:

1. `discover_capability`
2. `create_company_analytics_run`
3. shared start, safe-receipt, and stage-commit controls across all 26 host-executed stages
4. shared pause/resume, cancellation, and cursor-event controls as needed
5. `finalize_host_run` after the terminal stage supplies one complete `host-submission.v4`
6. consume `finalize_host_run.presentation`: open its run-specific `url` when `status` is `ready`, or render
   `get_run_view` inline when the host is headless
7. later `record_research_outcome` and `get_research_quality` when forecasts resolve

The durable coordinator checkpoints all 26 analytics stages in manifest order, resumes from the first incomplete stage, strictly validates the v4 terminal payload, rebinds report result/event descriptors to the durable lifecycle `run_id`, and supports crash-recoverable finalization. Completed `RunResult.artifacts` are the authoritative analytics/quality sidecars. The quality outcome index is a recoverable projection, not a second publication authority. Use `prepare_company_analytics` plus `import_company_analytics` only for an already-complete stateless submission; a stateless host may execute dependency-ready work in parallel before import.

Use discovery rather than pinning a tool count. Legacy dashboard-named tools remain aliases for compatibility.
`launch_research_report` remains an explicit ensure/retry operation, but a second launch call is not required after
a successful import or finalization returns a ready presentation. Every company uses the same viewer application;
the `?run=<run_id>` query selects the completed dossier.

Pass `presentation_mode = "path_only"` on MCP completion calls for a remote/headless harness, or set
`STOCKRESEARCHAGENTS_PRESENTATION_MODE=path_only` as a process-wide CLI/default policy. The historical
`TRADINGAGENTS_PORTABLE_PRESENTATION_MODE` name remains a fallback. Publication still succeeds
and returns the deterministic presentation path, while the absolute URL remains unset. An `auto` URL is scoped to the
presenter host's loopback namespace and carries a short-lived capability fragment; it is not a network-shareable URL.
Presentation startup failure never rolls back a valid completed research publication.

## Python

Python callers may use the same coordinators and strict models directly. Keep concrete model clients and provider adapters outside `tradingagents_portable`; translate their outputs at the host-submission boundary.
The portable publication service does not start UI infrastructure. An application adapter may call
`present_completed_run` after successful publication or inject its own completed-run presenter.

## Generic host adapter checklist

- Resolve the exact instrument identity before retrieval.
- Preserve `requested_at`, `cutoff_at`, and truthful research mode.
- Retrieve the newest evidence available by the cutoff, then apply an adaptive structural and cycle-aware lookback.
- Keep source terms and entitlements explicit.
- Assign stable source-batch and observation IDs and emit `source-lineage-crosswalk.v1`; its batch IDs must exactly equal the run card's ordered `source_batch_ids`.
- State `content_sha256_scope` explicitly. `source_content` hashes authoritative source bytes retained by the host, `bounded_extract` hashes the exact UTF-8 extract, and the safe adapter default `normalized_source_record` hashes the adapter's canonical parsed source record. The digest never authorizes raw-content transfer.
- Preserve canonical URI, content digest, host license-receipt identity, dossier document identity, and analytics source/license identity in the crosswalk; access, redistribution, and terms must agree across the portable records.
- Execute stages in dependency order or use the manifest's sequential fallback.
- In a durable run, commit only the current first-incomplete stage returned by the coordinator.
- Commit only bounded opaque nonterminal descriptors.
- Submit the complete terminal artifact once.
- Treat validation failure as a failed publication, not a partial success.
- Render only the completed `RunView` or exported artifacts.
- Never bypass paywalls or move licensed bodies across the portable boundary.

## Optional upstream adapter

`tradingagents-portable-legacy-mcp` and the `research` CLI import an installed upstream `TradingAgentsGraph`. They are compatibility adapters, not the default portable runtime, and may require environment-owned credentials.
