"""Dependency-free documentation and architecture-asset validation."""

from __future__ import annotations

import contextlib
import io
import re
import shlex
import struct
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
NESTED_IMAGE_LINK_PATTERN = re.compile(r"\[!\[[^\]]*\]\([^)]+\)\]\(([^)]+)\)")
BASH_FENCE_PATTERN = re.compile(r"```bash\s*\n(?P<body>.*?)```", re.DOTALL)
CLI_PREFIX_PATTERN = re.compile(r"(?<![\w-])uv\s+run\s+stock-research-agents(?:\s|$)")
REPOSITORY_LICENSE_PATTERN = re.compile(
    r"\b(?:repository|project)(?:'s)?\s+"
    r"(?P<license>MIT|Apache(?:\s+License)?(?:\s+2\.0|-2\.0)?)\s+license\b",
    re.IGNORECASE,
)
REMOTE_PREFIXES = ("http://", "https://", "mailto:", "plugin://", "subagent://")
STALE_VOCABULARY = (
    (re.compile(r"\bRunResult\b"), "retired RunResult contract"),
    (re.compile(r"decision[-_ ]consistency", re.IGNORECASE), "retired decision-consistency projection"),
    (re.compile(r"debate[-_ ]import(?:er)?", re.IGNORECASE), "retired debate-import path"),
    (re.compile(r"\btrader proposal\b", re.IGNORECASE), "retired trader-stage semantics"),
    (re.compile(r"\banalyst[- ]team\b", re.IGNORECASE), "retired analyst-team semantics"),
    (re.compile(r"\bhost harness\b", re.IGNORECASE), "stale ownership wording"),
    (re.compile(r"\bCompanyResearchCoordinator\b"), "retired coordinator name"),
    (re.compile(r"\blocally ready\b", re.IGNORECASE), "incorrect executor readiness wording"),
)

REQUIRED_DOCS = (
    ROOT / "README.md",
    ROOT / "DESIGN.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "CODE_OF_CONDUCT.md",
    ROOT / "ROADMAP.md",
    ROOT / "SECURITY.md",
    ROOT / "SUPPORT.md",
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
)

PUBLIC_ROOT_DOCS = (
    "README.md",
    "DESIGN.md",
    "design-qa.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "ROADMAP.md",
    "SECURITY.md",
    "SUPPORT.md",
)
PUBLIC_DOC_DIRECTORIES = ("docs", "examples", "benchmarks", "assets", "adapters", "skills")

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
    files = [ROOT / name for name in PUBLIC_ROOT_DOCS]
    for directory in (ROOT / name for name in PUBLIC_DOC_DIRECTORIES):
        files.extend(path for path in directory.rglob("*.md") if path.is_file())
    return sorted(set(files))


def documentation_text_files() -> list[Path]:
    files = [ROOT / name for name in PUBLIC_ROOT_DOCS]
    for directory in (ROOT / name for name in PUBLIC_DOC_DIRECTORIES):
        files.extend(
            path for path in directory.rglob("*") if path.is_file() and path.suffix in {".md", ".mmd", ".html"}
        )
    return sorted(set(files))


def stale_vocabulary_errors() -> list[str]:
    errors: list[str] = []
    for path in documentation_text_files():
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, description in STALE_VOCABULARY:
                if pattern.search(line):
                    errors.append(f"{path.relative_to(ROOT)}:{line_number}: {description}")
    return errors


def _bash_commands(path: Path) -> Iterator[str]:
    text = path.read_text(encoding="utf-8")
    for match in BASH_FENCE_PATTERN.finditer(text):
        command = ""
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            command = f"{command} {line}".strip()
            if command.endswith("\\"):
                command = command[:-1].rstrip()
                continue
            yield command
            command = ""
        if command:
            yield command


def cli_example_errors(paths: Iterable[Path] | None = None) -> list[str]:
    """Validate documented coordination-CLI commands without executing them."""

    from stock_research_agents.cli import _parser

    errors: list[str] = []
    for path in markdown_files() if paths is None else paths:
        for command in _bash_commands(path):
            prefix = CLI_PREFIX_PATTERN.search(command)
            if prefix is None:
                continue
            documented_command = command[prefix.start() :]
            try:
                arguments = shlex.split(documented_command)[3:]
            except ValueError as exc:
                errors.append(f"{path.relative_to(ROOT)}: invalid CLI example quoting: {exc}")
                continue

            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                try:
                    _parser().parse_args(arguments)
                except SystemExit as exc:
                    if exc.code == 0:
                        continue
                    detail = stderr.getvalue().strip().splitlines()[-1]
                    errors.append(f"{path.relative_to(ROOT)}: invalid CLI example `{documented_command}`: {detail}")
    return errors


def _normalized_license(value: str) -> str | None:
    normalized = re.sub(r"[\s-]+", " ", value.strip().lower())
    if normalized == "mit":
        return "MIT"
    if normalized in {"apache", "apache 2.0", "apache license 2.0"}:
        return "Apache-2.0"
    return None


def license_consistency_errors(paths: Iterable[Path] | None = None) -> list[str]:
    """Keep explicit repository-license claims aligned with package metadata and LICENSE."""

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared_license = project.get("license")
    if not isinstance(declared_license, str):
        return ["pyproject.toml: project.license must be a SPDX string"]

    canonical = _normalized_license(declared_license)
    if canonical is None:
        return [f"pyproject.toml: unsupported project.license value {declared_license!r}"]

    errors: list[str] = []
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    expected_marker = "Apache License" if canonical == "Apache-2.0" else "MIT License"
    if expected_marker not in license_text:
        errors.append(f"LICENSE: content does not match pyproject.toml project.license {declared_license}")

    for path in markdown_files() if paths is None else paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in REPOSITORY_LICENSE_PATTERN.finditer(line):
                referenced = _normalized_license(match.group("license"))
                if referenced != canonical:
                    errors.append(
                        f"{path.relative_to(ROOT)}:{line_number}: repository license {match.group('license')!r} "
                        f"does not match {declared_license}"
                    )
    return errors


def contributor_bootstrap_errors() -> list[str]:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    if re.search(r"(?m)^uv sync --extra dev(?:\s|$)", text):
        return []
    return ["CONTRIBUTING.md: development bootstrap must install the dev extra with `uv sync --extra dev`"]


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
    for pattern in (LINK_PATTERN, NESTED_IMAGE_LINK_PATTERN):
        for match in pattern.finditer(text):
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
    errors.extend(stale_vocabulary_errors())
    errors.extend(cli_example_errors())
    errors.extend(license_consistency_errors())
    errors.extend(contributor_bootstrap_errors())
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
