from __future__ import annotations

import inspect
import json

import pytest

from tradingagents_portable.capabilities import feature_matrix
from tradingagents_portable.contracts import RunRequest
from tradingagents_portable.mcp_server import (
    _reject_secret_shaped_keys,
    _request,
    _safe_legacy_config,
    run_legacy,
)


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
def test_secret_shaped_config_keys_are_rejected_recursively(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="credential-shaped config key is forbidden"):
        _reject_secret_shaped_keys(payload)


def test_legacy_config_is_allowlisted_and_omits_unset_values() -> None:
    assert _safe_legacy_config({"llm_provider": "openai", "temperature": None}) == {"llm_provider": "openai"}
    with pytest.raises(ValueError, match="unsupported legacy config keys"):
        _safe_legacy_config({"results_dir": "/tmp/not-public"})


@pytest.mark.parametrize(
    "payload",
    [
        {"backend_url": "https://user:password@example.test/v1"},
        {"backend_url": "https://example.test/v1?token=sentinel"},
        {"backend_url": "file:///tmp/provider.sock"},
        {"llm_max_retries": -1},
        {"temperature": 3},
    ],
)
def test_typed_legacy_values_reject_credential_or_unsafe_shapes(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _safe_legacy_config(payload)


def test_public_legacy_tool_exposes_typed_non_secret_arguments() -> None:
    parameters = inspect.signature(run_legacy).parameters
    assert "asset_type" in parameters
    assert "llm_provider" in parameters
    assert "deep_think_llm" in parameters
    assert "legacy_config" not in parameters
    assert "legacy_config_json" not in parameters
    assert not set(parameters).intersection({"api_key", "authorization", "credential", "password", "secret", "token"})


def test_safe_request_never_serializes_environment_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "DO_NOT_PERSIST_CREDENTIAL_SENTINEL"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    request = _request(
        "ORCL",
        "2026-07-03",
        None,
        1,
        1,
        "legacy",
        legacy_config={"llm_provider": "openai", "deep_think_llm": "gpt-test"},
    )
    assert sentinel not in json.dumps(request.to_dict())


def test_request_rejects_unknown_asset_type() -> None:
    with pytest.raises(ValueError, match="asset_type"):
        _request("ORCL", "2026-07-03", None, 1, 1, "legacy", asset_type="forex")


def test_crypto_default_and_explicit_analysts_exclude_fundamentals() -> None:
    default_request = _request("BTC-USD", "2026-07-03", None, 1, 1, "legacy", asset_type="crypto")
    explicit_request = RunRequest(
        symbol="BTC-USD",
        asset_type="crypto",
        executor="legacy",
        analysts=("fundamentals", "market", "social", "news"),
    )

    assert default_request.analysts == ("market", "social", "news")
    assert explicit_request.analysts == ("market", "social", "news")


@pytest.mark.parametrize(
    "config",
    [
        {"api_key": "sentinel"},
        {"llm_provider": {"nested_token": "sentinel"}},
        {"results_dir": "/tmp/not-public"},
        {"llm_provider": {"name": "openai"}},
    ],
)
def test_python_run_request_enforces_config_boundary(config: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RunRequest(executor="legacy", legacy_config=config)


def test_validated_python_config_cannot_be_mutated_after_construction() -> None:
    request = RunRequest(executor="legacy", legacy_config={"llm_provider": "openai"})

    with pytest.raises(TypeError, match="legacy_config is immutable"):
        request.legacy_config["api_key"] = "sentinel"


def test_executor_readiness_does_not_claim_unverified_features_supported() -> None:
    matrix = feature_matrix(legacy_path="/definitely/not/a/tradingagents/repository")
    features = {feature.name: feature.level.value for feature in matrix.features}
    assert features["orcl_fixture"] == "supported"
    assert features["legacy_adapter"] == "optional"
    assert features["legacy_full_topology"] == "optional"
    assert features["checkpoint_resume"] == "optional"
    assert features["live_stage_streaming"] == "unavailable"
    assert features["host_native_executor"] == "unavailable"
    assert features["run_cancellation"] == "unavailable"

    legacy = matrix.runtime_readiness["legacy_upstream"]
    assert legacy["result_mapping"] == "implemented_post_run"
    assert legacy["verification"] == "runtime_unverified"
    assert legacy["live_stage_streaming"] == "unavailable_without_upstream_observer_seam"
    assert legacy["checkpoint"] == "delegated_opt_in_runtime_unverified"
    assert legacy["cancellation"] == "unavailable"

    host = matrix.runtime_readiness["host_native"]
    assert host["implementation"] == "manifest_and_skill_only"
    assert host["verification"] == "not_implemented"
