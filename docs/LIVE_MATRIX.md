# Live-provider evidence matrix

- **Purpose:** define reproducible operational proof for live retrieval without
  placing credentials, raw bodies, or account state in this repository.
- **Audience:** host operators and release owners.
- **Canonical for:** the live/failure evidence required by the legacy-transition
  gate.
- **Not canonical for:** provider terms, credentials, or a claim of complete
  coverage.

Local tests intentionally use recorded transports. A live run is an
operator-owned activity: it must use a clean, immutable commit; only approved
host routes; and the source rights held by that host. Never commit credentials,
cookies, raw provider responses, redirect paths, queries, or licensed extracts.

## Required cases

Run every case at the same commit and record both the provider route and the
portable receipt. “Pass” means the observed status matches the expected status;
it does not mean the source is universally available.

| Case | Capability | Expected terminal state | Required evidence |
| --- | --- | --- | --- |
| Public success | SEC filings/fundamentals, GDELT news, World Bank macro, Polymarket context | `complete` or explicit bounded `partial` | sanitized `SourceBatch`, request/cutoff, response timestamp, content digest, source terms and access state |
| Public failure | one unavailable, rate-limited, malformed, or denied public response | `unavailable`, `rate_limited`, or `denied` with limitation | sanitized failure class, route identity, timestamp, and coverage impact |
| Licensed market data | prices and indicators through an entitled host `SourcePort` | conformance-valid batch or truthful unavailable/denied result | entitlement and license-receipt IDs, redistribution state, no extract unless permitted |
| Social source | approved host OAuth route | conformance-valid bounded batch or truthful denied result | host approval/entitlement receipt, access state, and bounded observation metadata |
| Chrome, if explicitly selected | public approved publisher page | attested batch or visible coverage gap | domain approval, canonical target/redirect/address attestations, no raw URL or browser state |

Use at least two unambiguous symbols plus one expected failure or no-result
query. Record the exact UTC window, package version, commit SHA, OS/Python,
route configuration identity, and whether each run is live, fixture, or
historical replay. Do not turn a single observation into a freshness or
availability guarantee.

## Evidence handoff

Store the sanitized run receipts and release-owner sign-offs in the protected
release-evidence location described in [Legacy transition](LEGACY_TRANSITION.md).
Each artifact must bind to the exact clean `HEAD`, include its SHA-256 digest,
and be signed by the release automation trust root. Only then may the live
matrix removal gate be marked passed. The checked-in index remains intentionally
empty until the release owner supplies authenticated operational evidence.

Before accepting a new host adapter, run the offline contract suite:

```bash
uv run pytest -q tests/test_host_source_ports.py tests/test_research_data_mcp.py
```

Then run the live matrix above under the host's own approval and entitlement
controls. Offline conformance is necessary but never substitutes for the live
evidence.
