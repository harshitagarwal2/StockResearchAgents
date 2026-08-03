# tradingrearchagents — repository guidance

This repository is an incubation environment for a harness-neutral TradingAgents capability. It must validate independently before any production integration into the sibling repository at `/Users/harshitagarwal/projects/tradingAgents`.

## Boundaries

- Treat the sibling TradingAgents repository as read-only reference and an optional runtime dependency.
- Do not copy or fork its prompts, workflow business logic, provider implementations, or persistence internals when an adapter can call them.
- Keep portable contracts, fixture execution, MCP tools, plugin metadata, and UI projections independent of LangGraph and any specific harness.
- No broker integration, order placement, simulated fills, portfolio mutation, or executable trading action.
- Trade-like outputs must be labeled `non_executable_analytical_scenario` and fixture/live-data status must always be visible.
- Never put credentials in MCP inputs/results, state, events, artifacts, logs, browser storage, or UI payloads.

## Verification

- Tests run without network access or real credentials.
- The deterministic ORCL fixture is the local end-to-end demonstration.
- Validate exact debate/risk turn counts, complete result sections, plugin manifests, MCP launch, loopback-only UI serving, and static UI safety.
- Keep the generated dashboard a projection of typed state/events; do not add analysis business logic to browser code.

## Collaboration

- Multiple agents may edit this repository concurrently. Preserve unrelated edits and never revert another lane's changes.
- Keep ownership boundaries explicit and report interface mismatches rather than silently changing another lane's files.
