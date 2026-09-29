#!/usr/bin/env python3
"""Bounded GUID backfill for traded universe (held ∪ watch ∪ recent Hermes).

Dry-run by default. Does NOT rewrite the full Hermes request corpus.
Appends InstrumentRecord tip patches and SecurityResearchSpine contributions
when a registry subject_guid is known and the durable row lacks one.

Usage:
  python3 scripts/ops/backfill_identity_carriage_traded.py --dry-run
  python3 scripts/ops/backfill_identity_carriage_traded.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _traded_symbols(root: Path, *, hermes_days: int = 30) -> set[str]:
    syms: set[str] = set()
    holdings = _load_json(root / "data" / "portfolios" / "state" / "holdings.json") or {}
    for row in holdings.get("positions") or holdings.get("holdings") or []:
        if isinstance(row, dict) and row.get("symbol"):
            syms.add(str(row["symbol"]).upper())
    for rel in (
        "data/portfolios/state/watchlist.json",
        "data/portfolios/state/ai_watchlist.json",
    ):
        raw = _load_json(root / rel)
        if isinstance(raw, dict):
            if "watchlist" in raw and isinstance(raw["watchlist"], list):
                for row in raw["watchlist"]:
                    if isinstance(row, dict) and row.get("symbol"):
                        syms.add(str(row["symbol"]).upper())
            else:
                for k in raw.keys():
                    if isinstance(k, str) and k.isalpha() and len(k) <= 6:
                        syms.add(k.upper())
        elif isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict) and row.get("symbol"):
                    syms.add(str(row["symbol"]).upper())
    cutoff = datetime.now(timezone.utc) - timedelta(days=hermes_days)
    hermes = root / "data" / "cio" / "hermes_research_results.jsonl"
    if hermes.exists():
        with hermes.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").upper()
                if not sym:
                    continue
                ts = str(row.get("completed_ts") or row.get("as_of") or "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    dt = None
                if dt is None or dt >= cutoff:
                    syms.add(sym)
    return {s for s in syms if s and s not in {"CASH", "PORTFOLIO", "MMKT"}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hermes-days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply)
    root = args.root
    from scripts.lib.identity_carriage import is_registry_guid, resolve_security_identity
    from scripts.lib.cio_instrument_record import InstrumentRecordStore, new_record, subject_key

    universe = sorted(_traded_symbols(root, hermes_days=args.hermes_days))
    report = {
        "as_of": _now(),
        "universe_n": len(universe),
        "apply": apply,
        "ir_stamped": 0,
        "ir_already": 0,
        "ir_unresolved": 0,
        "spine_stamped": 0,
        "spine_already": 0,
        "spine_unresolved": 0,
        "samples": [],
    }
    ir_path = root / "data" / "cio" / "cio_instrument_records.jsonl"
    store = InstrumentRecordStore(ir_path)
    spine_path = root / "data" / "cio" / "security_research_spine.jsonl"
    report["watch_stamped"] = 0
    report["watch_already"] = 0
    report["watch_unresolved"] = 0

    # Watchlist durable maps (personal + AI)
    for rel in (
        "data/portfolios/state/watchlist.json",
        "data/portfolios/state/ai_watchlist.json",
    ):
        path = root / rel
        raw = _load_json(path)
        if raw is None:
            continue
        changed = False
        if isinstance(raw, dict) and isinstance(raw.get("watchlist"), list):
            new_list = []
            for row in raw["watchlist"]:
                if not isinstance(row, dict):
                    new_list.append(row)
                    continue
                sym = str(row.get("symbol") or "").upper()
                if not sym or sym not in set(universe):
                    new_list.append(row)
                    continue
                env = resolve_security_identity(sym, root=root)
                if not is_registry_guid(env.get("subject_guid")):
                    report["watch_unresolved"] += 1
                    new_list.append(row)
                    continue
                if is_registry_guid(row.get("subject_guid")):
                    report["watch_already"] += 1
                    new_list.append(row)
                    continue
                report["watch_stamped"] += 1
                if apply:
                    row = dict(row)
                    row["subject_guid"] = env["subject_guid"]
                    if env.get("issuer_guid"):
                        row["issuer_guid"] = env["issuer_guid"]
                    row["identity_backfill"] = "traded_universe_20260929"
                    changed = True
                new_list.append(row)
            if apply and changed:
                raw = dict(raw)
                raw["watchlist"] = new_list
                path.write_text(json.dumps(raw, indent=2, default=str) + "\n", encoding="utf-8")
        elif isinstance(raw, dict):
            # ticker-keyed map
            for sym in list(raw.keys()):
                if not isinstance(sym, str) or sym not in set(universe):
                    continue
                val = raw[sym]
                if not isinstance(val, dict):
                    val = {"symbol": sym}
                env = resolve_security_identity(sym, root=root)
                if not is_registry_guid(env.get("subject_guid")):
                    report["watch_unresolved"] += 1
                    continue
                if is_registry_guid(val.get("subject_guid")):
                    report["watch_already"] += 1
                    continue
                report["watch_stamped"] += 1
                if apply:
                    val = dict(val)
                    val["symbol"] = sym
                    val["subject_guid"] = env["subject_guid"]
                    if env.get("issuer_guid"):
                        val["issuer_guid"] = env["issuer_guid"]
                    val["identity_backfill"] = "traded_universe_20260929"
                    raw[sym] = val
                    changed = True
            if apply and changed:
                path.write_text(json.dumps(raw, indent=2, default=str) + "\n", encoding="utf-8")

    for sym in universe:
        env = resolve_security_identity(sym, root=root)
        guid = env.get("subject_guid")
        if not is_registry_guid(guid):
            report["ir_unresolved"] += 1
            report["spine_unresolved"] += 1
            continue
        # InstrumentRecord tip for HELD/WATCH
        for kind in ("HELD", "WATCH", "EXIT"):
            key = subject_key(kind, sym)
            tip = store.load(key)
            if tip is None:
                continue
            if is_registry_guid(tip.get("subject_guid")):
                report["ir_already"] += 1
                continue
            report["ir_stamped"] += 1
            if apply:
                patched = dict(tip)
                patched["subject_guid"] = guid
                if env.get("issuer_guid"):
                    patched["issuer_guid"] = env["issuer_guid"]
                patched["updated_ts"] = _now()
                patched["identity_backfill"] = "traded_universe_20260929"
                store.upsert(patched)
            if len(report["samples"]) < 12:
                report["samples"].append({"symbol": sym, "kind": kind, "action": "ir_stamp"})
        # Spine
        from scripts.lib.cross_asset.security_research_spine import load_latest, append_spine, contribute

        sp = load_latest(sym, path=spine_path, root=root)
        if sp is None:
            continue
        if is_registry_guid(sp.get("subject_guid")):
            report["spine_already"] += 1
            continue
        report["spine_stamped"] += 1
        if apply:
            sp = dict(sp)
            sp["subject_guid"] = guid
            if env.get("issuer_guid"):
                sp["issuer_guid"] = env["issuer_guid"]
            sp = contribute(
                sp,
                silo="cio",
                kind="identity_backfill",
                summary=f"Backfill registry subject_guid for {sym}",
            )
            append_spine(sp, path=spine_path, root=root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"universe={report['universe_n']} ir_stamp={report['ir_stamped']} "
            f"ir_already={report['ir_already']} spine_stamp={report['spine_stamped']} "
            f"apply={apply}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
