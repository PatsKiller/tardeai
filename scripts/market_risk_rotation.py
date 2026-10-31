#!/usr/bin/env python3
"""Where leadership is moving: the rotation advisor's CLI (dry run by default).

Operator 2026-10-31, verbatim: "if stuff is turning for the long term, I should have advisement of what I should be
getting into". Reads (read-only) the daily bars through the engine's PgReader, the CIO opportunity projection, the
current holdings file and the market-risk snapshot's tier; prints the advisory payload and the card. ``--apply`` sends
the P2 card only when ``leadership.card_enabled`` is true in policy AND the leadership signature changed since the last
sent card (state under the persistent state root); otherwise it says why it did not send. Never a size, weight, price,
order or stop (``MBI_BEHAVIOR = 0``).

  python3 scripts/market_risk_rotation.py [--json] [--apply]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib.market_risk import contract as c  # noqa: E402
from scripts.lib.market_risk import leadership, rotation_advice  # noqa: E402
from scripts.lib.market_risk.policy import load_policy  # noqa: E402


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")


def load_holdings(path: Path) -> list[dict]:
    """Current holdings (the file Home reads). Market value = shares x price when the row has no market_value."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for h in doc.get("holdings") or []:
        if not isinstance(h, dict) or not h.get("symbol"):
            continue
        sh = h.get("shares") or h.get("quantity") or 0
        px = h.get("current_price") or h.get("price") or 0
        try:
            mv = float(h.get("market_value") or (float(sh) * float(px)))
        except (TypeError, ValueError):
            mv = 0.0
        out.append({"symbol": str(h["symbol"]).upper(), "sector": h.get("sector"), "market_value": mv})
    return out


def current_tier(root: Path) -> str | None:
    from scripts.lib.market_risk_projection import SNAPSHOT_REL

    try:
        return json.loads((root / SNAPSHOT_REL).read_text(encoding="utf-8")).get("tier")
    except (OSError, ValueError):
        return None


def earnings_map(reader, now: datetime, sessions: int) -> dict[str, str]:
    try:
        rows = reader.earnings_calendar(start=now, end=now + timedelta(days=int(sessions * 1.5)), now=now)
    except Exception as exc:  # noqa: BLE001 — an unreadable calendar is reported, never fatal
        print(f"market_risk_rotation: earnings calendar unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return {}
    return {str(r.get("symbol")).upper(): str(r.get("earnings_date") or r.get("date"))[:10] for r in rows or []}


def build(now: datetime, reader, policy: dict, root: Path) -> dict:
    ctx = c.EvalContext(now=now, reader=reader, policy=policy)
    block = leadership.measure(ctx)
    if block.get("state") != "evaluated":
        return {"state": "UNKNOWN", "leadership": block}
    cfg = policy.get("leadership") or {}
    payload = rotation_advice.advise(
        block,
        policy=policy,
        tier=current_tier(root),
        candidates=rotation_advice.load_candidates(root / "data" / "cio" / "cio_opportunity_projection.json"),
        holdings=load_holdings(root / "data" / "portfolios" / "state" / "holdings.json"),
        earnings=earnings_map(reader, now, int(cfg.get("earnings_window_sessions") or 10)),
    )
    tr = ROOT / str(cfg.get("track_record_path") or "")
    try:
        payload["track_record"] = json.loads(tr.read_text(encoding="utf-8")).get("summary")
    except (OSError, ValueError):
        payload["track_record"] = None
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="send the card when enabled and changed")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    policy = load_policy()
    from scripts.lib.market_risk.reader import PgReader

    root = state_root()
    payload = build(datetime.now(timezone.utc), PgReader(), policy, root)
    if payload.get("state") == "UNKNOWN":
        print(json.dumps(payload, indent=2, default=str))
        return 3
    print(json.dumps(payload, indent=2, default=str) if a.json else rotation_advice.render_card(payload))
    cfg = policy.get("leadership") or {}
    state_file = root / "data" / "runtime" / "market_risk" / "rotation_state.json"
    sig = rotation_advice.signature(payload)
    try:
        last = json.loads(state_file.read_text(encoding="utf-8")).get("signature")
    except (OSError, ValueError):
        last = None
    if not a.apply:
        print(
            f"DRY RUN: would {'send' if cfg.get('card_enabled') and sig != last else 'not send'} "
            f"(card_enabled={bool(cfg.get('card_enabled'))}, changed={sig != last})",
            file=sys.stderr,
        )
        return 0
    if not cfg.get("card_enabled"):
        print("not sent: leadership.card_enabled is false (operator decision; no demonstrated edge)", file=sys.stderr)
        return 0
    if sig == last:
        print("not sent: leadership signature unchanged", file=sys.stderr)
        return 0
    ok = rotation_advice.send_card(payload, policy)
    if not ok:
        print("send failed", file=sys.stderr)
        return 1
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"signature": sig, "sent_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    os.replace(tmp, state_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
