# Documentation map

- **Purpose:** route readers to the single canonical document for each question.
- **Audience:** users, harness integrators, maintainers, reviewers, and new contributors.
- **Canonical for:** documentation ownership and navigation.
- **Not canonical for:** runtime behavior or compatibility guarantees.

## Use the product

1. [Getting started](GETTING_STARTED.md) — run the safe fixture and open the Research Dossier Viewer.
2. [Operations](OPERATIONS.md) — state directories, exports, recovery, and troubleshooting.
3. [Glossary](GLOSSARY.md) — human-facing terms and strict identifiers.

## Integrate a host

1. [Integration](INTEGRATION.md) — MCP, Python, generic harness modes, and the optional Codex adapter.
2. [Harnesses](HOSTS.md) — PyPI, Git, GitHub Release, and host-specific MCP launch paths.
2. [Contract guide](CONTRACTS.md) — request, plan, stage envelope, terminal submission, and completed projection.
3. [Source portfolio](SOURCE_PORTFOLIO.md) — multi-source coverage, independence, deduplication, and expansion rules.
4. [Research-data MCP](RESEARCH_DATA_MCP.md) — provider-neutral adapter contracts and missing live-tool proof.
5. [Compatibility](COMPATIBILITY.md) — frozen profiles, mappings, and migration rules.

## Understand the system

1. [Design](../DESIGN.md) — product language, user journeys, viewer information architecture, and visual rules.
2. [Architecture](ARCHITECTURE.md) — boundaries, components, patterns, state, and publication.
3. [Ports and adapters](PORTS_AND_ADAPTERS.md) — SOLID dependency direction and extension seams.
4. [Research Quality](RESEARCH_QUALITY.md) — implemented forecast accountability and honest evaluation limits.
5. [Architecture decisions](adr/README.md) — why the durable boundaries exist.

## Review and release

1. [Capability and proof ledger](FEATURE_PARITY.md) — implemented, host-dependent, and unverified behavior.
2. [Validation](VALIDATION.md) — executable proof and known gaps.
3. [Legacy transition](LEGACY_TRANSITION.md) — removal gates, deprecation policy, and retained readers.
4. [Contributing](../CONTRIBUTING.md) — safe change workflow and review expectations.
5. [Releasing](RELEASING.md) — version checks, TestPyPI preflight, PyPI, GitHub Release, and MCP Registry flow.

## Document ownership rule

Link to canonical detail instead of copying it. README owns the product promise and first success; Design owns human experience; Architecture owns implementation structure; Contracts owns integration sequencing; Source portfolio owns breadth and independence rules; Research-data MCP owns adapter normalization; Compatibility owns the version map; Legacy transition owns removal gates; Validation owns proof.
