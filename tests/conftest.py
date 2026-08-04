from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if "STOCKRESEARCHAGENTS_STATE_DIR" not in os.environ:
    _ISOLATED_STATE_DIR = Path(tempfile.mkdtemp(prefix="stockresearchagents-pytest-"))
    os.environ["STOCKRESEARCHAGENTS_STATE_DIR"] = str(_ISOLATED_STATE_DIR)
    atexit.register(shutil.rmtree, _ISOLATED_STATE_DIR, ignore_errors=True)
