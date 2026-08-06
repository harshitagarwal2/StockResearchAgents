#!/usr/bin/env python3
"""Create a deterministic SPDX 2.3 SBOM for built Python release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import zipfile
from datetime import UTC, datetime
from email.parser import Parser
from pathlib import Path
from typing import Any

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


def build_sbom(artifacts: list[Path], *, created: str) -> dict[str, Any]:
    if not artifacts:
        raise ValueError("at least one wheel or sdist is required")

    parsed = [Parser().parsestr(_metadata_text(path)) for path in artifacts]
    identities = {(metadata["Name"], metadata["Version"]) for metadata in parsed}
    if len(identities) != 1:
        raise ValueError("all release artifacts must describe the same name and version")
    package_name, version = identities.pop()
    if not package_name or not version:
        raise ValueError("release metadata must contain Name and Version")

    artifact_hashes = [(path, _sha256(path)) for path in artifacts]
    namespace_seed = "\n".join(f"{path.name}:{digest}" for path, digest in artifact_hashes)
    namespace_digest = hashlib.sha256(namespace_seed.encode("utf-8")).hexdigest()
    package_id = _spdx_id(package_name)
    files = [
        {
            "fileName": path.name,
            "SPDXID": _spdx_id(f"File-{index}-{path.name}"),
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
        }
        for index, (path, digest) in enumerate(artifact_hashes, start=1)
    ]
    relationships = [
        {"spdxElementId": package_id, "relationshipType": "CONTAINS", "relatedSpdxElement": file["SPDXID"]}
        for file in files
    ]

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
            }
        ],
        "files": files,
        "relationships": relationships,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    artifacts = sorted((path.resolve() for path in args.artifacts), key=lambda path: path.name)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    created_at = datetime.fromtimestamp(epoch, UTC) if epoch else datetime.now(UTC)
    created = created_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sbom = build_sbom(artifacts, created=created)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
