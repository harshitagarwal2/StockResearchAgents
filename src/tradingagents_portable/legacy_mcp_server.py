"""Explicit opt-in MCP compatibility server for upstream TradingAgentsGraph.

This module is intentionally not referenced by the Codex plugin manifest. It
exists only for consumers that knowingly choose the provider-backed legacy
runtime and its environment-owned credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import RunRequest, reject_secret_shaped_keys, sanitize_legacy_config
from .errors import CapabilitySetupError
from .legacy import LegacyTradingAgentsAdapter
from .mcp_server import _annotations, _completed_publication_response, create_server


def _reject_secret_shaped_keys(value: object, path: tuple[str, ...] = ()) -> None:
    reject_secret_shaped_keys(value, path)


def _safe_legacy_config(config: Mapping[str, object] | None) -> dict[str, object]:
    return sanitize_legacy_config(config)


def _request(
    symbol: str,
    as_of_date: str,
    analysts: list[str] | None,
    debate_rounds: int,
    risk_rounds: int,
    executor: str,
    asset_type: str = "stock",
    checkpoint_enabled: bool = False,
    legacy_config: Mapping[str, object] | None = None,
    output_language: str = "English",
) -> RunRequest:
    if asset_type not in {"stock", "crypto"}:
        raise ValueError("asset_type must be 'stock' or 'crypto'")
    return RunRequest(
        symbol=symbol,
        as_of_date=as_of_date,
        asset_type=asset_type,  # type: ignore[arg-type]
        analysts=tuple(
            analysts
            if analysts is not None
            else (
                ("market", "social", "news") if asset_type == "crypto" else ("market", "social", "news", "fundamentals")
            )
        ),
        debate_rounds=debate_rounds,
        risk_rounds=risk_rounds,
        output_language=output_language,
        executor=executor,  # type: ignore[arg-type]
        checkpoint_enabled=checkpoint_enabled,
        legacy_config=_safe_legacy_config(legacy_config),
    )


def run_legacy(
    symbol: str,
    as_of_date: str,
    asset_type: str = "auto",
    analysts: list[str] | None = None,
    debate_rounds: int | None = None,
    risk_rounds: int | None = None,
    checkpoint_enabled: bool | None = None,
    legacy_path: str | None = None,
    llm_provider: str | None = None,
    deep_think_llm: str | None = None,
    quick_think_llm: str | None = None,
    backend_url: str | None = None,
    output_language: str | None = None,
    temperature: float | None = None,
    llm_max_retries: int | None = None,
    google_thinking_level: str | None = None,
    openai_reasoning_effort: str | None = None,
    anthropic_effort: str | None = None,
    report_output_path: str | None = None,
) -> dict[str, Any]:
    """Delegate upstream with typed non-secret config; credentials come only from the environment."""
    try:
        adapter = LegacyTradingAgentsAdapter(legacy_path)
        canonical_symbol, resolved_asset_type = adapter.resolve_subject(symbol, asset_type)
        defaults = adapter.defaults()
        resolved_debate_rounds = debate_rounds if debate_rounds is not None else int(defaults["max_debate_rounds"])
        resolved_risk_rounds = risk_rounds if risk_rounds is not None else int(defaults["max_risk_discuss_rounds"])
        resolved_checkpoint = (
            checkpoint_enabled if checkpoint_enabled is not None else bool(defaults.get("checkpoint_enabled", False))
        )
        resolved_output_language = output_language or str(defaults.get("output_language", "English"))
        legacy_config = {
            "llm_provider": llm_provider,
            "deep_think_llm": deep_think_llm,
            "quick_think_llm": quick_think_llm,
            "backend_url": backend_url,
            "output_language": output_language,
            "temperature": temperature,
            "llm_max_retries": llm_max_retries,
            "google_thinking_level": google_thinking_level,
            "openai_reasoning_effort": openai_reasoning_effort,
            "anthropic_effort": anthropic_effort,
            "report_output_path": report_output_path,
        }
        request = _request(
            canonical_symbol,
            as_of_date,
            analysts,
            resolved_debate_rounds,
            resolved_risk_rounds,
            "legacy",
            resolved_asset_type,
            resolved_checkpoint,
            legacy_config,
            output_language=resolved_output_language,
        )
        result, events = adapter.run(request)
        return _completed_publication_response(result, events, store=adapter.store)
    except CapabilitySetupError as exc:
        return exc.to_dict()


def create_legacy_server():
    server = create_server(include_legacy_metadata=True)
    server.tool(
        name="run_legacy",
        description=(
            "Explicitly delegate to upstream TradingAgentsGraph with typed non-secret settings. "
            "Provider credentials are read from this opt-in server's environment."
        ),
        annotations=_annotations(read_only=False, idempotent=False, open_world=True),
    )(run_legacy)
    return server


mcp = create_legacy_server()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
