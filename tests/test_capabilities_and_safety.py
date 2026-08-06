from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from stock_research_agents.capabilities import discovery, feature_matrix
from stock_research_agents.contracts import PROTOTYPE_NOTICE

ROOT = Path(__file__).resolve().parents[1]


def test_feature_matrix_reports_only_standalone_capabilities() -> None:
    matrix = feature_matrix()
    serialized = json.dumps(matrix.to_dict()).lower()
    names = {feature.name for feature in matrix.features}

    assert names >= {"typed_contracts", "company_analytics_v1", "research_data_adapter_contracts"}
    assert "legacy" not in serialized
    assert "upstream" not in serialized
    assert "tradingagents" not in serialized
    assert {feature.level.value for feature in matrix.features} <= {
        "supported",
        "partial",
        "optional",
        "prohibited",
    }


def test_discovery_has_no_broker_order_or_retired_surface() -> None:
    payload = discovery()
    tool_names = {str(name) for name in payload["tools"]}

    assert payload["active_profile"] == "company-analytics.v1"
    assert "get_validation_report" in tool_names
    assert not tool_names.intersection(
        {
            "run_legacy",
            "prepare_host_run",
            "import_host_run",
            "prepare_company_research",
            "import_company_research",
            "create_host_run",
            "create_company_research_run",
            "launch_local_dashboard",
            "get_viewer_report",
        }
    )
    assert not any("broker" in name or "order" in name or "trade" in name for name in tool_names)
    assert "never an order" in str(payload["safety_notice"]).lower()


def test_contract_imports_are_side_effect_free() -> None:
    script = """
import json
import sys
import stock_research_agents.contracts
import stock_research_agents.company_analytics_v1
blocked = sorted(
    name for name in sys.modules
    if name == 'tradingagents' or name.startswith(('tradingagents.', 'langgraph', 'langchain', 'dotenv'))
)
print(json.dumps(blocked))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test-owned source
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
