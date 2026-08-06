#!/usr/bin/env python3
"""Write a deterministic source/render digest manifest for architecture diagrams."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DIAGRAMS = (
    "system-context",
    "portable-components",
    "completed-publication",
    "research-quality-lineage",
    "solid-ports-adapters",
    "source-to-dossier",
    "company-analytics-lifecycle",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path, *, renderer: str) -> dict[str, object]:
    diagrams: dict[str, object] = {}
    for name in DIAGRAMS:
        source = root / "docs" / "diagrams" / f"{name}.mmd"
        svg = root / "assets" / "architecture" / f"{name}.svg"
        png = root / "assets" / "architecture" / f"{name}.png"
        diagrams[name] = {
            "source": source.relative_to(root).as_posix(),
            "source_sha256": _sha256(source),
            "svg": svg.relative_to(root).as_posix(),
            "svg_sha256": _sha256(svg),
            "png": png.relative_to(root).as_posix(),
            "png_sha256": _sha256(png),
        }
    return {
        "schema": "architecture-render-manifest.v1",
        "renderer": renderer,
        "diagrams": diagrams,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--renderer", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest(args.root.resolve(), renderer=args.renderer)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if not args.write:
        print(payload, end="")
        return 0
    target = args.root / "assets" / "architecture" / "render-manifest.json"
    target.write_text(payload, encoding="utf-8")
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
