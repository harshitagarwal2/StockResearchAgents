#!/usr/bin/env python3
"""Run the credential-free scoped differential against the pinned upstream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents_portable.oracle_semantics import run_semantic_differential


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-path", required=True)
    parser.add_argument("--portable-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output")
    parser.add_argument(
        "--require-clean-portable",
        action="store_true",
        help="Fail unless the compared portable checkout is clean and eligible as release evidence.",
    )
    args = parser.parse_args()
    report = run_semantic_differential(
        upstream_path=args.upstream_path,
        portable_root=args.portable_root,
    )
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.passed and (not args.require_clean_portable or report.release_evidence_eligible) else 1


if __name__ == "__main__":
    raise SystemExit(main())
