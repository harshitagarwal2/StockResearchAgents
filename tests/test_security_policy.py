from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_secret_scan_runs_for_pushes_and_pull_requests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "secret-scan.yml").read_text(encoding="utf-8")

    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "gitleaks/gitleaks-action@v2" in workflow
    assert "fetch-depth: 0" in workflow


def test_security_policy_preserves_portable_authority_boundary() -> None:
    policy = " ".join((ROOT / "SECURITY.md").read_text(encoding="utf-8").lower().split())

    for forbidden_material in ("credentials", "cookies", "provider tokens", "broker authority"):
        assert forbidden_material in policy


def test_research_quality_discloses_model_level_temporal_contamination() -> None:
    quality = (ROOT / "docs" / "RESEARCH_QUALITY.md").read_text(encoding="utf-8").lower()

    assert "historically grounded simulation" in quality
    assert "model knowledge-cutoff declaration" in quality
