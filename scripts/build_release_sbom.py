#!/usr/bin/env python3
"""Create a deterministic SPDX 2.3 SBOM for built Python release artifacts."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tarfile
import tomllib
import zipfile
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

ARTIFACT_SUFFIXES = (".whl", ".tar.gz")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_text(path: Path) -> str:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise ValueError(f"{path.name} must contain exactly one METADATA file")
            return archive.read(names[0]).decode("utf-8")
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
            ]
            if len(members) != 1:
                raise ValueError(f"{path.name} must contain exactly one PKG-INFO file")
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise ValueError(f"could not read PKG-INFO from {path.name}")
            return extracted.read().decode("utf-8")
    raise ValueError(f"unsupported release artifact: {path.name}")


def _spdx_id(value: str) -> str:
    return "SPDXRef-" + re.sub(r"[^A-Za-z0-9.-]", "-", value)


def _runtime_requirements(metadata: Any) -> list[Requirement]:
    requirements: list[Requirement] = []
    for value in metadata.get_all("Requires-Dist", []):
        try:
            requirement = Requirement(value)
        except InvalidRequirement as exc:
            raise ValueError(f"invalid Requires-Dist entry: {value}") from exc
        marker = "" if requirement.marker is None else str(requirement.marker)
        if "extra ==" in marker or "== extra" in marker:
            continue
        requirements.append(requirement)
    return requirements


def _literal_assignment(path: Path, name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return node.value.value
    return None


def _editable_root_version(root: dict[str, Any], lock_file: Path) -> str:
    if version := root.get("version"):
        return str(version)
    editable = root.get("source", {}).get("editable")
    if not isinstance(editable, str):
        raise ValueError("lock root package must contain a version or editable source")
    project_root = (lock_file.parent / editable).resolve()
    pyproject_path = project_root / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("could not resolve the editable lock root version") from exc
    project = pyproject.get("project", {})
    if version := project.get("version"):
        return str(version)
    attr = pyproject.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {}).get("attr")
    if not isinstance(attr, str) or "." not in attr:
        raise ValueError("editable lock root does not expose a resolvable project version")
    module_name, attribute = attr.rsplit(".", 1)
    search_roots = (
        pyproject.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {}).get("where", ["."])
    )
    if not isinstance(search_roots, list) or not all(isinstance(value, str) for value in search_roots):
        raise ValueError("editable lock root has invalid setuptools package roots")
    module_parts = module_name.split(".")
    for search_root in search_roots:
        base = project_root / search_root
        candidates = [base.joinpath(*module_parts).with_suffix(".py"), base.joinpath(*module_parts, "__init__.py")]
        for candidate in candidates:
            if candidate.is_file() and (resolved := _literal_assignment(candidate, attribute)):
                return resolved
    raise ValueError("could not resolve the editable lock root version")


def _locked_packages(lock_file: Path) -> dict[str, dict[str, Any]]:
    try:
        lock = tomllib.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read lock file: {lock_file}") from exc
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise ValueError("lock file does not contain a package inventory")
    indexed: dict[str, dict[str, Any]] = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            raise ValueError("lock file contains an invalid package entry")
        name = str(canonicalize_name(package["name"]))
        if name in indexed:
            raise ValueError(f"lock file contains ambiguous package versions: {name}")
        indexed[name] = package
    return indexed


def _dependency_name(dependency: dict[str, Any]) -> str:
    name = dependency.get("name")
    if not isinstance(name, str):
        raise ValueError("lock dependency is missing a package name")
    return str(canonicalize_name(name))


def _package_dependencies(package: dict[str, Any], selected_extras: set[str]) -> list[dict[str, Any]]:
    dependencies = list(package.get("dependencies", []))
    optional = package.get("optional-dependencies", {})
    if not isinstance(dependencies, list) or not isinstance(optional, dict):
        raise ValueError(f"lock package has invalid dependencies: {package.get('name', '<unknown>')}")
    for extra in sorted(selected_extras):
        extra_dependencies = optional.get(extra)
        if not isinstance(extra_dependencies, list):
            raise ValueError(f"lock package does not define selected extra {extra}: {package.get('name', '<unknown>')}")
        dependencies.extend(extra_dependencies)
    if not all(isinstance(dependency, dict) for dependency in dependencies):
        raise ValueError(f"lock package has an invalid dependency entry: {package.get('name', '<unknown>')}")
    return dependencies


def _package_id(name: str, version: str) -> str:
    return _spdx_id(f"Package-{name}-{version}")


def _locked_runtime_graph(
    lock_file: Path,
    *,
    root_name: str,
    root_version: str,
    root_metadata: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    indexed = _locked_packages(lock_file)
    normalized_root = str(canonicalize_name(root_name))
    root = indexed.get(normalized_root)
    if root is None:
        raise ValueError(f"lock file does not contain the release root package: {normalized_root}")
    locked_root_version = _editable_root_version(root, lock_file)
    if locked_root_version != root_version:
        raise ValueError(f"lock root version {locked_root_version} does not match release version {root_version}")

    requirements = {str(canonicalize_name(req.name)): req for req in _runtime_requirements(root_metadata)}
    root_dependencies = {_dependency_name(dependency) for dependency in _package_dependencies(root, set())}
    if set(requirements) != root_dependencies:
        raise ValueError("wheel runtime dependencies disagree with lock root dependencies")
    for name, requirement in requirements.items():
        locked = indexed.get(name)
        locked_version = None if locked is None else locked.get("version")
        if not isinstance(locked_version, str):
            raise ValueError(f"runtime dependency is not version-locked: {name}")
        if requirement.specifier and not requirement.specifier.contains(locked_version, prereleases=True):
            raise ValueError(f"locked version does not satisfy wheel requirement: {requirement}")

    reachable = {normalized_root}
    selected_extras: dict[str, set[str]] = {normalized_root: set()}
    processed: dict[str, frozenset[str]] = {}
    pending = [normalized_root]
    edges: set[tuple[str, str, str]] = set()
    while pending:
        source_name = pending.pop(0)
        source = indexed[source_name]
        extras = selected_extras[source_name]
        state = frozenset(extras)
        if processed.get(source_name) == state:
            continue
        processed[source_name] = state
        for dependency in _package_dependencies(source, extras):
            target_name = _dependency_name(dependency)
            target = indexed.get(target_name)
            target_version = None if target is None else target.get("version")
            if not isinstance(target_version, str):
                raise ValueError(f"reachable runtime dependency is not version-locked: {target_name}")
            marker = dependency.get("marker")
            edge_comment = f"Environment marker: {marker}" if isinstance(marker, str) else ""
            edges.add((source_name, target_name, edge_comment))
            target_extras = dependency.get("extra", [])
            if not isinstance(target_extras, list) or not all(isinstance(extra, str) for extra in target_extras):
                raise ValueError(f"lock dependency has invalid extras: {source_name} -> {target_name}")
            known_extras = selected_extras.setdefault(target_name, set())
            before = len(known_extras)
            known_extras.update(target_extras)
            if target_name not in reachable or len(known_extras) != before:
                reachable.add(target_name)
                pending.append(target_name)

    dependency_packages: list[dict[str, Any]] = []
    for name in sorted(reachable - {normalized_root}):
        locked_package = indexed[name]
        version = str(locked_package["version"])
        registry = locked_package.get("source", {}).get("registry")
        if registry != "https://pypi.org/simple":
            raise ValueError(f"reachable runtime dependency is not locked from PyPI: {name}")
        dependency_packages.append(
            {
                "name": name,
                "SPDXID": _package_id(name, version),
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{name}@{version}",
                    }
                ],
            }
        )

    root_id = _spdx_id(root_name)
    relationships: list[dict[str, str]] = []
    for source_name, target_name, comment in sorted(edges):
        source_id = (
            root_id
            if source_name == normalized_root
            else _package_id(source_name, str(indexed[source_name]["version"]))
        )
        target_id = _package_id(target_name, str(indexed[target_name]["version"]))
        relationship = {
            "spdxElementId": source_id,
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": target_id,
        }
        if comment:
            relationship["comment"] = comment
        relationships.append(relationship)
    return dependency_packages, relationships


def build_sbom(artifacts: list[Path], *, created: str, lock_file: Path) -> dict[str, Any]:
    if not artifacts:
        raise ValueError("at least one wheel or sdist is required")
    artifacts = sorted((path.resolve() for path in artifacts), key=lambda path: path.name)

    parsed = [Parser().parsestr(_metadata_text(path)) for path in artifacts]
    identities = {(metadata["Name"], metadata["Version"]) for metadata in parsed}
    if len(identities) != 1:
        raise ValueError("all release artifacts must describe the same name and version")
    package_name, version = identities.pop()
    if not package_name or not version:
        raise ValueError("release metadata must contain Name and Version")

    artifact_hashes = [(path, _sha256(path)) for path in artifacts]
    try:
        lock_digest = _sha256(lock_file)
    except OSError as exc:
        raise ValueError(f"could not read lock file: {lock_file}") from exc
    namespace_seed = "\n".join(
        [*(f"{path.name}:{digest}" for path, digest in artifact_hashes), f"{lock_file.name}:{lock_digest}"]
    )
    namespace_digest = hashlib.sha256(namespace_seed.encode("utf-8")).hexdigest()
    package_id = _spdx_id(package_name)
    wheel_metadata = [metadata for path, metadata in zip(artifacts, parsed, strict=True) if path.suffix == ".whl"]
    if not wheel_metadata:
        raise ValueError("at least one wheel is required to validate locked runtime dependencies")
    dependency_packages, dependency_relationships = _locked_runtime_graph(
        lock_file,
        root_name=package_name,
        root_version=version,
        root_metadata=wheel_metadata[0],
    )
    files: list[dict[str, Any]] = [
        {
            "fileName": path.name,
            "SPDXID": _spdx_id(f"File-{index}-{path.name}"),
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
        }
        for index, (path, digest) in enumerate(artifact_hashes, start=1)
    ]
    relationships: list[dict[str, str]] = [
        {"spdxElementId": package_id, "relationshipType": "CONTAINS", "relatedSpdxElement": file["SPDXID"]}
        for file in files
    ]
    relationships.extend(dependency_relationships)

    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{package_name}-{version}-release-artifacts",
        "documentNamespace": f"https://github.com/harshitagarwal2/StockResearchAgents/sbom/{namespace_digest}",
        "creationInfo": {
            "creators": ["Tool: scripts/build_release_sbom.py"],
            "created": created,
            "licenseListVersion": "3.25",
        },
        "documentDescribes": [package_id],
        "packages": [
            {
                "name": package_name,
                "SPDXID": package_id,
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "Apache-2.0",
                "licenseDeclared": "Apache-2.0",
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{package_name}@{version}",
                    }
                ],
            },
            *dependency_packages,
        ],
        "files": files,
        "relationships": relationships,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--lock-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    created_at = datetime.fromtimestamp(epoch, UTC) if epoch else datetime.now(UTC)
    created = created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sbom = build_sbom(args.artifacts, created=created, lock_file=args.lock_file.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
