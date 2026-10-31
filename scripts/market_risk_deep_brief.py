#!/usr/bin/env python3
"""Build the Market Risk deep brief for an instant — read-only, nothing written, nothing sent.

  # the fact pack and the deterministic brief for now (production reader, SELECT-only):
  python3 scripts/market_risk_deep_brief.py
  # replay an instant (the engine is evaluated at that instant first; the brief is built from that assessment):
  python3 scripts/market_risk_deep_brief.py --as-of 2026-10-29T22:15:00Z --json
  # show the prose path with a stubbed model (no model is called; the stub's text is validated like a real answer):
  python3 scripts/market_risk_deep_brief.py --as-of 2026-10-29T22:15:00Z --stub-model draft.txt

The live send path is the evaluator (scripts/market_risk_evaluate.py --apply), which calls the brief after the
initial cards. This script never calls a model and never sends. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import deep_brief, scoring  # noqa: E402
from scripts.lib.market_risk.deep_brief_facts import PgSources, build_fact_pack, load_config  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", help="ISO-8601 instant")
    ap.add_argument("--fixture", help="fixture directory (replay without a DB)")
    ap.add_argument("--overlay")
    ap.add_argument("--stub-model", help="file whose text stands in for the model's answer (validated, never sent)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    now = scoring._parse(a.as_of) if a.as_of else datetime.now(timezone.utc)
    if now is None:
        ap.error("--as-of is not ISO-8601")
    import market_risk_evaluate as ev

    policy = load_policy()
    if a.fixture:
        from scripts.lib.market_risk.fixture_reader import FixtureReader

        reader, sources = FixtureReader(a.fixture, overlay=a.overlay), None
    else:
        from scripts.lib.market_risk.reader import PgReader

        reader = PgReader()
        sources = PgSources(reader)
    doc = ev.evaluate(now, reader, policy, None, None).to_dict()
    cfg = load_config()
    pack = build_fact_pack(now, reader, doc, sources=sources, cfg=cfg)
    stub = None
    if a.stub_model:
        txt = Path(a.stub_model).read_text(encoding="utf-8")
        stub = lambda prompt, timeout_s: (txt, "stub")  # noqa: E731
    brief = deep_brief.write(pack, call_model=stub, cfg=cfg)
    if a.as_json:
        print(json.dumps({"assessment_tier": doc.get("tier"), "pack": pack, "brief": brief}, indent=2, default=str))
    else:
        print(brief["text"])
        print(f"\n[curated={brief['curated']} reason={brief['reason']}]")
        if brief.get("validation"):
            print(json.dumps(brief["validation"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
