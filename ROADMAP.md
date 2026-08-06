# Roadmap

This roadmap describes proof and reliability priorities, not delivery promises or investment-performance claims.

## Release readiness

- Publish signed, checksummed wheel and source artifacts only after installed-artifact, SBOM, provenance, TestPyPI, and protected-environment gates pass.
- Keep Python 3.11–3.14 and the supported MCP v2 range under compatibility testing.
- Maintain a backup-first state migration and rollback path before changing durable schemas.

## Evidence and provider reliability

- Expand the scheduled public-provider canary matrix while keeping ordinary CI deterministic and offline.
- Record only sanitized provider status and contract-shape evidence; never archive credentials or raw restricted content.
- Add licensed or OAuth-backed routes only through host-owned adapters and explicit entitlement receipts.

## Research quality

- Accumulate independently resolved, leakage-controlled forecast cohorts under explicit cutoff, horizon, and resolution conventions.
- Extend cohort evaluation to additional forecast kinds only after their outcome conventions are approved and represented in versioned contracts.
- Treat calibration-model fitting or other ML as optional host-owned research until external evaluation criteria and adequate cohorts exist.

## Product and operations

- Keep the completed-only viewer accessible, responsive, projection-only, and protected by browser/runtime regression tests.
- Improve redacted diagnostics and recovery evidence without turning telemetry into authorization or outcome truth.
- Add a second workflow profile only when a concrete independent use case justifies generalizing the current registry.

## Permanently out of scope

Broker connectivity, order placement, portfolio mutation, executable trading authority, credential transport, and guaranteed investment performance are not roadmap items.
