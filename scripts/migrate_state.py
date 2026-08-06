#!/usr/bin/env python3
"""Plan or apply a validated backup-first local state schema adoption."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stock_research_agents.state import StateLayout
from stock_research_agents.state_migrations import migrate_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=StateLayout.from_environment().root)
    parser.add_argument("--apply", action="store_true", help="Write the v1 state manifest after validation")
    parser.add_argument("--backup-dir", type=Path, help="Required outside-state backup path for existing state")
    arguments = parser.parse_args()
    report = migrate_state(arguments.state_dir, apply=arguments.apply, backup_dir=arguments.backup_dir)
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
