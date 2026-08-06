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


def test_architecture_posters_use_checked_in_sources() -> None:
    for name in ("system-overview", "portable-patterns", "research-quality"):
        assert (ROOT / "docs" / "renders" / f"{name}.html").is_file()
        assert (ROOT / "assets" / "architecture" / f"{name}.png").is_file()


def test_nested_image_link_target_is_validated(tmp_path, monkeypatch) -> None:
    check_docs = _load_check_docs()
    markdown = tmp_path / "README.md"
    (tmp_path / "preview.png").touch()
    markdown.write_text("[![Preview](preview.png)](missing.svg)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)

    assert check_docs.broken_links(markdown) == ["README.md: missing link target missing.svg"]
