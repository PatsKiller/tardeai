#!/usr/bin/env python3
"""Build data/runtime/defense_engine_latest.json (DefenseProjection@v1) — design defense/v001.

Reads only: the Market Risk snapshot (built and book-joined exactly as GET /api/v2/market-risk/latest does),
the stored stops slice (DefenseStopsSlice@v1, data/runtime/defense_stops_slice_latest.json: the positions and
stop breakdown of cio_truth.resolve, written host-side by lib.defense_stops_slice), and the labelled side files
in data/runtime/. No broker call, no credential, no LLM, no order. The output is advisory and is refused if it
carries any size / order / share / level field (lib.defense_engine.assert_advisory).

Import boundary (n8n broker-reach gate, scripts/audit_lane_transitive_capabilities.py): this file must not import
cio_truth, holdings_document or db_adapter, even lazily -- their graph reaches schwab_position_sync. A host caller
that wants live stops resolves them itself (lib.defense_stops_slice.resolve_live) and passes ``truth=``.

    python3 scripts/defense_engine_build.py --dry-run      # print the projection, write nothing
    python3 scripts/defense_engine_build.py                # write the projection atomically

Intended lane: defense-engine-build, chained after each market-risk-evaluate (proposal only; not scheduled here).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import defense_engine as de  # noqa: E402

SIDE = {
    "stoplights": "inverse_stoplights_latest.json",
    "cash": "defense_cash_alternatives_latest.json",
    "recs": "defense_recommendations_latest.json",
    "sector_desk": "sector_momentum_latest.json",
    "industries": "industry_momentum_latest.json",
    "radar": "hedging_radar_latest.json",
    "options": "options_lifecycle_latest.json",
}
GAP_KEY = {"recs": "recommendations"}


def _read(path: Path) -> tuple[dict | None, str | None]:
    if not path.exists():
        return None, f"{path.name} not on file"
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return None, f"{path.name} unreadable: {type(e).__name__}"
    return (doc, None) if isinstance(doc, dict) else (None, f"{path.name} is not an object")


def load_market_risk(root: Path) -> tuple[dict | None, str | None]:
    """The engine projection as the API serves it: load_snapshot + build + book join (each fails soft)."""
    try:
        from lib.market_risk_projection import build, load_snapshot
    except Exception as e:  # noqa: BLE001
        return None, f"market risk projection unavailable: {type(e).__name__}"

    def _load(rel: str):
        doc, _ = _read(root / rel)
        return doc
    snap = load_snapshot(_load, lambda rel: (root / rel).exists())
    if not snap:
        return None, "market_risk_latest.json not on file"
    radar, _ = _read(root / "data" / "runtime" / "hedging_radar_latest.json")
    episode = None
    try:
        from lib.market_risk import escalation
        episode = escalation.open_episode(escalation.load())
    except Exception:  # noqa: BLE001 -- a torn ledger never blocks the read
        episode = None
    proj = build(snap, radar, episode=episode)
    try:
        from lib.market_risk_book_join import join
        proj = join(proj)
    except Exception as e:  # noqa: BLE001
        proj["book_exposure_error"] = f"{type(e).__name__}: {e}"
    return proj, None


def load_truth(root: Path) -> tuple[dict | None, str | None]:
    """Positions and stops from the stored slice; a missing, unreadable or foreign file is a stated gap."""
    doc, gap = _read(root / de.STOPS_SLICE_REL)
    if gap:
        return None, gap
    return de.truth_from_slice(doc)


def policy_tiers(root: Path) -> dict | None:
    try:
        import yaml
        doc = yaml.safe_load((root / "config" / "market_risk_policy.yaml").read_text())
        return doc.get("tiers") if isinstance(doc, dict) else None
    except Exception:  # noqa: BLE001 -- the ladder then shows no score floors, stated by null
        return None


_FROM_SLICE = object()


def build(root: Path, now: datetime | None = None, *, truth=_FROM_SLICE) -> dict:
    """``truth``: a cio_truth.resolve document a host caller already resolved (None = unavailable); omitted, the
    stored stops slice is read."""
    rt = root / "data" / "runtime"
    gaps: dict = {}
    side: dict = {}
    for key, name in SIDE.items():
        side[key], gaps[GAP_KEY.get(key, key)] = _read(rt / name)
    mr, gaps["market_risk"] = load_market_risk(root)
    if truth is _FROM_SLICE:
        truth, gaps["stops"] = load_truth(root)
    else:
        gaps["stops"] = None if isinstance(truth, dict) else "cio_truth unavailable"
    cfg_raw, _ = _read(root / "config" / "defense_recommendations.json")
    try:
        from lib.desks_a import lane_states
        states = lane_states(root)
    except Exception:  # noqa: BLE001
        states = None
    return de.build_projection(mr=mr, truth=truth, gaps=gaps, states=states, policy_tiers=policy_tiers(root),
                               cfg_raw=cfg_raw, now=now, **side)


def write_atomic(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, default=str)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)  # our own temp file, never a store
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print the projection; write nothing")
    ap.add_argument("--root", default=None, help="state root (default: this checkout)")
    ap.add_argument("--summary", action="store_true", help="print a short summary instead of the full JSON")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else ROOT
    doc = build(root)
    out = root / de.OUT_REL
    if args.summary:
        n = doc["narrative"]
        print(json.dumps({"tier": doc["tier"].get("tier"), "score": doc["tier"].get("score"), "headline": n["headline"],
                          "steps": [s["title"] for s in n["what_to_do"]], "sources": doc["source_summary"],
                          "inverse_triggers": doc["hedge_readiness"].get("inverse_triggers")}, indent=1, default=str))
    elif args.dry_run:
        print(json.dumps(doc, indent=1, default=str))
    if args.dry_run:
        print(f"DRY RUN — would write {out} ({len(json.dumps(doc, default=str))} bytes); nothing written", file=sys.stderr)
        return 0
    write_atomic(out, doc)
    print(f"[defense-engine] wrote {out} tier={doc['tier'].get('tier')} sources={doc['source_summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
