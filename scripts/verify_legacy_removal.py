#!/usr/bin/env python3
"""Verify the fail-closed legacy-executor removal gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents_portable.transition_verifier import (
    DEFAULT_TRUSTED_SIGNERS,
    HmacSha256AttestationVerifier,
    load_hmac_trust_roots,
    verify_legacy_removal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--evidence-index", default="evidence/legacy-removal-evidence.v1.json")
    parser.add_argument("--trusted-signer", action="append", dest="trusted_signers")
    parser.add_argument(
        "--hmac-trust-roots",
        type=Path,
        help="Strict signed-JSON HMAC trust-root file supplied by release automation",
    )
    parser.add_argument("--max-age-days", type=int, default=30)
    expectation = parser.add_mutually_exclusive_group()
    expectation.add_argument("--expect-blocked", action="store_true")
    expectation.add_argument("--require-removal-allowed", action="store_true")
    args = parser.parse_args()
    trust_roots = load_hmac_trust_roots(args.hmac_trust_roots) if args.hmac_trust_roots else {}
    trusted_signers = args.trusted_signers or (list(trust_roots) if trust_roots else DEFAULT_TRUSTED_SIGNERS)
    report = verify_legacy_removal(
        args.repo_root,
        evidence_index_path=args.evidence_index,
        trusted_signers=trusted_signers,
        trust_roots=trust_roots,
        attestation_verifier=HmacSha256AttestationVerifier() if trust_roots else None,
        max_age_days=args.max_age_days,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.expect_blocked:
        return 0 if not report["removal_allowed"] else 1
    return 0 if report["removal_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
