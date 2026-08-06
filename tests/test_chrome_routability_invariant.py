from __future__ import annotations

from ipaddress import ip_address

import pytest

from stock_research_agents_host.adapters.chrome import _is_globally_routable_unicast


@pytest.mark.parametrize(
    "address",
    ("127.0.0.1", "10.0.0.1", "169.254.1.1", "224.0.0.1", "0.0.0.0", "::", "::1", "ff02::1", "fec0::1"),
)
def test_non_public_or_non_unicast_addresses_fail_closed(address: str) -> None:
    assert _is_globally_routable_unicast(ip_address(address)) is False


@pytest.mark.parametrize("address", ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"))
def test_known_global_unicast_addresses_are_accepted(address: str) -> None:
    assert _is_globally_routable_unicast(ip_address(address)) is True
