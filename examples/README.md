# Examples

The files in this directory are public, credential-free inputs for learning the portable contracts.

- `company-request.v1.json` is a minimal deterministic request for planning an Evidence-First Company Research run.

Generate and inspect its plan with:

```bash
uv run stock-research-agents company-plan \
  --input examples/company-request.v1.json \
  --output plan.json
```

The example uses `fixture` mode and a historical cutoff. Changing the symbol does not make the request live; a live request is truthful only when the host actually retrieves cutoff-valid live evidence.

Complete terminal submissions are intentionally not hand-maintained here. They are large, strictly linked artifacts produced and validated by the host. The deterministic conformance builders live under `tests/research_submission_fixtures.py`.
