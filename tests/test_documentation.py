from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_check_docs():
    path = ROOT / "scripts" / "check_docs.py"
    spec = importlib.util.spec_from_file_location("check_docs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_documentation_links_and_architecture_assets_are_valid() -> None:
    check_docs = _load_check_docs()
    assert check_docs.check() == []


def test_documentation_gate_covers_public_root_adapter_and_skill_docs() -> None:
    check_docs = _load_check_docs()
    covered = {path.relative_to(ROOT).as_posix() for path in check_docs.markdown_files()}

    assert {
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "ROADMAP.md",
        "SECURITY.md",
        "SUPPORT.md",
        "adapters/README.md",
        "skills/stock-research-agents/SKILL.md",
    }.issubset(covered)


def test_documented_cli_examples_use_current_parser() -> None:
    check_docs = _load_check_docs()
    assert check_docs.cli_example_errors() == []


def test_repository_license_references_match_project_metadata() -> None:
    check_docs = _load_check_docs()
    assert check_docs.license_consistency_errors() == []


def test_contributor_bootstrap_installs_development_dependencies() -> None:
    check_docs = _load_check_docs()
    assert check_docs.contributor_bootstrap_errors() == []


def test_architecture_posters_use_checked_in_sources() -> None:
    for name in ("system-overview", "portable-patterns", "research-quality"):
        assert (ROOT / "docs" / "renders" / f"{name}.html").is_file()
        assert (ROOT / "assets" / "architecture" / f"{name}.png").is_file()


def test_architecture_render_manifest_binds_sources_to_checked_assets() -> None:
    check_docs = _load_check_docs()
    assert check_docs.architecture_render_manifest_errors() == []


def test_nested_image_link_target_is_validated(tmp_path, monkeypatch) -> None:
    check_docs = _load_check_docs()
    markdown = tmp_path / "README.md"
    (tmp_path / "preview.png").touch()
    markdown.write_text("[![Preview](preview.png)](missing.svg)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)

    assert check_docs.broken_links(markdown) == ["README.md: missing link target missing.svg"]


def test_unknown_documented_cli_command_is_rejected(tmp_path, monkeypatch) -> None:
    check_docs = _load_check_docs()
    markdown = tmp_path / "README.md"
    markdown.write_text("```bash\nuv run stock-research-agents retired-command\n```\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)

    errors = check_docs.cli_example_errors([markdown])

    assert len(errors) == 1
    assert errors[0].startswith("README.md: invalid CLI example")
    assert "invalid choice: 'retired-command'" in errors[0]


def test_mismatched_repository_license_claim_is_rejected(tmp_path, monkeypatch) -> None:
    check_docs = _load_check_docs()
    markdown = tmp_path / "README.md"
    markdown.write_text("Released under the repository's MIT license.\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nlicense = "Apache-2.0"\n', encoding="utf-8")
    (tmp_path / "LICENSE").write_text("Apache License\nVersion 2.0\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)

    assert check_docs.license_consistency_errors([markdown]) == [
        "README.md:1: repository license 'MIT' does not match Apache-2.0"
    ]
