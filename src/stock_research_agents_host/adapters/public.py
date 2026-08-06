"""Lawful public research adapter composed from typed provider strategies."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import cast
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from stock_research_agents_host.adapters.providers import (
    DeniedSocialProvider,
    GdeltProvider,
    LicensedMarketDataProvider,
    PolymarketProvider,
    SecProvider,
    WorldBankProvider,
)
from stock_research_agents_host.adapters.providers._base import (
    ADAPTER_VERSION as _ADAPTER_VERSION,
)
from stock_research_agents_host.adapters.providers._base import (
    HTTPResponse,
    HTTPTransport,
    ProviderPayloadError,
    ProviderSupport,
    ProviderTransportError,
    now,
)
from stock_research_agents_host.contracts import SourceBatch, SourceQuery
from stock_research_agents_host.ports import SourcePort
from stock_research_agents_host.source_router import ProviderSourceRouter, SourceProvider

SEC_USER_AGENT = "StockResearchAgents research adapter/0.1 (https://github.com/harshitagarwal2/StockResearchAgents)"
ADAPTER_VERSION = _ADAPTER_VERSION
MAX_HTTP_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_SEC_COMPANY_FACT_ITEMS = 1_000
_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
_CREDENTIAL_PARAM_PARTS = {"authorization", "cookie", "credential", "key", "password", "secret", "sig", "token"}


def _reject_credential_fields(fields: Mapping[str, object] | None, label: str) -> None:
    for key in fields or {}:
        normalized = str(key).lower().replace("-", "_")
        if any(part in _CREDENTIAL_PARAM_PARTS for part in normalized.split("_")):
            raise ValueError(f"public transport {label} cannot contain credential fields")


def _read_http_body(response: object) -> bytes:
    reader = getattr(response, "read", None)
    if not callable(reader):
        raise ProviderTransportError("public provider response body is unreadable")
    try:
        body = reader(MAX_HTTP_RESPONSE_BYTES + 1)
    except TypeError as exc:
        raise ProviderTransportError("public provider response body does not support bounded reads") from exc
    if not isinstance(body, bytes | bytearray):
        raise ProviderTransportError("public provider response body must be bytes")
    if len(body) > MAX_HTTP_RESPONSE_BYTES:
        raise ProviderTransportError("public provider response body exceeds the bounded size limit")
    return bytes(body)


class UrllibHTTPTransport:
    """Small default transport; credentials are intentionally unsupported."""

    def __init__(
        self,
        *,
        operator_identity: str = SEC_USER_AGENT,
        max_attempts: int = 3,
        backoff_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not operator_identity.strip() or "(" not in operator_identity or ")" not in operator_identity:
            raise ValueError("operator_identity must descriptively identify the host and a contact")
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not 0 <= backoff_seconds <= 1:
            raise ValueError("backoff_seconds must be between 0 and 1 second")
        self._operator_identity = operator_identity
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    @property
    def operator_identity(self) -> str:
        return self._operator_identity

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HTTPResponse:
        _reject_credential_fields(params, "parameters")
        _reject_credential_fields(headers, "headers")
        target = f"{url}?{urlencode(params)}" if params else url
        request = Request(target, headers={"User-Agent": self._operator_identity, **dict(headers or {})})
        for attempt in range(self._max_attempts):
            try:
                with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS provider URLs
                    result = HTTPResponse(
                        response.status, json.loads(_read_http_body(response)), dict(response.headers)
                    )
            except HTTPError as exc:
                try:
                    result = HTTPResponse(exc.code, None, dict(exc.headers or {}))
                finally:
                    exc.close()
            if result.status not in _RETRYABLE_HTTP_STATUSES or attempt + 1 == self._max_attempts:
                return result
            self._sleep(self._backoff_seconds * (2**attempt))
        raise AssertionError("bounded retry loop did not return")


class PublicResearchDataAdapter:
    """One SourcePort composed from explicit, typed provider strategies."""

    def __init__(
        self,
        transport: HTTPTransport,
        *,
        licensed_source: SourcePort | None = None,
        reddit_oauth_source: SourcePort | None = None,
        sec_user_agent: str | None = None,
        clock: Callable[[], str] = now,
    ) -> None:
        operator_identity = (
            sec_user_agent if sec_user_agent is not None else getattr(transport, "operator_identity", SEC_USER_AGENT)
        )
        if not operator_identity.strip() or "(" not in operator_identity or ")" not in operator_identity:
            raise ValueError("SEC User-Agent must descriptively identify the host and a contact")
        support = ProviderSupport(transport, operator_identity, clock)
        providers = cast(
            tuple[SourceProvider, ...],
            (
                LicensedMarketDataProvider(licensed_source, support),
                DeniedSocialProvider(reddit_oauth_source, support),
                SecProvider(support, max_company_fact_items=MAX_SEC_COMPANY_FACT_ITEMS),
                GdeltProvider(support),
                PolymarketProvider(support),
                WorldBankProvider(support),
            ),
        )
        self._router = ProviderSourceRouter(providers)
        self._support = support

    @property
    def capabilities(self) -> frozenset[str]:
        return self._router.capabilities()

    def fetch(self, capability: str, query: SourceQuery) -> SourceBatch:
        try:
            return self._router.fetch(capability, query)
        except (ProviderTransportError, ProviderPayloadError) as exc:
            return self._support.terminal(
                capability, query, "unavailable", f"Provider response unavailable: {type(exc).__name__}."
            )
