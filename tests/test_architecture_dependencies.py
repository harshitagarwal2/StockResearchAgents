from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "stock_research_agents"
SOURCE_PACKAGE = ROOT / "src" / "stock_research_agents_host"


def _imports(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _python_files(path: Path) -> tuple[Path, ...]:
    return tuple(sorted(candidate for candidate in path.rglob("*.py") if "__pycache__" not in candidate.parts))


def test_domain_contracts_do_not_depend_on_interfaces_or_infrastructure() -> None:
    domain_files = (
        PACKAGE / "research_contracts.py",
        PACKAGE / "research_conformance.py",
        PACKAGE / "company_analytics_v1" / "contracts.py",
        PACKAGE / "research_quality_v1" / "contracts.py",
        *_python_files(PACKAGE / "analytics_v1"),
    )
    forbidden = {
        "cli",
        "mcp_server",
        "report_server",
        "viewer_server",
        "presentation",
        "store",
        "lifecycle",
        "stock_research_agents_host",
    }
    violations: list[str] = []
    for path in domain_files:
        for imported in _imports(path):
            if imported.split(".")[0] in forbidden or any(f".{name}" in imported for name in forbidden):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert violations == []


def test_lifecycle_domain_does_not_compose_default_infrastructure() -> None:
    path = PACKAGE / "company_lifecycle.py"
    source = path.read_text(encoding="utf-8")

    assert "from .store import" not in source
    assert "LIFECYCLE_STORE" not in source
    assert "RUN_STORE" not in source
    assert "default_decision_memory_store" not in source

    profile_source = (PACKAGE / "lifecycle_profiles.py").read_text(encoding="utf-8")
    assert "QUALITY_STORE" not in profile_source


def test_default_coordinator_is_constructed_only_in_bootstrap() -> None:
    constructors: list[str] = []
    for path in _python_files(PACKAGE):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "CompanyAnalyticsCoordinator":
                    constructors.append(path.relative_to(PACKAGE).as_posix())

    assert constructors == ["bootstrap.py"]


def test_inbound_adapters_use_the_application_services_and_runtime() -> None:
    for name in ("cli.py", "mcp_server.py"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        assert "from .application import CompletedPublicationService, CompletedRunQueryService" in source
        assert "from .bootstrap import DEFAULT_RUNTIME" in source
        assert "from .store import RUN_STORE" not in source


def test_provider_strategies_do_not_depend_on_coordination_or_presentation() -> None:
    forbidden = {"cli", "mcp_server", "company_lifecycle", "presentation", "viewer_server"}
    violations: list[str] = []
    for path in _python_files(SOURCE_PACKAGE / "adapters" / "providers"):
        for imported in _imports(path):
            if any(name in imported.split(".") for name in forbidden):
                violations.append(f"{path.relative_to(ROOT)} imports {imported}")
    assert violations == []
