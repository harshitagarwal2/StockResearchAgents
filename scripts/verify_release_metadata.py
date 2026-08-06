#!/usr/bin/env python3
"""Fail closed when release-facing package and MCP metadata disagree."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "stock-research-agents"
REGISTRY_NAME = "io.github.harshitagarwal2/stock-research-agents"
VERSION_FILE = ROOT / "src" / "stock_research_agents" / "_version.py"
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
STABLE_VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


def package_version() -> str:
    match = VERSION_PATTERN.search(VERSION_FILE.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"could not read __version__ from {VERSION_FILE.relative_to(ROOT)}")
    return match.group(1)


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def validate_package_only(version: str, tag: str | None) -> list[str]:
    errors: list[str] = []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project")
    if not isinstance(project, dict):
        return ["pyproject.toml must define [project]"]
    if project.get("name") != PACKAGE_NAME:
        errors.append(f"pyproject project.name must be {PACKAGE_NAME!r}")
    if "version" in project:
        errors.append("pyproject must derive its version from _version.py, not declare project.version")
    dynamic = project.get("dynamic")
    if not isinstance(dynamic, list) or "version" not in dynamic:
        errors.append("pyproject project.dynamic must include version")
    dynamic_config = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {})
    expected = "stock_research_agents._version.__version__"
    if not isinstance(dynamic_config, dict) or dynamic_config.get("version", {}).get("attr") != expected:
        errors.append(f"pyproject setuptools dynamic version must use {expected!r}")
    if tag is not None and tag.removeprefix("refs/tags/") != f"v{version}":
        errors.append(f"tag {tag!r} must be v{version}")
    return errors


def validate_public_metadata(version: str) -> list[str]:
    errors: list[str] = []
    plugin = load_json(ROOT / ".codex-plugin" / "plugin.json")
    if plugin.get("version") != version:
        errors.append(".codex-plugin/plugin.json version must match the package version")

    registry = load_json(ROOT / "server.json")
    if registry.get("name") != REGISTRY_NAME:
        errors.append(f"server.json name must be {REGISTRY_NAME!r}")
    if registry.get("version") != version:
        errors.append("server.json version must match the package version")
    packages = registry.get("packages")
    if not isinstance(packages, list) or len(packages) != 1 or not isinstance(packages[0], dict):
        errors.append("server.json must define exactly one PyPI package")
    else:
        package = packages[0]
        if package.get("registryType") != "pypi":
            errors.append("server.json package registryType must be pypi")
        if package.get("identifier") != PACKAGE_NAME:
            errors.append("server.json PyPI identifier must match the package name")
        if package.get("version") != version:
            errors.append("server.json PyPI package version must match the package version")
        if package.get("transport") != {"type": "stdio"}:
            errors.append("server.json package transport must be stdio")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"mcp-name: {REGISTRY_NAME}" not in readme:
        errors.append("README.md must contain the exact MCP Registry mcp-name marker")

    for path in (
        ROOT / "src" / "stock_research_agents" / "mcp_server.py",
        ROOT / "src" / "stock_research_agents_host" / "research_data_mcp.py",
    ):
        text = path.read_text(encoding="utf-8")
        if "version=__version__" not in text:
            errors.append(f"{path.relative_to(ROOT)} must use the shared package version")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="expected version tag, for example v0.1.0")
    parser.add_argument(
        "--package-only",
        action="store_true",
        help="skip plugin and MCP Registry checks for TestPyPI previews",
    )
    parser.add_argument("--require-stable", action="store_true", help="require a MAJOR.MINOR.PATCH version")
    parser.add_argument("--print-version", action="store_true", help="print the validated package version")
    args = parser.parse_args(argv)

    version = package_version()
    errors = validate_package_only(version, args.tag)
    if args.require_stable and not STABLE_VERSION_PATTERN.fullmatch(version):
        errors.append("stable releases must use MAJOR.MINOR.PATCH versioning")
    if not args.package_only:
        errors.extend(validate_public_metadata(version))

    if errors:
        for error in errors:
            print(f"release metadata error: {error}", file=sys.stderr)
        return 1
    if args.print_version:
        print(version)
    else:
        print(f"release metadata valid: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
