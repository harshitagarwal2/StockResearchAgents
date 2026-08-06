from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from stock_research_agents_host.adapters.public import HTTPResponse, PublicResearchDataAdapter

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-08-03T12:00:00+00:00"


def _load_smoke_script():
    path = ROOT / "scripts" / "smoke_research_data.py"
    spec = importlib.util.spec_from_file_location("smoke_research_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def get_json(self, url: str, *, params: object = None, headers: object = None) -> HTTPResponse:
        if self.status != 200:
            return HTTPResponse(self.status, None)
        if "company_tickers" in url:
            return HTTPResponse(
                200,
                {
                    "0": {"ticker": "ORCL", "cik_str": 1341439},
                    "1": {"ticker": "META", "cik_str": 1326801},
                },
            )
        if "submissions" in url:
            return HTTPResponse(200, {"filings": {"recent": {}}})
        if "companyfacts" in url:
            return HTTPResponse(200, {"facts": {}})
        if "gdeltproject" in url:
            return HTTPResponse(200, {"articles": []})
        if "worldbank" in url:
            return HTTPResponse(200, [{"pages": 1}, []])
        if "gamma-api.polymarket.com" in url:
            return HTTPResponse(200, {"events": [], "pagination": {"hasMore": False, "totalResults": 0}})
        raise AssertionError(f"unexpected public provider URL: {url}")


def _adapter(status: int = 200) -> PublicResearchDataAdapter:
    return PublicResearchDataAdapter(FakeTransport(status), clock=lambda: CUTOFF)


def test_run_smoke_exercises_seven_public_capabilities_for_each_symbol() -> None:
    smoke = _load_smoke_script()

    evidence, exit_code = smoke.run_smoke(_adapter(), ("ORCL", "META"), CUTOFF, strict_public=False)

    assert exit_code == 0
    assert len(evidence["public_calls"]) == 14
    assert {(call["symbol"], call["capability"]) for call in evidence["public_calls"]} == {
        (symbol, capability) for symbol in ("ORCL", "META") for capability in smoke.PUBLIC_CAPABILITIES
    }


def test_run_smoke_emits_only_sanitized_deterministic_evidence_fields() -> None:
    smoke = _load_smoke_script()

    evidence, _ = smoke.run_smoke(_adapter(), ("ORCL", "META"), CUTOFF, strict_public=False)

    expected = {"symbol", "capability", "provider", "status", "count", "limitations", "timestamps", "failure_kind"}
    assert all(set(call) == expected for call in evidence["public_calls"])
    serialized = json.dumps(evidence).lower()
    assert all(secret not in serialized for secret in ("authorization", "api_key", "raw_body", "cookie", "bearer"))


def test_default_mode_succeeds_when_provider_is_unavailable_but_contracts_are_valid() -> None:
    smoke = _load_smoke_script()

    evidence, exit_code = smoke.run_smoke(_adapter(503), ("ORCL", "META"), CUTOFF, strict_public=False)

    assert exit_code == 0
    assert evidence["summary"]["provider_failures"] == 14
    assert evidence["summary"]["contract_failures"] == 0


def test_strict_public_mode_fails_when_public_provider_is_unavailable() -> None:
    smoke = _load_smoke_script()

    _, exit_code = smoke.run_smoke(_adapter(503), ("ORCL", "META"), CUTOFF, strict_public=True)

    assert exit_code == smoke.EXIT_PROVIDER_FAILURE


def test_contract_failure_has_distinct_status_and_exit_code() -> None:
    smoke = _load_smoke_script()

    class ContractBreakingAdapter:
        def fetch(self, capability: str, query: object) -> object:
            raise TypeError("raw provider body must not escape")

    evidence, exit_code = smoke.run_smoke(ContractBreakingAdapter(), ("ORCL", "META"), CUTOFF, strict_public=False)

    assert exit_code == smoke.EXIT_CONTRACT_FAILURE
    assert evidence["public_calls"][0]["status"] == "contract_failure"
    assert evidence["public_calls"][0]["limitations"] == ["Adapter contract failed with TypeError."]


def test_fail_closed_boundaries_remain_unavailable_or_denied() -> None:
    smoke = _load_smoke_script()

    evidence, _ = smoke.run_smoke(_adapter(), ("ORCL", "META"), CUTOFF, strict_public=False)

    by_capability = {call["capability"]: call["status"] for call in evidence["fail_closed_checks"]}
    assert by_capability == {
        "prices": "unavailable",
        "indicators": "unavailable",
        "stocktwits": "denied",
        "reddit": "denied",
    }


def test_main_honors_symbols_cutoff_output_and_strictness(monkeypatch, tmp_path: Path) -> None:
    smoke = _load_smoke_script()
    output = tmp_path / "smoke.json"
    monkeypatch.setattr(smoke, "create_adapter", _adapter)

    exit_code = smoke.main(
        [
            "--symbols",
            "ORCL",
            "META",
            "--cutoff",
            CUTOFF,
            "--output",
            str(output),
            "--strictness",
            "strict-public",
        ]
    )

    assert exit_code == smoke.EXIT_PROVIDER_FAILURE
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["request"] == {"symbols": ["ORCL", "META"], "cutoff": CUTOFF, "strictness": "strict-public"}
    assert payload["summary"]["provider_failures"] >= 1
