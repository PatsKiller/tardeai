#!/usr/bin/env python3
"""Market caps for the Market Risk Engine's index issuers (DSN-20261031-market-risk-engine, event category).

The engine measures earnings concentration over ``config/market_risk_policy.yaml`` ``event.index_universe`` (one
entry per issuer) and reads caps from ``fundamental_data`` metric ``MarketCap`` (``PgReader.index_weights``). That
metric is written by the EXISTING Finviz fundamentals writer
(``external_market_data_ingest.ingest_finviz_fundamentals``: stored Finviz through the data broker, zero provider
calls), whose weekly lane covers a different symbol list. This runner asks that same writer for the engine's issuers
once a day. No new store, provider or writer; caps never go to ``market_quotes`` (the latest-quote ledger).

Default is a dry run (reads and reports; writes nothing); ``--apply`` writes. Exit 2 when coverage of the universe is
below ``event.min_cap_coverage`` or a ``required_issuers`` name has no cap, so the lane's own receipt shows the gap.
AUTHORITY: READ_ONLY_ADVISORY. Market data only; never touches a broker account or an order route.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def event_policy() -> dict[str, Any]:
    from lib.market_risk.policy import load_policy

    return load_policy().get("event") or {}


def run(
    *,
    apply: bool,
    symbols: list[str] | None = None,
    ingest: Callable[..., dict] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ev = policy if policy is not None else event_policy()
    syms = symbols or [str(s).upper() for s in ev.get("index_universe") or []]
    if ingest is None:
        import external_market_data_ingest as x

        ingest = x.ingest_finviz_fundamentals
    # The Finviz cache keys some issuers by another ticker form (BRK.B -> BRK-B): request the cache key, report the issuer.
    to_key = {v.upper(): k.upper() for k, v in (ev.get("issuer_aliases") or {}).items() if "-" in k}
    keys = [to_key.get(s, s) for s in syms]
    res = ingest(keys, limit=max(len(keys), 1), dry_run=not apply)
    per = res.get("symbols") or {}
    caps = {s: (per.get(to_key.get(s, s)) or {}).get("metrics", {}).get("MarketCap") for s in syms}
    have = {s: float(v) for s, v in caps.items() if v}
    floor = float(ev.get("min_cap_coverage", 0.8))
    required = [str(u).upper() for u in ev.get("required_issuers") or []]
    total = sum(have.values())
    out = {
        "apply": apply,
        "writer": "external_market_data_ingest.ingest_finviz_fundamentals -> fundamental_data",
        "universe": len(syms),
        "with_cap": len(have),
        "coverage": round(len(have) / len(syms), 3) if syms else 0.0,
        "coverage_floor": floor,
        "required_missing": sorted(set(required) - set(have)),
        "missing": sorted(set(syms) - set(have)),
        "top": [
            {"symbol": s, "cap_bn": round(v / 1e9, 1), "weight": round(v / total, 4)}
            for s, v in sorted(have.items(), key=lambda kv: -kv[1])[:10]
        ],
        "rows_written": int(res.get("rows") or 0) if apply else 0,
        "provider_calls": int(res.get("provider_calls") or 0),
    }
    out["ok"] = out["coverage"] >= floor and not out["required_missing"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write fundamental_data rows (default: dry run)")
    ap.add_argument("--dry-run", action="store_true", help="default; overrides --apply")
    ap.add_argument("--universe", help="comma-separated symbols instead of the policy's event.index_universe")
    a = ap.parse_args(argv)
    syms = [s.strip().upper() for s in a.universe.split(",") if s.strip()] if a.universe else None
    out = run(apply=bool(a.apply) and not a.dry_run, symbols=syms)
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
