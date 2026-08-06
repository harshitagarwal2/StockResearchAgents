from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stable_release_metadata_is_consistent() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/verify_release_metadata.py",
            "--tag",
            "v0.1.0",
            "--require-stable",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "release metadata valid: 0.1.0\n"


def test_project_metadata_describes_the_public_distribution() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["name"] == "stock-research-agents"
    assert project["dynamic"] == ["version"]
    assert project["urls"]["Repository"] == "https://github.com/harshitagarwal2/StockResearchAgents"
    assert "mcp" in project["keywords"]
    assert "Programming Language :: Python :: 3.11" in project["classifiers"]


def test_source_checkout_launchers_and_host_adapters_stay_thin() -> None:
    expected = {
        "scripts/run-stock-research-mcp": "stock_research_agents.mcp_server",
        "scripts/run-stock-research-data-mcp": "stock_research_agents_host.research_data_mcp",
    }
    for relative_path, module in expected.items():
        launcher = ROOT / relative_path
        text = launcher.read_text(encoding="utf-8")

        assert os.access(launcher, os.X_OK)
        assert "repo_root=" in text
        assert f"exec uv run python -m {module}" in text
        assert "echo " not in text

    opencode = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    servers = opencode["mcp"]["servers"]
    assert servers["stock-research-agents"]["command"] == ["bash", "scripts/run-stock-research-mcp"]
    assert servers["stock-research-data"]["command"] == ["bash", "scripts/run-stock-research-data-mcp"]
    assert all(server["type"] == "local" for server in servers.values())

    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    hermes = (ROOT / "docs" / "HERMES_MCP_CONFIG.yaml").read_text(encoding="utf-8")
    assert "AGENTS.md" in claude
    assert "skills/stock-research-agents/SKILL.md" in claude
    assert "mcp_servers:" in hermes
    assert "/absolute/path/to/StockResearchAgents" in hermes
