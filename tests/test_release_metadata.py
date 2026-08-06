from __future__ import annotations

import json
import os
import re
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
    assert "Programming Language :: Python :: 3.14" in project["classifiers"]


def test_ci_exercises_every_declared_python_minor() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        match.group(1)
        for classifier in pyproject["project"]["classifiers"]
        if (match := re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", classifier))
    }
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    exercised = set(re.findall(r'["\x27](\d+\.\d+)["\x27]', workflow))

    assert declared == exercised


def test_readme_quickstart_uses_current_cli_surfaces() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "fixture --events" not in readme
    assert "scripts/smoke_backend.py" in readme
    assert "stock-research-agents analytics-plan" in readme
    assert (ROOT / "examples" / "company-request.v1.json").is_file()


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


def test_ci_installs_uv_before_source_launcher_smoke() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    compatibility_job = workflow.split("  python-compatibility:", maxsplit=1)[1]

    install_step, smoke_steps = compatibility_job.split("      - name: Compile Python", maxsplit=1)
    assert 'python -m pip install -e ".[dev]" "uv==0.12.1"' in install_step
    assert "pytest -q" in smoke_steps
    assert "python scripts/smoke_mcp.py" in smoke_steps


def test_release_publication_is_strictly_ordered_and_publisher_is_verified() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    publisher_job = workflow.split("  publish-mcp-registry:", maxsplit=1)[1]

    assert "needs: create-github-release" in publisher_job
    assert "releases/latest/download" not in publisher_job
    assert "/releases/download/v1.7.9/" in publisher_job
    assert "ab128162b0616090b47cf245afe0a23f3ef08936fdce19074f5ba0a4469281ac" in publisher_job
    assert "sha256sum --check" in publisher_job


def test_release_validates_each_distribution_and_attests_release_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "scripts/smoke_installed_distribution.py" in workflow
    assert "scripts/build_release_sbom.py" in workflow
    assert "--lock-file uv.lock" in workflow
    assert "SOURCE_DATE_EPOCH" in workflow
    attest_pin = "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2"
    assert workflow.count(attest_pin) == 2
    assert "actions/attest-build-provenance@" not in workflow
    assert "actions/attest-sbom@" not in workflow
    assert "sbom-path: release/sbom.spdx.json" in workflow
    assert "attestations: write" in workflow


def test_ci_has_locked_and_mcp_compatibility_edges() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --locked" in workflow
    assert "mcp==2.0.0" in workflow
    assert '"mcp>=2,<3"' in workflow
    assert "3.14" in workflow


def test_security_workflows_are_pinned_and_fail_closed() -> None:
    supply_chain = (ROOT / ".github" / "workflows" / "supply-chain.yml").read_text(encoding="utf-8")
    codeql = (ROOT / ".github" / "workflows" / "codeql.yml").read_text(encoding="utf-8")

    assert "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294" in supply_chain
    assert "pip-audit==2.10.1" in supply_chain
    assert "zizmor==1.29.0" in supply_chain
    assert "github/codeql-action/init@5595ccaf912efad79be6eef63a5619ff05969be3" in codeql
    assert "github/codeql-action/analyze@5595ccaf912efad79be6eef63a5619ff05969be3" in codeql


def test_live_provider_canary_is_scheduled_bounded_and_non_gating() -> None:
    workflow = (ROOT / ".github" / "workflows" / "live-provider-canary.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "timeout-minutes: 8" in workflow
    assert "timeout --kill-after=15s 360s python scripts/smoke_research_data.py" in workflow
    assert "--strictness contract" in workflow
    assert "sanitized-live-provider-canary" in workflow
    assert "SEC, GDELT, World Bank, and Polymarket" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
