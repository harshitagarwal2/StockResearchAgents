"""Isolated research-data MCP surface; the coordination MCP remains unchanged."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from stock_research_agents._version import __version__
from stock_research_agents_host.adapters.providers.catalog import (
    CAPABILITY_SPECS,
    capability_spec,
    public_adapter_capabilities,
)
from stock_research_agents_host.adapters.public import PublicResearchDataAdapter, UrllibHTTPTransport
from stock_research_agents_host.contracts import (
    SOURCE_BATCH_VERSION,
    SourceQuery,
    validate_source_response,
)
from stock_research_agents_host.ports import SourcePort
from stock_research_agents_host.source_portfolio import SourcePortfolioCollector

try:
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Research-data MCP support requires the project's mcp dependency.") from exc

TOOL_NAMES = {
    "prices": "research_data_get_prices",
    "indicators": "research_data_get_indicators",
    "regulatory_filings": "research_data_get_regulatory_filings",
    "fundamentals": "research_data_get_fundamentals",
    "financial_statements": "research_data_get_financial_statements",
    "company_news": "research_data_get_company_news",
    "global_news": "research_data_get_global_news",
    "macro": "research_data_get_macro",
    "prediction_markets": "research_data_get_prediction_markets",
    "stocktwits": "research_data_get_stocktwits",
    "reddit": "research_data_get_reddit",
}
PORTFOLIO_TOOL_NAME = "research_data_collect_source_portfolio"
if set(TOOL_NAMES) != {spec.name for spec in CAPABILITY_SPECS}:  # pragma: no cover - import-time invariant
    raise RuntimeError("research-data MCP tools and the capability catalog must match exactly")
if PORTFOLIO_TOOL_NAME in TOOL_NAMES.values():  # pragma: no cover - import-time invariant
    raise RuntimeError("the source portfolio tool name must be distinct from SourceBatch tools")


@dataclass(frozen=True, slots=True)
class AdapterConformanceReceipt:
    receipt_id: str
    adapter_id: str
    source_batch_version: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.receipt_id or not self.adapter_id:
            raise ValueError("adapter conformance receipt identity is required")
        if self.source_batch_version != SOURCE_BATCH_VERSION:
            raise ValueError("adapter conformance receipt must cover SourceBatch v1")
        if not self.capabilities or set(self.capabilities) - set(TOOL_NAMES):
            raise ValueError("adapter conformance receipt capabilities are invalid")


PUBLIC_ADAPTER_RECEIPT = AdapterConformanceReceipt(
    receipt_id="public-adapters-source-batch-v1",
    adapter_id="PublicResearchDataAdapter",
    source_batch_version=SOURCE_BATCH_VERSION,
    capabilities=public_adapter_capabilities(),
)


class ResearchDataService:
    """Transport-neutral direct-Python surface used verbatim by MCP tools."""

    def __init__(self, adapter: SourcePort) -> None:
        self._adapter = adapter

    def execute(self, capability: str, fields: dict[str, object]) -> dict[str, object]:
        query = _query(capability, fields)
        return validate_source_response(capability, query, self._adapter.fetch(capability, query)).to_dict()


class SourcePortfolioService:
    """Terminal additive surface over explicitly configured provider routes."""

    def __init__(self, collector: SourcePortfolioCollector) -> None:
        self._collector = collector

    def execute(self, capability: str, fields: dict[str, object]) -> dict[str, object]:
        capability_spec(capability)
        route_ids = self._collector.route_ids(capability)
        if len(route_ids) < 2:
            raise ValueError("source portfolio collection requires at least two configured provider routes")
        return self._collector.collect(capability, _query(capability, fields)).to_dict()


def _query_id(capability: str, fields: dict[str, object]) -> str:
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return f"{capability}-{digest}"


def _query(capability: str, fields: dict[str, object]) -> SourceQuery:
    query_id = _query_id(capability, fields)
    payload = {"query_id": query_id, **fields}
    for field in (
        "form_types",
        "metrics",
        "statement_types",
        "periods",
        "topics",
        "series",
        "regions",
        "search_terms",
    ):
        if field in payload:
            value = payload[field]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{field} must be an array of strings")
            payload[field] = tuple(value)
    return capability_spec(capability).query_type(**payload)  # type: ignore[arg-type]


def create_server(
    adapter: SourcePort,
    receipts: tuple[AdapterConformanceReceipt, ...] = (),
    *,
    portfolio_collector: SourcePortfolioCollector | None = None,
) -> MCPServer:
    server = MCPServer(
        "StockResearchAgents Research Data",
        version=__version__,
        instructions="Read-only bounded research data. Authentication and provider selection remain host-owned.",
    )
    service = ResearchDataService(adapter)
    registered = {
        capability
        for receipt in receipts
        if receipt.adapter_id == type(adapter).__name__ and receipt.source_batch_version == SOURCE_BATCH_VERSION
        for capability in receipt.capabilities
    }
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

    def prices(symbol: str, start_time: str, end_time: str, interval: str) -> dict[str, object]:
        return service.execute(
            "prices", {"symbol": symbol, "start_time": start_time, "end_time": end_time, "interval": interval}
        )

    def indicators(
        symbol: str,
        indicator: str,
        start_time: str,
        end_time: str,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        return service.execute(
            "indicators",
            {
                "symbol": symbol,
                "indicator": indicator,
                "start_time": start_time,
                "end_time": end_time,
                "parameters": parameters,
            },
        )

    def regulatory_filings(
        issuer: str,
        jurisdiction: str,
        form_types: list[str],
        filed_after: str,
        filed_before: str,
    ) -> dict[str, object]:
        return service.execute(
            "regulatory_filings",
            {
                "issuer": issuer,
                "jurisdiction": jurisdiction,
                "form_types": form_types,
                "filed_after": filed_after,
                "filed_before": filed_before,
            },
        )

    def fundamentals(symbol: str, metrics: list[str], as_of: str) -> dict[str, object]:
        return service.execute("fundamentals", {"symbol": symbol, "metrics": metrics, "as_of": as_of})

    def financial_statements(
        issuer: str,
        statement_types: list[str],
        periods: list[str],
        as_of: str,
    ) -> dict[str, object]:
        return service.execute(
            "financial_statements",
            {"issuer": issuer, "statement_types": statement_types, "periods": periods, "as_of": as_of},
        )

    def company_news(
        symbol: str,
        published_after: str,
        published_before: str,
        max_items: int,
    ) -> dict[str, object]:
        return service.execute(
            "company_news",
            {
                "symbol": symbol,
                "published_after": published_after,
                "published_before": published_before,
                "max_items": max_items,
            },
        )

    def global_news(
        topics: list[str],
        published_after: str,
        published_before: str,
        max_items: int,
    ) -> dict[str, object]:
        return service.execute(
            "global_news",
            {
                "topics": topics,
                "published_after": published_after,
                "published_before": published_before,
                "max_items": max_items,
            },
        )

    def macro(
        series: list[str],
        regions: list[str],
        start_time: str,
        end_time: str,
        vintage_as_of: str,
    ) -> dict[str, object]:
        return service.execute(
            "macro",
            {
                "series": series,
                "regions": regions,
                "start_time": start_time,
                "end_time": end_time,
                "vintage_as_of": vintage_as_of,
            },
        )

    def prediction_markets(search_terms: list[str], as_of: str, max_items: int) -> dict[str, object]:
        return service.execute(
            "prediction_markets",
            {"search_terms": search_terms, "as_of": as_of, "max_items": max_items},
        )

    def stocktwits(symbol: str, start_time: str, end_time: str, max_items: int) -> dict[str, object]:
        return service.execute(
            "stocktwits",
            {"symbol": symbol, "start_time": start_time, "end_time": end_time, "max_items": max_items},
        )

    def reddit(symbol: str, start_time: str, end_time: str, max_items: int) -> dict[str, object]:
        return service.execute(
            "reddit",
            {"symbol": symbol, "start_time": start_time, "end_time": end_time, "max_items": max_items},
        )

    functions: dict[str, Any] = {
        "prices": prices,
        "indicators": indicators,
        "regulatory_filings": regulatory_filings,
        "fundamentals": fundamentals,
        "financial_statements": financial_statements,
        "company_news": company_news,
        "global_news": global_news,
        "macro": macro,
        "prediction_markets": prediction_markets,
        "stocktwits": stocktwits,
        "reddit": reddit,
    }
    for capability in TOOL_NAMES:
        if capability in registered:
            server.tool(
                name=TOOL_NAMES[capability],
                description=f"Return a canonical SourceBatch v1 for {capability}; accepts no credentials.",
                annotations=read,
            )(functions[capability])
    if portfolio_collector is not None:
        portfolio_service = SourcePortfolioService(portfolio_collector)

        def collect_source_portfolio(capability: str, fields: dict[str, object]) -> dict[str, object]:
            return portfolio_service.execute(capability, fields)

        server.tool(
            name=PORTFOLIO_TOOL_NAME,
            description=(
                "Return a terminal SourcePortfolioReceipt v1 across at least two explicitly configured routes; "
                "provider batches and entitlements remain separate."
            ),
            annotations=read,
        )(collect_source_portfolio)
    return server


def create_default_server() -> MCPServer:
    adapter = PublicResearchDataAdapter(UrllibHTTPTransport())
    return create_server(adapter, (PUBLIC_ADAPTER_RECEIPT,))


mcp = create_default_server()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
