from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"

_FORBIDDEN_DEPENDENCY_PREFIXES = ("tradingagents", "langgraph", "langchain")
_FORBIDDEN_RUNTIME_IMPORTS = {"tradingagents", "langgraph", "langchain"}
_FORBIDDEN_PUBLIC_TOKENS = ("tradingagents", "legacy", "upstream")


def _normalized_distribution_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement.strip())
    assert match is not None, f"unparseable dependency requirement: {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _contains_forbidden_dependency(name: str) -> bool:
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    return any(normalized == prefix or normalized.startswith(f"{prefix}-") for prefix in _FORBIDDEN_DEPENDENCY_PREFIXES)


def _structured_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _structured_strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for child in value:
            yield from _structured_strings(child)


def _forbidden_public_strings(value: Any) -> list[str]:
    return sorted(
        {
            text
            for text in _structured_strings(value)
            if any(token in text.casefold() for token in _FORBIDDEN_PUBLIC_TOKENS)
        }
    )


def _machine_identifiers(value: Any) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text == "mcpServers" and isinstance(child, Mapping):
                yield from (str(server_name) for server_name in child)
            if key_text.casefold() in {
                "$id",
                "capability_id",
                "id",
                "name",
                "schema_id",
                "server",
                "workflow_id",
            } and isinstance(child, str):
                yield child
            yield from _machine_identifiers(child)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for child in value:
            yield from _machine_identifiers(child)


def test_runtime_dependency_graph_has_no_external_or_upstream_runtime() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    dependency_groups = {
        "runtime": project.get("dependencies", []),
        **project.get("optional-dependencies", {}),
    }
    assert "upstream" not in {name.casefold() for name in dependency_groups}

    forbidden_requirements = {
        group: sorted(
            requirement
            for requirement in requirements
            if _contains_forbidden_dependency(_normalized_distribution_name(requirement))
        )
        for group, requirements in dependency_groups.items()
    }
    assert not {group: values for group, values in forbidden_requirements.items() if values}

    lock_path = ROOT / "uv.lock"
    if lock_path.is_file():
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        forbidden_locked = sorted(
            package["name"] for package in lock.get("package", []) if _contains_forbidden_dependency(package["name"])
        )
        assert forbidden_locked == []


def test_legacy_and_upstream_product_files_are_absent() -> None:
    explicitly_retired = {
        ROOT / ".github/workflows/upstream-sync.yml",
        ROOT / "evidence/legacy-removal-evidence.v1.json",
        ROOT / "evidence/parity-ledger.v1.json",
        ROOT / "scripts/run_upstream_semantic_probe.py",
        ROOT / "scripts/upstream_pin.py",
        ROOT / "scripts/verify_legacy_removal.py",
        ROOT / "src/stock_research_agents/legacy.py",
        ROOT / "src/stock_research_agents/legacy_mcp_server.py",
        ROOT / "src/stock_research_agents/host_native.py",
        ROOT / "src/stock_research_agents/migrations.py",
        ROOT / "src/stock_research_agents/oracle_semantics.py",
        ROOT / "src/stock_research_agents/projection.py",
        ROOT / "src/stock_research_agents/transition_verifier.py",
        ROOT / "src/stock_research_agents/dashboard.py",
        ROOT / "src/stock_research_agents/company_research.py",
        ROOT / "src/stock_research_agents/fixture.py",
        ROOT / "src/stock_research_agents/topology.py",
        ROOT / "src/stock_research_agents/workflow/fixture-workflow.v1.json",
        ROOT / "src/stock_research_agents/workflow/fixture-submission.v1.schema.json",
        ROOT / "src/stock_research_agents/workflow/host-submission.v1.schema.json",
        ROOT / "src/stock_research_agents/workflow/host-submission.v2.schema.json",
        ROOT / "src/stock_research_agents/workflow/host-submission.v3.schema.json",
        ROOT / "src/stock_research_agents/workflow/host-submission.v4.schema.json",
        ROOT / "src/stock_research_agents/workflow/legacy-transition.v1.json",
        ROOT / "upstream.lock.json",
    }
    assert sorted(path.relative_to(ROOT).as_posix() for path in explicitly_retired if path.exists()) == []

    assert not (SOURCE_ROOT / "tradingagents_portable").exists()
    assert not (SOURCE_ROOT / "tradingagents_host").exists()
    assert ".upstream/" not in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    production_roots = (
        SOURCE_ROOT,
        ROOT / "scripts",
        ROOT / ".github/workflows",
        ROOT / "evidence",
    )
    forbidden_named_files = sorted(
        path.relative_to(ROOT).as_posix()
        for base in production_roots
        if base.exists()
        for path in base.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
        and any(token in path.name.casefold() for token in ("legacy", "upstream"))
    )
    assert forbidden_named_files == []


