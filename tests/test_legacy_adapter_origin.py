from __future__ import annotations

import sys
import types

import pytest

from tradingagents_portable.errors import CapabilitySetupError
from tradingagents_portable.legacy import LegacyTradingAgentsAdapter


def test_explicit_legacy_path_rejects_an_already_loaded_different_checkout(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested_root = tmp_path / "requested"
    (requested_root / "tradingagents").mkdir(parents=True)
    other_root = tmp_path / "other" / "tradingagents"
    other_root.mkdir(parents=True)

    loaded_package = types.ModuleType("tradingagents")
    loaded_package.__file__ = str(other_root / "__init__.py")
    monkeypatch.setitem(sys.modules, "tradingagents", loaded_package)

    adapter = LegacyTradingAgentsAdapter(legacy_path=str(requested_root))
    with pytest.raises(CapabilitySetupError, match="different tradingagents package") as captured:
        adapter._activate_legacy_path()

    assert str(other_root) in captured.value.guidance.message
    assert str(requested_root) in captured.value.guidance.message


def test_explicit_legacy_path_is_promoted_ahead_of_installed_packages(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested_root = tmp_path / "requested"
    (requested_root / "tradingagents").mkdir(parents=True)
    root_string = str(requested_root.resolve())
    monkeypatch.delitem(sys.modules, "tradingagents", raising=False)
    monkeypatch.setattr("sys.path", ["/installed", root_string, "/other"])

    LegacyTradingAgentsAdapter(legacy_path=root_string)._activate_legacy_path()

    assert sys.path == [root_string, "/installed", "/other"]


def test_resolve_subject_propagates_normalization_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LegacyTradingAgentsAdapter()
    symbol_module = types.SimpleNamespace(normalize_symbol=lambda _raw: (_ for _ in ()).throw(ValueError("bad symbol")))
    monkeypatch.setattr("tradingagents_portable.legacy.importlib.import_module", lambda _name: symbol_module)

    with pytest.raises(ValueError, match="bad symbol"):
        adapter.resolve_subject("not valid")


def test_resolve_subject_does_not_hide_import_errors_from_the_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LegacyTradingAgentsAdapter()

    def broken_normalizer(_raw: str) -> str:
        raise ImportError("normalizer dependency failed")

    symbol_module = types.SimpleNamespace(normalize_symbol=broken_normalizer)
    monkeypatch.setattr("tradingagents_portable.legacy.importlib.import_module", lambda _name: symbol_module)

    with pytest.raises(ImportError, match="normalizer dependency failed"):
        adapter.resolve_subject("ORCL")


def test_resolve_subject_falls_back_only_when_symbol_module_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LegacyTradingAgentsAdapter()

    def missing_module(_name: str) -> object:
        raise ModuleNotFoundError(
            "symbol utilities unavailable",
            name="tradingagents.dataflows.symbol_utils",
        )

    monkeypatch.setattr("tradingagents_portable.legacy.importlib.import_module", missing_module)

    assert adapter.resolve_subject(" orcl ") == ("ORCL", "stock")


def test_resolve_subject_propagates_missing_transitive_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LegacyTradingAgentsAdapter()

    def missing_dependency(_name: str) -> object:
        raise ModuleNotFoundError("dependency unavailable", name="upstream_optional_dependency")

    monkeypatch.setattr("tradingagents_portable.legacy.importlib.import_module", missing_dependency)

    with pytest.raises(ModuleNotFoundError, match="dependency unavailable"):
        adapter.resolve_subject("ORCL")
