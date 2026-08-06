from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "examples" / "generated" / "orcl-fixture"


def test_fixture_demo_is_reproducible_and_visibly_non_executable(tmp_path: Path) -> None:
    generated = tmp_path / "demo"

    subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned generator
        [sys.executable, str(ROOT / "scripts" / "generate_fixture_demo.py"), "--output-dir", str(generated)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    expected_files = {"events.json", "manifest.json", "preview.svg", "result.json", "view.json"}
    assert {path.name for path in generated.iterdir()} == expected_files
    assert {path.name for path in COMMITTED.iterdir()} == expected_files
    for name in expected_files:
        assert (generated / name).read_bytes() == (COMMITTED / name).read_bytes()

    preview = (generated / "preview.svg").read_text(encoding="utf-8")
    assert "FIXTURE DATA" in preview
    assert "NON-EXECUTABLE ANALYTICAL SCENARIO" in preview
    manifest = json.loads((generated / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fixture"] is True
    assert manifest["non_executable"] is True
    assert manifest["files"] == sorted(expected_files - {"manifest.json"})
