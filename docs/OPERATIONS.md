# Operations

- **Purpose:** document local state, completed publication, exports, recovery, and troubleshooting.
- **Audience:** users, host operators, and maintainers.
- **Canonical for:** local operational behavior.
- **Not canonical for:** business semantics or provider operations.

## State directory

StockResearchAgents state resolves in this order:

1. `STOCKRESEARCHAGENTS_STATE_DIR`
2. `$XDG_STATE_HOME/stock-research-agents`
3. `~/.local/state/stock-research-agents`

Use an isolated directory for demonstrations or tests:

```bash
STOCKRESEARCHAGENTS_STATE_DIR=/private/tmp/stock-research-agents-demo \
  uv run stock-research-agents report --fixture
```

The store writes private temporary files and atomically replaces completed artifacts. Do not edit run files manually.

## Completed publication

Lifecycle state and completed result publication are separate. A run may have durable stage progress while the Research Dossier Viewer correctly shows no dossier. Visibility begins only after terminal validation and atomic publication succeed.

`analytics-init` / `create_company_analytics_run` creates a durable 26-stage lifecycle with its own control `run_id`. Shared lifecycle controls accept one first-incomplete stage commit at a time, retain safe receipts and events, and resume from that boundary. Finalization strictly validates analytics and atomically publishes the content-derived `CompanyAnalyticsResultV1`, which retains the exact submission and seven authoritative artifacts. Completed control state exposes the canonical result identity as `result_run_id`; it does not replace the lifecycle ID. The quality outcome index uses a hidden stage/publish sequence and is reconstructed from completed artifacts when recovery requires it; it is not part of a distributed transaction. `analytics-import` / `import_company_analytics` remains an atomic stateless path for an already-complete analytics wrapper.

## Recovery

- `run-pause` stops at a stage boundary.
- `run-resume` continues from the first incomplete stage.
- `run-cancel` requests cooperative cancellation.
- `run-cancel-ack` records caller acknowledgement after in-flight work stops.
- `run-finalize` retries recoverable publication staging without weakening validation.

The caller runtime owns hard interruption and must replay an interrupted in-flight stage.

## Inspect and export

Use CLI or MCP read operations to inspect run control, events, the typed result, or the completed `RunView`. `run-export` writes completed JSON/Markdown artifacts to an explicit target directory.

Do not treat the browser cache, a partial API response, or a host's private stage material as the authoritative completed artifact.

## Research Dossier Viewer

Successful CLI imports/finalization and MCP imports/finalization automatically return a `presentation` receipt. In
the default `auto` mode, StockResearchAgents ensures one shared loopback viewer daemon for the durable state directory and
returns a run-specific capability URL such as
`http://127.0.0.1:<port>/?run=<run_id>#access_token=<capability>`. The browser exchanges the fragment-only token for
an `HttpOnly`, `SameSite=Strict`, API-scoped session cookie and removes the fragment from the address bar. Treat the
unopened capability URL as private. Later companies reuse that server; no
company-specific HTML file or server is generated.

The absolute URL is runtime-local discovery metadata and is not embedded in the immutable `CompanyAnalyticsResultV1`. The viewer
registry, token, startup diagnostics, coordination lock, and lifetime lease live under the state directory with
private permissions. Host and Origin validation, API authentication, CSP, framing denial, and no-referrer policy
protect the browser boundary. Registry and health identities bind the protocol, package, run schema, and viewer asset
digest so a protocol-mismatched daemon is retired instead of reused. The daemon rereads durable completed bundles and
quality outcomes for each request, exits after the reported idle timeout, never opens a browser, and has no research,
credential, or execution authority.

For a headless process, disable automatic server startup without changing research semantics:

```bash
STOCKRESEARCHAGENTS_PRESENTATION_MODE=path_only \
  uv run stock-research-agents analytics-import --input completed-analytics.json
```

The response then carries `presentation.status = "path_only"`, a deterministic `presentation.path`, and no absolute
URL. If daemon startup fails, the completed result remains published and the receipt reports presentation as
unavailable so a host can retry with `launch_research_report` or use `get_run_view` inline.

MCP callers may select the same policy per completion call with `presentation_mode = "path_only"`; this is preferred
for remote or headless clients because an `auto` URL is reachable only inside the presenter host's loopback namespace.
Ready receipts declare `url_scope = "presenter_host_loopback"` and `idle_ttl_seconds` explicitly.

The foreground command remains available for diagnostics:

```bash
uv run stock-research-agents report --host 127.0.0.1 --port 8765
```

Only explicit loopback addresses are accepted. The server must never bind to a public interface.

## Common problems

| Symptom | Meaning | Response |
| --- | --- | --- |
| Empty viewer | No completed publication exists | Finish or import a valid terminal dossier |
| Presentation is `path_only` | Headless mode or a non-durable in-memory store is active | Render `get_run_view` inline or enable automatic presentation with durable state |
| Presentation is `unavailable` | Viewer startup or exact-run readiness failed after publication | Keep the completed result, inspect the structured presentation error, then retry the viewer |
| Fixture appears old | Fixture cutoff is intentionally fixed | Use a truthful live host run for current research |
| Licensed area is blocked | Host entitlement or redistribution is unavailable | Keep the limitation; do not substitute fabricated content |
| Resume repeats one stage | StockResearchAgents resumes at stage boundaries | Let the host replay that stage idempotently |
| Direct import shows no checkpointing | Stateless imports have no lifecycle | Use the durable company lifecycle when checkpoints are required |
| Analytics resume repeats one stage | Resume occurs at stage boundaries | Replay the interrupted caller-owned stage idempotently, then commit it |
| Licensed page cannot be opened | Access is absent or restricted | Record the limitation; never bypass the restriction |
