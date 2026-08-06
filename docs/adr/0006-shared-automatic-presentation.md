# ADR 0006: Share and automatically discover completed presentation

- **Status:** Accepted
- **Date:** 2026-08-03
- **Decision owners:** StockResearchAgents maintainers

## Context

The Research Dossier Viewer already renders any completed run selected by `?run=<run_id>`, but import and finalize
operations return only a relative path. Callers must launch another server manually, and the existing foreground CLI
server cannot outlive a short command. Starting one page or server per company would duplicate infrastructure while
misrepresenting the viewer as company-specific.

## Decision

Keep atomic research publication and presentation separate. After a successful completed publication, inbound
adapters invoke a narrow completed-run presenter. The default local presenter coordinates one detached, loopback-only
viewer daemon per durable state directory and returns a versioned receipt containing the run ID, deterministic path,
runtime-local absolute URL, readiness status, reuse status, and any presentation-only error.

The daemon uses a private registry, coordination lock, and lifetime lease; binds an ephemeral loopback port; verifies
its instance, protocol, package, run schema, assets, and state-directory identity through authenticated health checks;
and reports ready only after the exact completed run endpoint responds. A random per-daemon capability is carried in
the URL fragment, exchanged for an API-scoped `HttpOnly` session cookie, and never sent as an initial HTTP request or
referrer. The server validates exact loopback Host/Origin authorities and emits restrictive browser security headers.
It reloads durable completed state and quality outcomes for each request, expires after a reported idle period, and
never opens a browser.

Headless adapters use the same contract with `status = path_only` and no absolute URL. A presentation failure never
rolls back or downgrades a valid completed research publication.

## Scope and non-goals

This decision governs completed-result discovery and local viewer process lifetime. It does not add research logic,
partial-stage streaming, credentials, provider access, lifecycle controls, broker authority, or browser automation to
the viewer. An absolute loopback URL is runtime-local and is never stored as a cross-machine identifier.

## Consequences

- Every company uses one generic viewer application and a run-specific URL.
- CLI, MCP, Codex, and other short-lived adapters can return a usable local page without blocking.
- Publication remains deterministic and authoritative even when presentation is unavailable.
- A small private daemon registry, concurrency lock, readiness protocol, and idle lifecycle must be maintained.
- Ready receipts declare that URLs are scoped to the presenter host's loopback namespace and report their idle TTL;
  remote/headless MCP callers select `path_only` per completion call.
- The versioned presentation path remains deterministic for a completed run.

## Alternatives considered

- Generate static HTML per company: rejected because it duplicates the read model and can drift from typed state.
- Start a new in-process server per result: rejected because short-lived CLI processes exit and repeated runs leak
  servers and ports.
- Always return a fixed port: rejected because the URL may be dead or belong to another process.
- Make the browser own publication or retrieval: rejected because it violates the completed-only authority boundary.

## Contract impact

`launch_research_report` is an explicit ensure/retry operation. Completed import/finalize responses carry a versioned `presentation` receipt for the exact published run.

## Validation evidence

Automated tests must prove loopback-only binding, token/Host/Origin protection, private registry permissions,
cross-process server reuse, stale/version-mismatched daemon recovery, later quality-outcome visibility, visibility of
a company published after daemon startup, exact-run URL routing, path-only behavior, completed-only gating, and
non-rollback when presentation startup fails.
