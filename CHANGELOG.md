# Changelog

All notable changes to StockResearchAgents are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Harness-neutral release automation, package metadata, MCP Registry metadata, and host adapter documentation.

## Release policy

- Stable releases use `vMAJOR.MINOR.PATCH` tags and the same version in package, plugin, and MCP Registry metadata.
- Pre-release validation is published only to TestPyPI; it is not a normal installation channel.
- Release notes must state fixture/live-data status and preserve the non-executable analytical-scenario boundary.
