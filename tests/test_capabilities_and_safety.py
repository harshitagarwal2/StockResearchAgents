from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tradingrearchagents.capabilities import discovery, feature_matrix
from tradingrearchagents.contracts import PROTOTYPE_NOTICE, RunRequest
from tradingrearchagents.errors import CapabilitySetupError
from tradingrearchagents.legacy import LegacyTradingAgentsAdapter

ROOT = Path(__file__).resolve().parents[1]


def test_feature_matrix_has_no_parity_blocker_statuses() -> None:
    matrix = feature_matrix(legacy_path=str(ROOT / "does-not-exist"))
    serialized = json.dumps(matrix.to_dict()).lower()

    assert matrix.features
    assert "missing" not in serialized
    assert "deferred" not in serialized
    assert "host_blocked" not in serialized
    assert "legacy_full_topology" in {feature.name for feature in matrix.features}
    assert "orcl_fixture" in {feature.name for feature in matrix.features}
    assert "loopback_dashboard" in {feature.name for feature in matrix.features}
    assert {feature.level.value for feature in matrix.features} <= {"supported", "optional", "prohibited"}


def test_discovery_has_no_broker_or_order_tool_surface() -> None:
    payload = discovery(legacy_path=str(ROOT / "does-not-exist"))
    tool_names = tuple(str(name).lower() for name in payload["tools"])

    assert not any("broker" in name or "order" in name or "trade" in name for name in tool_names)
    assert "never an order" in str(payload["safety_notice"]).lower()


def test_optional_legacy_adapter_fails_with_typed_setup_guidance(tmp_path: Path) -> None:
    missing_legacy = tmp_path / "missing-upstream"
    adapter = LegacyTradingAgentsAdapter(str(missing_legacy))
    request = RunRequest(symbol="AAPL", executor="legacy")

    with pytest.raises(CapabilitySetupError) as captured:
        adapter.run(request)

    payload = captured.value.to_dict()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "legacy_executor_unavailable"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["steps"]
    serialized = json.dumps(payload).lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_contract_imports_are_side_effect_free() -> None:
    script = """
import json
import sys
import tradingrearchagents.contracts
import tradingrearchagents.topology
blocked = sorted(
    name for name in sys.modules
    if name == 'tradingagents' or name.startswith(('tradingagents.', 'langgraph', 'langchain', 'dotenv'))
)
print(json.dumps(blocked))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert json.loads(completed.stdout) == []


def test_non_executable_notice_is_unambiguous() -> None:
    normalized = PROTOTYPE_NOTICE.lower()
    assert "not financial advice" in normalized
    assert "never an order" in normalized
    assert "broker instruction" in normalized
    assert "authorization to trade" in normalized
