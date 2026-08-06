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


def _metadata(name: str = "stock-research-agents", version: str = "0.1.0") -> bytes:
    return f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nLicense-Expression: Apache-2.0\n\n".encode()


def _write_wheel(path: Path, *, version: str = "0.1.0") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"stock_research_agents-{version}.dist-info/METADATA", _metadata(version=version))


def _write_sdist(path: Path, *, version: str = "0.1.0") -> None:
    payload = _metadata(version=version)
    info = tarfile.TarInfo(f"stock_research_agents-{version}/PKG-INFO")
    info.size = len(payload)
    nested = tarfile.TarInfo(f"stock_research_agents-{version}/src/stock_research_agents.egg-info/PKG-INFO")
    nested.size = len(payload)
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))
        archive.addfile(nested, io.BytesIO(payload))


def test_release_sbom_is_deterministic_and_covers_wheel_and_sdist(tmp_path: Path) -> None:
    module = _load_sbom_module()
    wheel = tmp_path / "stock_research_agents-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "stock_research_agents-0.1.0.tar.gz"
    _write_wheel(wheel)
    _write_sdist(sdist)

    created = "2026-08-05T12:00:00Z"
    first = module.build_sbom([wheel, sdist], created=created)
    second = module.build_sbom([wheel, sdist], created=created)

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
        module.build_sbom([wheel, sdist], created="2026-08-05T12:00:00Z")
