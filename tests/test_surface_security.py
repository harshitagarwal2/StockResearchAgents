from __future__ import annotations

import inspect

import pytest

from stock_research_agents import mcp_server
from stock_research_agents.contracts import reject_secret_shaped_keys


@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "sentinel"},
        {"provider": {"access-token": "sentinel"}},
        {"nested": [{"authorization": "Bearer sentinel"}]},
        {"settings": {"privateKey": "sentinel"}},
        {"cookie_jar": {"session": "sentinel"}},
    ],
)
def test_secret_shaped_keys_are_rejected_recursively(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="credential-shaped config key is forbidden"):
        reject_secret_shaped_keys(payload)


def test_financial_authorization_field_is_not_misclassified_as_a_credential() -> None:
    reject_secret_shaped_keys(
        {"new_repurchase_authorization_usd_bn": 50, "regulatory_authorization_status": "approved"}
    )


def test_public_mcp_tools_do_not_accept_credentials() -> None:
    forbidden = {"api_key", "authorization", "cookie", "credential", "password", "secret", "token"}
    for tool in mcp_server.create_server()._tool_manager.list_tools():
        assert not set(inspect.signature(getattr(mcp_server, tool.name)).parameters).intersection(forbidden)
