from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "browser-smoke.yml"
SCRIPT = ROOT / "scripts" / "browser_smoke.mjs"
PACKAGE = ROOT / "package.json"
PACKAGE_LOCK = ROOT / "package-lock.json"


def test_browser_smoke_workflow_uses_locked_browser_dependencies() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    package_lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))

    assert "npm ci --ignore-scripts --fund=false --audit=false" in workflow
    assert package["private"] is True
    assert package["devDependencies"] == {
        "@axe-core/playwright": "4.10.2",
        "playwright": "1.54.1",
    }
    assert package_lock["packages"][""]["devDependencies"] == package["devDependencies"]
    assert "playwright install --with-deps chromium" in workflow


def test_browser_smoke_workflow_uses_pinned_actions_and_read_only_permissions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert re.search(r"actions/checkout@[0-9a-f]{40}\s+# v5\b", workflow)
    assert re.search(r"actions/setup-python@[0-9a-f]{40}\s+# v5\.6\.0\b", workflow)
    assert re.search(r"actions/setup-node@[0-9a-f]{40}\s+# v4\.4\.0\b", workflow)
    assert "permissions:\n  contents: read" in workflow


def test_browser_smoke_script_exercises_viewer_security_and_accessibility_boundaries() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    for required in (
        "access_token",
        "HttpOnly",
        "partialRunId",
        "AxeBuilder",
        "serious",
        "critical",
        "390",
        "non-executable",
        "fixture",
    ):
        assert required in script

    assert 'waitUntil: "networkidle"' not in script
    assert script.count('waitUntil: "domcontentloaded"') == 2


def test_browser_smoke_script_starts_only_a_loopback_viewer() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'create_viewer_server("127.0.0.1", 0' in script
    assert "0.0.0.0" not in script
    assert "localhost" not in script