def test_public_distribution_entry_points_and_machine_ids_use_product_brand() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["name"] == "stock-research-agents"
    assert project["scripts"] == {
        "stock-research-agents": "stock_research_agents.cli:main",
        "stock-research-agents-mcp": "stock_research_agents.mcp_server:main",
        "stock-research-data-mcp": "stock_research_agents_host.research_data_mcp:main",
    }

    plugin = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "stock-research-agents"

    marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["name"] == "stock-research-agents-local"
    assert [entry["name"] for entry in marketplace["plugins"]] == ["stock-research-agents"]

    mcp_manifest = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert set(mcp_manifest["mcpServers"]) == {"stock-research-agents", "stock-research-data"}

    structured_manifests = [plugin, marketplace, mcp_manifest]
    structured_manifests.extend(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((SOURCE_ROOT / "stock_research_agents/workflow").glob("*.json"))
    )
    old_brand_identifiers = sorted(
        identifier
        for identifier in _machine_identifiers(structured_manifests)
        if "tradingagents" in identifier.casefold()
    )
    assert old_brand_identifiers == []


def test_source_ast_has_no_external_runtime_imports_or_legacy_entry_points() -> None:
    forbidden_imports: list[str] = []
    forbidden_definitions: list[str] = []

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        module = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(module):
            imported_roots: set[str] = set()
            if isinstance(node, ast.Import):
                imported_roots = {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots = {node.module.partition(".")[0]}
            for imported_root in imported_roots & _FORBIDDEN_RUNTIME_IMPORTS:
                forbidden_imports.append(f"{relative}:{node.lineno}:{imported_root}")

            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.name in {
                "AnalystReport",
                "ExecutionConfig",
                "LegacyTradingAgentsAdapter",
                "PortfolioDecision",
                "RunRequest",
                "RunResult",
                "TraderDecision",
                "WorkflowTopology",
                "run_legacy",
                "start_host_run",
                "commit_host_stage",
                "pause_host_run",
                "resume_host_run",
                "finalize_host_run",
            }:
                forbidden_definitions.append(f"{relative}:{node.lineno}:{node.name}")

    assert forbidden_imports == []
    assert forbidden_definitions == []


def test_package_root_exposes_only_the_first_party_completed_result() -> None:
    import stock_research_agents as package

    assert package.CompanyAnalyticsResultV1.__name__ == "CompanyAnalyticsResultV1"
    for retired_name in (
        "AnalystReport",
        "ExecutionConfig",
        "PortfolioDecision",
        "RunRequest",
        "RunResult",
        "TraderDecision",
        "WorkflowTopology",
    ):
        assert not hasattr(package, retired_name)


def test_discovery_and_mcp_expose_no_legacy_or_upstream_surface() -> None:
    from stock_research_agents.capabilities import discovery

    payload = discovery()
    assert _forbidden_public_strings(payload) == []

    pytest.importorskip("mcp")
    from stock_research_agents import mcp_server
    from stock_research_agents_host import research_data_mcp

    coordination_tools = {tool.name for tool in mcp_server.mcp._tool_manager.list_tools()}
    research_data_tools = {tool.name for tool in research_data_mcp.mcp._tool_manager.list_tools()}
    assert coordination_tools == set(payload["tools"])
    assert _forbidden_public_strings(sorted(coordination_tools | research_data_tools)) == []
