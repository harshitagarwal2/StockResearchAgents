# Examples

The files in this directory are public, credential-free inputs for learning the portable contracts.

- `company-request.v1.json` is a minimal deterministic request for planning an Evidence-First Company Research run.

Generate and inspect its plan with:

```bash
uv run stock-research-agents analytics-plan \
  --input examples/company-request.v1.json \
  --output plan.json
```

The example uses `fixture` mode and a historical cutoff. Changing the symbol does not make the request live; a live request is truthful only when the host actually retrieves cutoff-valid live evidence.

Complete terminal-submission source files are intentionally not hand-maintained here. They are large, strictly linked artifacts produced and validated by the host. The deterministic conformance builders live under `tests/research_submission_fixtures.py`.

## Generated product demonstration

The committed ORCL demonstration is regenerated from those deterministic contracts and checked byte-for-byte in CI:

```bash
uv run python scripts/generate_fixture_demo.py
```

![Fixture Research Dossier Viewer preview](generated/orcl-fixture/preview.svg)

The accompanying [result](generated/orcl-fixture/result.json), [events](generated/orcl-fixture/events.json), [view](generated/orcl-fixture/view.json), and digest [manifest](generated/orcl-fixture/manifest.json) are synthetic, historical-cutoff fixture artifacts. They demonstrate the completed product surface; they are not current research, investment advice, or an executable trade.
