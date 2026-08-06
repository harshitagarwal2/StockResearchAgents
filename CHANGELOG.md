# Changelog

All notable changes to StockResearchAgents are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Harness-neutral release automation, package metadata, MCP Registry metadata, and host adapter documentation.
- Explicit application composition, shared completed-run services, architecture dependency tests, and provider-specific source routing.
- GitHub issue and pull-request templates, code ownership, support guidance, and Python 3.12/3.13 compatibility smoke jobs.
- Evaluation-only binary calibration cohorts, state diagnostics and migrations, multi-source portfolio receipts, and deterministic fixture demonstration artifacts.
- Installed-distribution smoke tests, SPDX SBOM generation, artifact attestations, CodeQL, dependency review, supply-chain audit, mutation smoke, live-provider canary, and real-browser accessibility checks.
- Python 3.14 validation, property-based tests, contributor roadmap, and community code of conduct.

### Changed

- Reworked the README around a CI-backed proof path, explicit interfaces, source limitations, and the non-execution boundary.
- Segregated application ports by reader/writer responsibility and clarified workflow-definition naming without changing wire identifiers.
- Replaced the public-source provider monolith with a typed capability catalog and provider-owned validation, retrieval, parsing, and normalization.
- Centralized application composition, completed-publication recovery, lifecycle validation, state layout ownership, and idempotent runtime shutdown.
- Ordered release publication behind independent wheel/sdist validation and provenance generation; no public release has been published.

## Release policy

- Stable releases use `vMAJOR.MINOR.PATCH` tags and the same version in package, plugin, and MCP Registry metadata.
- Pre-release validation is published only to TestPyPI; it is not a normal installation channel.
- Release notes must state fixture/live-data status and preserve the non-executable analytical-scenario boundary.
