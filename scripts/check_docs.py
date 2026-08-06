"""Dependency-free documentation and architecture-asset validation."""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REMOTE_PREFIXES = ("http://", "https://", "mailto:", "plugin://", "subagent://")

REQUIRED_DOCS = (
    ROOT / "README.md",
    ROOT / "DESIGN.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "GETTING_STARTED.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "INTEGRATION.md",
    ROOT / "docs" / "HOSTS.md",
    ROOT / "docs" / "RELEASING.md",
    ROOT / "docs" / "CONTRACTS.md",
    ROOT / "docs" / "OPERATIONS.md",
    ROOT / "docs" / "GLOSSARY.md",
    ROOT / "docs" / "COMPATIBILITY.md",
    ROOT / "docs" / "RESEARCH_QUALITY.md",
    ROOT / "docs" / "RESEARCH_DATA_MCP.md",
    ROOT / "docs" / "LEGACY_TRANSITION.md",
    ROOT / "docs" / "adr" / "0005-host-native-core-and-legacy-retirement.md",
)

TECHNICAL_DIAGRAMS = (
    "system-context",
    "portable-components",
    "completed-publication",
    "research-quality-lineage",
    "solid-ports-adapters",
    "source-to-dossier",
    "company-analytics-lifecycle",
)
POSTERS = ("system-overview", "portable-patterns", "research-quality")
DIAGRAM_GALLERY = ROOT / "docs" / "diagrams" / "README.md"


def markdown_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "DESIGN.md", ROOT / "CONTRIBUTING.md"]
    for directory in (ROOT / "docs", ROOT / "examples", ROOT / "assets"):
        files.extend(path for path in directory.rglob("*.md") if path.is_file())
    return sorted(set(files))


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if " " in target and not target.startswith(("/", "./", "../")):
        target = target.split(" ", 1)[0]
    return target


def broken_links(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for match in LINK_PATTERN.finditer(text):
        target = _link_target(match.group(1))
        if not target or target.startswith("#") or target.startswith(REMOTE_PREFIXES):
            continue
        relative_path = target.split("#", 1)[0]
        if not relative_path:
            continue
        resolved = (path.parent / relative_path).resolve()
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing link target {target}")
    return errors


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ValueError("invalid PNG signature")
        length = struct.unpack(">I", handle.read(4))[0]
        kind = handle.read(4)
        if kind != b"IHDR" or length < 8:
            raise ValueError("missing PNG IHDR")
        width, height = struct.unpack(">II", handle.read(8))
    return width, height


def diagram_errors() -> list[str]:
    errors: list[str] = []
    gallery_text = DIAGRAM_GALLERY.read_text(encoding="utf-8") if DIAGRAM_GALLERY.exists() else ""
    for name in TECHNICAL_DIAGRAMS:
        source = ROOT / "docs" / "diagrams" / f"{name}.mmd"
        rendered = ROOT / "assets" / "architecture" / f"{name}.svg"
        preview = ROOT / "assets" / "architecture" / f"{name}.png"
        if not source.exists():
            errors.append(f"missing Mermaid source: {source.relative_to(ROOT)}")
        elif "accTitle:" not in source.read_text(encoding="utf-8") or "accDescr:" not in source.read_text(
            encoding="utf-8"
        ):
            errors.append(f"missing accessible Mermaid metadata: {source.relative_to(ROOT)}")
        if not rendered.exists():
            errors.append(f"missing SVG render: {rendered.relative_to(ROOT)}")
        else:
            try:
                svg_root = ET.parse(rendered).getroot()
            except ET.ParseError as exc:
                errors.append(f"invalid SVG {rendered.relative_to(ROOT)}: {exc}")
            else:
                view_box = svg_root.attrib.get("viewBox", "").split()
                if len(view_box) != 4:
                    errors.append(f"missing SVG viewBox: {rendered.relative_to(ROOT)}")
                else:
                    try:
                        svg_width = float(view_box[2])
                        svg_height = float(view_box[3])
                    except ValueError:
                        errors.append(f"invalid SVG viewBox: {rendered.relative_to(ROOT)}")
                    else:
                        if svg_width <= 0 or svg_height <= 0:
                            errors.append(f"non-positive SVG viewBox: {rendered.relative_to(ROOT)}")
                if svg_root.attrib.get("width") != "100%":
                    errors.append(f"SVG is not responsive-width: {rendered.relative_to(ROOT)}")
                if not svg_root.attrib.get("role"):
                    errors.append(f"SVG is missing an accessibility role: {rendered.relative_to(ROOT)}")
                child_names = {child.tag.rsplit("}", 1)[-1] for child in svg_root}
                if not {"title", "desc"}.issubset(child_names):
                    errors.append(f"SVG is missing title/description: {rendered.relative_to(ROOT)}")

        if not preview.exists():
            errors.append(f"missing GitHub PNG preview: {preview.relative_to(ROOT)}")
        else:
            try:
                width, height = _png_size(preview)
            except ValueError as exc:
                errors.append(f"invalid technical PNG {preview.relative_to(ROOT)}: {exc}")
            else:
                if width < 1200 or height < 250:
                    errors.append(f"technical PNG is too small: {preview.relative_to(ROOT)} is {width}x{height}")
                if max(width / height, height / width) > 6:
                    errors.append(
                        f"technical PNG aspect ratio is not GitHub-legible: "
                        f"{preview.relative_to(ROOT)} is {width}x{height}"
                    )

        preview_link = f"../../assets/architecture/{name}.png"
        svg_link = f"../../assets/architecture/{name}.svg"
        source_link = f"({name}.mmd)"
        if preview_link not in gallery_text or svg_link not in gallery_text or source_link not in gallery_text:
            errors.append(f"diagram is missing from GitHub preview gallery: {name}")

    for name in POSTERS:
        source = ROOT / "docs" / "renders" / f"{name}.html"
        rendered = ROOT / "assets" / "architecture" / f"{name}.png"
        if not source.exists():
            errors.append(f"missing poster source: {source.relative_to(ROOT)}")
        if not rendered.exists():
            errors.append(f"missing poster render: {rendered.relative_to(ROOT)}")
            continue
        try:
            width, height = _png_size(rendered)
        except ValueError as exc:
            errors.append(f"invalid poster {rendered.relative_to(ROOT)}: {exc}")
            continue
        if (width, height) != (1800, 1000):
            errors.append(f"poster must be 1800x1000: {rendered.relative_to(ROOT)} is {width}x{height}")
    return errors


def check() -> list[str]:
    errors = [f"missing canonical document: {path.relative_to(ROOT)}" for path in REQUIRED_DOCS if not path.exists()]
    for path in markdown_files():
        errors.extend(broken_links(path))
    errors.extend(diagram_errors())
    return errors


def main() -> int:
    errors = check()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"Documentation OK: {len(markdown_files())} Markdown files and 17 architecture renders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
