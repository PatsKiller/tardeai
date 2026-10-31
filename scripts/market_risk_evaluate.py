#!/usr/bin/env python3
"""Market Risk Engine evaluator (DSN-20261031-market-risk-engine P2-T1).

  # what the engine says now, from the production reader (default: dry run, nothing written):
  python3 scripts/market_risk_evaluate.py
  # replay an instant from a fixture directory (one JSON list per DataReader method, e.g. fred.json):
  python3 scripts/market_risk_evaluate.py --fixture tests/fixtures/market_risk/x --as-of 2026-10-29T22:15:00Z --json
  # write the assessment (latest.json + a dated receipt) under persistent-state data/runtime/market_risk/:
  python3 scripts/market_risk_evaluate.py --apply

Advisory only (MBI_BEHAVIOR = 0). No sends here: alerting is a separate module that reads the assessment. The DB
table waits for the §7A registry grant; until then --apply writes JSON atomically. Exit codes: 0 ok, 2 no reader.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402
from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk import explain, registry, scoring  # noqa: E402
from scripts.lib.market_risk.policy import POLICY_PATH, load_policy  # noqa: E402

ET = ZoneInfo("America/New_York")


def state_dir() -> Path:
    root = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")
    return root / "data" / "runtime" / "market_risk"


def session_of(now: datetime) -> str:
    et = now.astimezone(ET)
    if et.weekday() >= 5:
        return "closed"
    hm = et.hour * 60 + et.minute
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "regular"
    if 16 * 60 <= hm < 20 * 60:
        return "afterhours"
    return "closed"


class FixtureReader:
    """Replay reader over ``<dir>/<method>.json`` lists. Rows newer than ``end`` are never returned."""

    def __init__(self, directory: Path | str):
        self.dir = Path(directory)
        if not self.dir.is_dir():
            raise FileNotFoundError(f"fixture directory not found: {self.dir}")

    def _rows(self, name: str, end: datetime | None = None, symbols: Iterable[str] | None = None) -> list[dict]:
        f = self.dir / f"{name}.json"
        rows = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        want = {s.upper() for s in symbols} if symbols else None
        out = []
        for r in rows:
            if (
                want is not None
                and str(r.get("symbol", "")).upper() not in want
                and str(r.get("series", "")).upper() not in want
            ):
                continue
            at = scoring._parse(r.get("as_of") or r.get("observed_at") or r.get("date"))
            if end is not None and at is not None and at > end:
                continue
            out.append(r)
        return out

    def quotes(self, symbols, *, start, end):
        return [r for r in self._rows("quotes", end, symbols) if (scoring._parse(r.get("as_of")) or end) >= start]

    def daily_bars(self, symbols, *, sessions, end):
        return self._rows("daily_bars", end, symbols)

    def regime_indicators(self, *, end):
        return self._rows("regime_indicators", end)

    def fred(self, series, *, observations, end):
        return self._rows("fred", end, series)

    def option_snapshots(self, symbols, *, sessions, end):
        return self._rows("option_snapshots", end, symbols)

    def sector_states(self, *, end):
        return self._rows("sector_states", end)

    def earnings_calendar(self, *, start, end):
        return self._rows("earnings_calendar")

    def macro_calendar(self, *, start, end):
        return self._rows("macro_calendar")


def production_reader() -> Any:
    try:
        from scripts.lib.market_risk.reader import PgReader  # builder H
    except ImportError as exc:
        raise SystemExit(
            f"market_risk_evaluate: production reader scripts.lib.market_risk.reader.PgReader is not available ({exc}); "
            "use --fixture DIR for a replay. Refusing to evaluate on an empty reader."
        ) from None
    return PgReader()


def evaluate(now: datetime, reader: Any, policy: dict, prior: dict | None, portfolio: c.PortfolioContext | None = None):
    ctx = c.EvalContext(now=now, reader=reader, policy=policy, session=session_of(now))
    obs = registry.evaluate_all(ctx)
    a = scoring.compose(obs, policy, prior=prior, now=now)
    a = scoring.apply_uplift(a, portfolio, policy)
    a = explain.explain(a, policy)
    return a


def _read_prior(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write latest.json + dated receipt")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--as-of", help="ISO-8601 instant to evaluate (replay)")
    ap.add_argument("--fixture", help="fixture directory for a replay reader")
    ap.add_argument("--prior", help="prior assessment JSON (default: latest.json when not replaying)")
    ap.add_argument("--policy", default=str(POLICY_PATH))
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    apply = a.apply and not a.dry_run
    now = scoring._parse(a.as_of) if a.as_of else datetime.now(timezone.utc)
    if now is None:
        ap.error(f"--as-of {a.as_of!r} is not ISO-8601")
    policy = load_policy(a.policy)
    try:
        reader = FixtureReader(a.fixture) if a.fixture else production_reader()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    prior_path = Path(a.prior) if a.prior else (None if a.as_of else state_dir() / "latest.json")
    prior = _read_prior(prior_path) if prior_path else None
    assessment = evaluate(now, reader, policy, prior)
    doc = assessment.to_dict()
    doc["mode"] = "apply" if apply else "dry_run"
    doc["session"] = session_of(now)
    if apply:
        d = state_dir()
        stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        atomic_write_json(d / "receipts" / f"{stamp}.json", doc)
        atomic_write_json(d / "latest.json", doc)
        doc["written"] = str(d / "latest.json")
    if a.as_json:
        print(json.dumps(doc, indent=2, default=str))
    else:
        print(f"[market-risk] {doc['mode']} as_of {doc['as_of']} session {doc['session']}")
        for line in explain.card_lines(assessment):
            print("  " + line)
        print(
            f"  hysteresis: raw {assessment.hysteresis.get('raw_tier')} -> {assessment.tier} "
            f"(bootstrap={assessment.hysteresis.get('bootstrap')})"
        )
        if apply:
            print(f"  wrote {doc['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
