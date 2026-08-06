from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_sbom_module() -> ModuleType:
    path = ROOT / "scripts" / "build_release_sbom.py"
    spec = importlib.util.spec_from_file_location("build_release_sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metadata(
    name: str = "stock-research-agents",
    version: str = "0.1.0",
    *,
    requirements: tuple[str, ...] = (),
) -> bytes:
    requires_dist = "".join(f"Requires-Dist: {requirement}\n" for requirement in requirements)
    return f"""Metadata-Version: 2.4
Name: {name}
Version: {version}
License-Expression: Apache-2.0
{requires_dist}
""".encode()


def _write_wheel(path: Path, *, version: str = "0.1.0", requirements: tuple[str, ...] = ()) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"stock_research_agents-{version}.dist-info/METADATA",
            _metadata(version=version, requirements=requirements),
        )


def _write_sdist(path: Path, *, version: str = "0.1.0") -> None:
    payload = _metadata(version=version)
    info = tarfile.TarInfo(f"stock_research_agents-{version}/PKG-INFO")
    info.size = len(payload)
    nested = tarfile.TarInfo(f"stock_research_agents-{version}/src/stock_research_agents.egg-info/PKG-INFO")
    nested.size = len(payload)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
        archive.addfile(nested, io.BytesIO(payload))


def _write_lock(path: Path, *, root_version: str = "0.1.0", with_runtime_graph: bool = False) -> None:
    runtime_graph = (
        """
dependencies = [{ name = "mcp" }, { name = "colorama", marker = "sys_platform == 'win32'" }]

[package.optional-dependencies]
dev = [{ name = "pytest" }]

[[package]]
name = "mcp"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "anyio" }]

[[package]]
name = "anyio"
version = "4.14.2"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "9.1.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "colorama"
version = "0.4.6"
source = { registry = "https://pypi.org/simple" }
"""
        if with_runtime_graph
        else ""
    )
    path.write_text(
        f"""version = 1

[[package]]
name = "stock-research-agents"
version = "{root_version}"
{runtime_graph}
""",
        encoding="utf-8",
    )


def test_release_sbom_is_deterministic_and_covers_wheel_and_sdist(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.1.0.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)
    lock = tmp_path / "uv.lock"
    _write_lock(lock)

    created = "2026-08-05T12:00:00Z"
    first = module.build_sbom([wheel, sdist], created=created, lock_file=lock)
    second = module.build_sbom([sdist, wheel], created=created, lock_file=lock)

    assert first == second
    assert first["spdxVersion"] == "SPDX-2.3"
    assert first["creationInfo"]["created"] == created
    assert first["packages"][0]["versionInfo"] == "0.1.0"
    assert {file["fileName"] for file in first["files"]} == {wheel.name, sdist.name}
    assert all(file["checksums"][0]["algorithm"] == "SHA256" for file in first["files"])


def test_release_sbom_rejects_mismatched_distribution_versions(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.2.0.tar.gz"
    _write_wheel(wheel, version="0.1.0")
    _write_sdist(sdist, version="0.2.0")

    with pytest.raises(ValueError, match="same name and version"):
        module.build_sbom([wheel, sdist], created="2026-08-05T12:00:00Z", lock_file=tmp_path / "uv.lock")


def test_release_sbom_includes_exact_locked_transitive_runtime_graph(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.1.0.tar.gz"
    _write_wheel(
        wheel,
        requirements=(
            "MCP>=2.0,<3",
            "colorama>=0.4; sys_platform == 'win32'",
            "pytest>=8; extra == 'dev'",
        ),
    )
    _write_sdist(sdist)
    lock = tmp_path / "uv.lock"
    _write_lock(lock, with_runtime_graph=True)

    sbom = module.build_sbom([sdist, wheel], created="2026-08-05T12:00:00Z", lock_file=lock)
    packages = {package["name"]: package for package in sbom["packages"]}

    assert set(packages) == {"stock-research-agents", "mcp", "anyio", "colorama"}
    assert packages["mcp"]["versionInfo"] == "2.0.0"
    assert packages["anyio"]["versionInfo"] == "4.14.2"
    assert packages["colorama"]["versionInfo"] == "0.4.6"
    assert packages["mcp"]["externalRefs"][0]["referenceLocator"] == "pkg:pypi/mcp@2.0.0"
    assert packages["anyio"]["externalRefs"][0]["referenceLocator"] == "pkg:pypi/anyio@4.14.2"
    assert "pytest" not in packages

    package_id = packages["stock-research-agents"]["SPDXID"]
    depends_on = {
        (relationship["spdxElementId"], relationship["relatedSpdxElement"])
        for relationship in sbom["relationships"]
        if relationship["relationshipType"] == "DEPENDS_ON"
    }
    assert depends_on == {
        (package_id, packages["mcp"]["SPDXID"]),
        (package_id, packages["colorama"]["SPDXID"]),
        (packages["mcp"]["SPDXID"], packages["anyio"]["SPDXID"]),
    }
    assert sum(relationship["relationshipType"] == "CONTAINS" for relationship in sbom["relationships"]) == 2


def test_release_sbom_rejects_lock_root_version_mismatch(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.1.0.tar.gz"
    lock = tmp_path / "uv.lock"
    _write_wheel(wheel)
    _write_sdist(sdist)
    _write_lock(lock, root_version="0.2.0")

    with pytest.raises(ValueError, match="lock root version 0.2.0 does not match release version 0.1.0"):
        module.build_sbom([wheel, sdist], created="2026-08-05T12:00:00Z", lock_file=lock)


def test_release_sbom_requires_lock_file(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.1.0.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)

    with pytest.raises(ValueError, match="could not read lock file"):
        module.build_sbom(
            [wheel, sdist],
            created="2026-08-05T12:00:00Z",
            lock_file=tmp_path / "missing.lock",
        )
