NO_CONSUMER_REASON = (
    "operator-invoked diligence CLI: CIOEventLifecycleCensus@v1 is a stdout baseline receipt for Phase 1 WS2, not an ingested store contract"
)

#!/usr/bin/env python3
"""Event lifecycle census — measure accepted→…→recoverable by family.

READ_ONLY_ADVISORY. MBI=0. Samples producers/stores; never writes broker,
notify, or history DELETE. Fail-soft on every store.

Families (master plan WS2):
  • security_holdings_exit_reentry
  • sector_industry
  • catalyst_earnings

Stages:
  accepted → normalized → persisted → processed → archived → recoverable

  python scripts/cio_event_lifecycle_census.py            # human
  python scripts/cio_event_lifecycle_census.py --json
  python scripts/cio_event_lifecycle_census.py --root PATH
  python scripts/cio_event_lifecycle_census.py --out evidence.json

This is instrumentation for a *baseline*, not a claim of 99.99%.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIVE = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")

SCHEMA = "CIOEventLifecycleCensus@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

STAGES = (
    "accepted",
    "normalized",
    "persisted",
    "processed",
    "archived",
    "recoverable",
)

FAMILIES = (
    "security_holdings_exit_reentry",
    "sector_industry",
    "catalyst_earnings",
)

_SYM_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * num / den, 2)


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        if not path.is_file():
            return None, "missing"
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            obj, _idx = json.JSONDecoder().raw_decode(text)
            return obj, "raw_decode_partial_ok"
    except OSError as exc:
        return None, f"os_error:{type(exc).__name__}"
    except Exception as exc:  # fail-soft
        return None, f"error:{type(exc).__name__}"


def _iter_jsonl(path: Path, *, limit: int | None = None) -> tuple[list[dict[str, Any]], str | None]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows, "missing"
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                    if limit is not None and len(rows) >= limit:
                        break
        return rows, None
    except OSError as exc:
        return rows, f"os_error:{type(exc).__name__}"


def _norm_sym(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_norm_symbol(sym: str) -> bool:
    if not sym or sym in {"CASH", "USD", "MMF"}:
        return False
    return bool(_SYM_RE.match(sym))


def _resolve_path(root: Path, rel: str) -> Path:
    """Prefer canonical registry when the store id is known; else root/rel."""
    try:
        from scripts.lib.canonical_store_registry import resolve_store

        # Map a few well-known relative paths to store ids.
        by_path = {
            "data/portfolios/state/holdings.json": "portfolio.holdings.current",
            "data/portfolios/state/watchlist.json": "portfolio.watchlist",
            "data/cio/cio_instrument_records.jsonl": "cio.instrument_records",
            "data/runtime/sector_momentum_latest.json": "sector.momentum.current",
            "data/runtime/industry_momentum_latest.json": "industry.momentum.current",
            "data/runtime/identity_registry.json": "identity.registry",
            "data/cio/cio_workflow_lineage.jsonl": "cio.workflow_lineage",
        }
        store_id = by_path.get(rel)
        if store_id:
            res = resolve_store(store_id, root=root)
            path = res.get("path")
            if path:
                return Path(path)
    except Exception:
        pass
    return root / rel


def _persistent_sibling(root: Path) -> Path | None:
    """If CURRENT lacks a data plane symlink, persistent-state may still hold it."""
    preferred = Path.home() / "trade-ai-releases" / "persistent-state"
    try:
        if preferred.is_dir() and preferred.resolve() != root.resolve():
            return preferred
    except OSError:
        return preferred if preferred.is_dir() else None
    return None


def _family_shell(family: str) -> dict[str, Any]:
    return {
        "family": family,
        "stages": {s: 0 for s in STAGES},
        "stage_pct_of_accepted": {s: None for s in STAGES},
        "full_lifecycle_pct": None,
        "drop_reasons": {},
        "producers": [],
        "stores": [],
        "notes": [],
        "sample_n": 0,
        "ok": True,
        "errors": [],
    }


def _finalize_family(fam: dict[str, Any]) -> dict[str, Any]:
    accepted = int(fam["stages"].get("accepted") or 0)
    for stage in STAGES:
        fam["stage_pct_of_accepted"][stage] = _pct(int(fam["stages"].get(stage) or 0), accepted)
    # Full lifecycle = share of accepted that reached recoverable.
    fam["full_lifecycle_pct"] = fam["stage_pct_of_accepted"]["recoverable"]
    # Pipeline processed rate (common headline): processed/accepted.
    fam["processed_pct"] = fam["stage_pct_of_accepted"]["processed"]
    return fam


# ── family collectors ─────────────────────────────────────────────────────────


def census_security_holdings_exit_reentry(root: Path) -> dict[str, Any]:
    """Holdings + EXIT instrument records + reentry desk/payload."""
    fam = _family_shell("security_holdings_exit_reentry")
    fam["producers"] = [
        "holdings reconciliation → portfolio.holdings.current",
        "cio_instrument_record (HELD:/EXIT:)",
        "reentry_decision_desk",
        "reentry_payload_last",
    ]
    drops: Counter[str] = Counter()

    holdings_path = _resolve_path(root, "data/portfolios/state/holdings.json")
    ir_path = _resolve_path(root, "data/cio/cio_instrument_records.jsonl")
    reentry_desk = root / "data/runtime/reentry_decision_desk_latest.json"
    reentry_payload = root / "data/cio/reentry_payload_last.json"
    identity_path = _resolve_path(root, "data/runtime/identity_registry.json")
    theses_path = root / "data/cio/cio_theses_projection.json"
    backups_dir = root / "data/cio/backups"
    lifecycle_path = root / "data/cio/intelligence_lifecycle.jsonl"

    fam["stores"] = [
        str(holdings_path),
        str(ir_path),
        str(reentry_desk),
        str(reentry_payload),
        str(identity_path),
    ]

    holdings_obj, herr = _load_json(holdings_path)
    if herr:
        fam["errors"].append(f"holdings:{herr}")
    holdings_rows: list[dict[str, Any]] = []
    if isinstance(holdings_obj, dict):
        raw = holdings_obj.get("holdings") or []
        if isinstance(raw, list):
            holdings_rows = [r for r in raw if isinstance(r, dict)]

    identity_obj, _ = _load_json(identity_path)
    by_symbol: dict[str, Any] = {}
    if isinstance(identity_obj, dict):
        by_symbol = identity_obj.get("by_symbol") or {}
        if not isinstance(by_symbol, dict):
            by_symbol = {}

    theses_obj, _ = _load_json(theses_path)
    thesis_symbols: set[str] = set()
    if isinstance(theses_obj, dict):
        for key in ("theses", "by_symbol", "items", "records"):
            block = theses_obj.get(key)
            if isinstance(block, dict):
                thesis_symbols.update(_norm_sym(k) for k in block.keys())
            elif isinstance(block, list):
                for row in block:
                    if isinstance(row, dict):
                        thesis_symbols.add(_norm_sym(row.get("symbol") or row.get("ticker")))
        # flat symbol keys
        for k in theses_obj:
            if _is_norm_symbol(_norm_sym(k)):
                thesis_symbols.add(_norm_sym(k))

    ir_rows, ir_err = _iter_jsonl(ir_path)
    if ir_err:
        fam["errors"].append(f"instrument_records:{ir_err}")
    held_ir: set[str] = set()
    exit_ir: set[str] = set()
    for row in ir_rows:
        sk = str(row.get("subject_key") or "")
        if sk.startswith("HELD:"):
            held_ir.add(_norm_sym(sk.split(":", 1)[1]))
        elif sk.startswith("EXIT:"):
            exit_ir.add(_norm_sym(sk.split(":", 1)[1]))

    desk_obj, desk_err = _load_json(reentry_desk)
    if desk_err:
        fam["errors"].append(f"reentry_desk:{desk_err}")
    desk_rows: list[dict[str, Any]] = []
    if isinstance(desk_obj, dict):
        raw = desk_obj.get("rows") or []
        if isinstance(raw, list):
            desk_rows = [r for r in raw if isinstance(r, dict)]

    payload_obj, payload_err = _load_json(reentry_payload)
    if payload_err:
        fam["errors"].append(f"reentry_payload:{payload_err}")
    payload_syms: set[str] = set()
    if isinstance(payload_obj, dict):
        payload_syms = {_norm_sym(k) for k in payload_obj.keys() if _is_norm_symbol(_norm_sym(k))}

    # Lifecycle processed evidence for holdings deltas.
    lifecycle_rows, _ = _iter_jsonl(lifecycle_path)
    lifecycle_holdings_syms: set[str] = set()
    for row in lifecycle_rows:
        delta = row.get("delta") if isinstance(row, dict) else None
        if not isinstance(delta, dict):
            continue
        if str(delta.get("source_domain") or "").lower() == "holdings":
            # wake symbols if any
            impact = row.get("impact") if isinstance(row.get("impact"), dict) else {}
            for sym in impact.get("wake_symbols") or []:
                lifecycle_holdings_syms.add(_norm_sym(sym))
            ref = str(delta.get("source_ref") or "")
            if ":" in ref:
                lifecycle_holdings_syms.add(_norm_sym(ref.split(":")[-1]))

    backups = list(backups_dir.glob("holdings.json.*")) if backups_dir.is_dir() else []
    backup_readable = 0
    for bp in backups:
        obj, err = _load_json(bp)
        if err is None and isinstance(obj, dict) and isinstance(obj.get("holdings"), list):
            backup_readable += 1

    # Build per-symbol event sample from three producer legs.
    events: dict[str, dict[str, bool]] = {}

    def ensure(sym: str) -> dict[str, bool]:
        return events.setdefault(
            sym,
            {s: False for s in STAGES},
        )

    # Holdings leg
    for row in holdings_rows:
        sym = _norm_sym(row.get("symbol") or row.get("ticker"))
        if not sym:
            drops["holdings_missing_symbol"] += 1
            continue
        if row.get("is_cash") or sym == "CASH":
            drops["holdings_cash_skipped"] += 1
            continue
        ev = ensure(sym)
        ev["accepted"] = True
        if _is_norm_symbol(sym):
            ev["normalized"] = True
        else:
            drops["holdings_symbol_not_normalized"] += 1
        # holdings.json itself is the persist store
        ev["persisted"] = True
        if sym in by_symbol or sym in held_ir or sym in thesis_symbols or sym in lifecycle_holdings_syms:
            ev["processed"] = True
        else:
            drops["holdings_no_downstream_cognition"] += 1
        # archived: EXIT IR exists for this symbol OR backup set exists (store-level)
        if sym in exit_ir:
            ev["archived"] = True
        # recoverable via live holdings + readable backup
        if backup_readable > 0 and holdings_obj is not None:
            ev["recoverable"] = True
        elif holdings_obj is not None and ev["persisted"]:
            # live file is recoverable even without backup; note honesty
            ev["recoverable"] = True
            drops["recoverable_via_live_only"] += 1

    # EXIT instrument-record leg (former holdings)
    for sym in exit_ir:
        if not sym:
            continue
        ev = ensure(sym)
        ev["accepted"] = True
        if _is_norm_symbol(sym):
            ev["normalized"] = True
        else:
            drops["exit_symbol_not_normalized"] += 1
        ev["persisted"] = True
        ev["archived"] = True
        if sym in thesis_symbols or sym in by_symbol or sym in payload_syms or any(
            _norm_sym(r.get("symbol")) == sym for r in desk_rows
        ):
            ev["processed"] = True
        else:
            drops["exit_no_downstream"] += 1
        # EXIT IR is itself the recovery spine for cognition
        ev["recoverable"] = True

    # Reentry desk leg
    for row in desk_rows:
        sym = _norm_sym(row.get("symbol"))
        if not sym:
            drops["reentry_missing_symbol"] += 1
            continue
        ev = ensure(sym)
        ev["accepted"] = True
        if _is_norm_symbol(sym) and row.get("price_source"):
            ev["normalized"] = True
        elif _is_norm_symbol(sym):
            ev["normalized"] = True
            drops["reentry_missing_price_source"] += 1
        else:
            drops["reentry_symbol_not_normalized"] += 1
        if sym in payload_syms or sym in exit_ir:
            ev["persisted"] = True
        else:
            # desk snapshot is a derived projection — count as persisted if desk file ok
            if desk_obj is not None:
                ev["persisted"] = True
                drops["reentry_persisted_desk_only"] += 1
            else:
                drops["reentry_not_persisted"] += 1
        gates = row.get("gates")
        advisory = row.get("advisory")
        intel = row.get("intel")
        if gates or advisory or intel:
            ev["processed"] = True
        else:
            drops["reentry_unprocessed_empty_gates"] += 1
        if sym in exit_ir:
            ev["archived"] = True
        # desk is rebuildable DERIVED; payload is a last-shot cache
        if desk_obj is not None:
            ev["recoverable"] = True

    if backup_readable == 0:
        fam["notes"].append("no_readable_holdings_backup_under_data/cio/backups")
    else:
        fam["notes"].append(f"readable_holdings_backups={backup_readable}")
    fam["notes"].append(
        f"holdings_rows={len(holdings_rows)} exit_ir={len(exit_ir)} "
        f"reentry_desk_rows={len(desk_rows)} reentry_payload_syms={len(payload_syms)}"
    )

    for ev in events.values():
        for stage in STAGES:
            if ev.get(stage):
                fam["stages"][stage] += 1
            else:
                # once accepted, missing later stage is a drop — counted above when detectable
                pass

    fam["sample_n"] = len(events)
    fam["drop_reasons"] = dict(drops.most_common())
    if fam["errors"]:
        fam["ok"] = False
    return _finalize_family(fam)


def census_sector_industry(root: Path) -> dict[str, Any]:
    fam = _family_shell("sector_industry")
    fam["producers"] = [
        "sector_momentum_engine → sector.momentum.current",
        "industry_momentum → industry.momentum.current",
        "holdings resolved_sectors",
    ]
    drops: Counter[str] = Counter()

    sector_path = _resolve_path(root, "data/runtime/sector_momentum_latest.json")
    industry_path = _resolve_path(root, "data/runtime/industry_momentum_latest.json")
    holdings_path = _resolve_path(root, "data/portfolios/state/holdings.json")
    wouldhave = root / "data/runtime/sector_momentum_wouldhavefired.json"
    sync_state = root / "data/runtime/sector_universe_sync_state.json"
    fam["stores"] = [str(sector_path), str(industry_path), str(wouldhave), str(sync_state)]

    sector_obj, serr = _load_json(sector_path)
    industry_obj, ierr = _load_json(industry_path)
    holdings_obj, _ = _load_json(holdings_path)
    if serr:
        fam["errors"].append(f"sector:{serr}")
    if ierr:
        fam["errors"].append(f"industry:{ierr}")

    sector_rows: list[dict[str, Any]] = []
    if isinstance(sector_obj, dict):
        raw = sector_obj.get("rows") or []
        if isinstance(raw, list):
            sector_rows = [r for r in raw if isinstance(r, dict)]
        nd = sector_obj.get("not_decomposed") or {}
        if isinstance(nd, dict):
            for pos in nd.get("positions") or []:
                if isinstance(pos, dict):
                    why = str(pos.get("why") or "not_decomposed")
                    drops[f"sector_not_decomposed:{why[:60]}"] += 1

    industry_rows: list[dict[str, Any]] = []
    if isinstance(industry_obj, dict):
        raw = industry_obj.get("industries") or []
        if isinstance(raw, list):
            industry_rows = [r for r in raw if isinstance(r, dict)]

    resolved_sectors: list[Any] = []
    if isinstance(holdings_obj, dict):
        rs = holdings_obj.get("resolved_sectors") or []
        if isinstance(rs, list):
            resolved_sectors = rs

    events: dict[str, dict[str, bool]] = {}

    def ensure(key: str) -> dict[str, bool]:
        return events.setdefault(key, {s: False for s in STAGES})

    for row in sector_rows:
        key = f"sector:{row.get('sector') or row.get('etf') or 'UNKNOWN'}"
        ev = ensure(key)
        ev["accepted"] = True
        if row.get("sector") and row.get("etf") and row.get("state"):
            ev["normalized"] = True
        else:
            drops["sector_row_incomplete"] += 1
            if row.get("sector") or row.get("etf"):
                ev["normalized"] = True
        if sector_obj is not None:
            ev["persisted"] = True
        # processed if book exposure attached or state present and holdings resolved_sectors non-empty
        if row.get("book_pct") is not None or row.get("book_dollars") is not None:
            ev["processed"] = True
        elif resolved_sectors:
            ev["processed"] = True
            drops["sector_processed_via_holdings_resolved_only"] += 1
        else:
            drops["sector_unprocessed"] += 1
        if wouldhave.is_file() or sync_state.is_file():
            ev["archived"] = True
        else:
            drops["sector_no_archive_sidecar"] += 1
        # DERIVED_CURRENT_PROJECTION rebuildable
        ev["recoverable"] = sector_obj is not None

    for row in industry_rows:
        name = row.get("industry") or row.get("name") or row.get("id") or row.get("sector")
        key = f"industry:{name or 'UNKNOWN'}"
        # avoid colliding with sector keys; industries may reuse names
        if key in events and events[key].get("accepted") and key.startswith("industry:"):
            # already counted
            pass
        ev = ensure(key)
        ev["accepted"] = True
        if name:
            ev["normalized"] = True
        else:
            drops["industry_missing_name"] += 1
        if industry_obj is not None:
            ev["persisted"] = True
        # processed if quadrant / candidates / alerts machinery touched the row
        if any(k in row for k in ("quadrant", "perf_month", "perf_week", "rs", "state", "score")):
            ev["processed"] = True
        elif isinstance(industry_obj, dict) and industry_obj.get("counts"):
            ev["processed"] = True
        else:
            drops["industry_unprocessed"] += 1
        # industry file is current projection; treat history absence honestly
        if (root / "data/runtime/industry_momentum_latest.json").is_file():
            # no dedicated archive file observed — count archived only if captured_at present
            if industry_obj and industry_obj.get("captured_at"):
                # current snapshot only — not a true archive
                drops["industry_archive_current_only"] += 1
            else:
                drops["industry_no_archive"] += 1
        ev["recoverable"] = industry_obj is not None

    # Honesty note: industry archive stage mostly false unless sidecar exists.
    for key, ev in events.items():
        if key.startswith("industry:") and not ev.get("archived"):
            # leave archived false
            pass

    fam["notes"].append(
        f"sector_rows={len(sector_rows)} industry_rows={len(industry_rows)} "
        f"holdings_resolved_sectors={len(resolved_sectors)}"
    )
    if wouldhave.is_file():
        fam["notes"].append("sector_wouldhavefired_present")
    if sync_state.is_file():
        fam["notes"].append("sector_universe_sync_state_present")

    for ev in events.values():
        for stage in STAGES:
            if ev.get(stage):
                fam["stages"][stage] += 1

    fam["sample_n"] = len(events)
    fam["drop_reasons"] = dict(drops.most_common())
    if fam["errors"]:
        fam["ok"] = False
    return _finalize_family(fam)


def census_catalyst_earnings(root: Path) -> dict[str, Any]:
    fam = _family_shell("catalyst_earnings")
    fam["producers"] = [
        "catalyst_events → catalyst_graph_latest",
        "hermes/momentum_catalysts/*.jsonl",
        "earnings_dates.json",
    ]
    drops: Counter[str] = Counter()

    graph_path = root / "data/cio/catalyst_graph_latest.json"
    earnings_path = root / "data/portfolios/state/earnings_dates.json"
    hermes_dir = root / "data/hermes/momentum_catalysts"
    if not hermes_dir.is_dir() or not any(hermes_dir.glob("*.jsonl")):
        sibling = _persistent_sibling(root)
        if sibling is not None:
            alt = sibling / "data/hermes/momentum_catalysts"
            if alt.is_dir() and any(alt.glob("*.jsonl")):
                hermes_dir = alt
                fam["notes"].append(f"hermes_dir_fallback={hermes_dir}")
    fam["stores"] = [str(graph_path), str(earnings_path), str(hermes_dir)]

    graph_obj, gerr = _load_json(graph_path)
    if gerr:
        fam["errors"].append(f"catalyst_graph:{gerr}")
    earnings_obj, eerr = _load_json(earnings_path)
    if eerr:
        fam["errors"].append(f"earnings_dates:{eerr}")

    # Graph funnel: traces/skipped = accepted pool; nodes = persisted/processed.
    traces: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    if isinstance(graph_obj, dict):
        traces = [t for t in (graph_obj.get("traces") or []) if isinstance(t, dict)]
        nodes = [n for n in (graph_obj.get("nodes") or []) if isinstance(n, dict)]
        raw_skipped = graph_obj.get("skipped") or {}
        if isinstance(raw_skipped, dict):
            skipped = {str(k): int(v) for k, v in raw_skipped.items() if isinstance(v, (int, float))}
            for k, v in skipped.items():
                drops[f"catalyst_graph_skip:{k}"] += int(v)

    # Hermes daily catalysts (sample last few files, fail-soft).
    hermes_rows: list[dict[str, Any]] = []
    hermes_files = sorted(hermes_dir.glob("*.jsonl")) if hermes_dir.is_dir() else []
    for fp in hermes_files[-5:]:
        rows, err = _iter_jsonl(fp)
        if err:
            fam["errors"].append(f"hermes_catalysts:{fp.name}:{err}")
            continue
        hermes_rows.extend(rows)

    earnings_syms: dict[str, dict[str, Any]] = {}
    if isinstance(earnings_obj, dict):
        for k, v in earnings_obj.items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, dict):
                earnings_syms[_norm_sym(k)] = v

    # Event keys: catalyst traces + hermes rows + earnings symbols.
    events: dict[str, dict[str, bool]] = {}

    def ensure(key: str) -> dict[str, bool]:
        return events.setdefault(key, {s: False for s in STAGES})

    # 1) Graph traces (accepted producers into binder)
    for i, tr in enumerate(traces):
        guid = tr.get("catalyst_guid") or tr.get("catalyst_row_id") or f"trace:{i}"
        key = f"trace:{guid}"
        ev = ensure(key)
        ev["accepted"] = True
        sym = _norm_sym(
            (tr.get("target_security") or {}).get("symbol")
            if isinstance(tr.get("target_security"), dict)
            else tr.get("symbol")
        )
        if not sym and isinstance(tr.get("target_security"), str):
            sym = _norm_sym(tr.get("target_security"))
        if sym and _is_norm_symbol(sym):
            ev["normalized"] = True
        elif tr.get("headline") or tr.get("catalyst_guid"):
            # headline-only still "normalized" enough to attempt bind
            ev["normalized"] = True
            drops["catalyst_trace_weak_symbol"] += 1
        else:
            drops["catalyst_trace_not_normalized"] += 1
        # persisted/processed if matching node exists — approximate via node event_guids set below
        # mark later

    node_by_guid = {
        str(n.get("event_guid")): n for n in nodes if n.get("event_guid")
    }
    node_syms = {
        _norm_sym(n.get("symbol"))
        for n in nodes
        if _norm_sym(n.get("symbol"))
    }
    # Also security_guid presence implies identity bind
    for i, tr in enumerate(traces):
        guid = tr.get("catalyst_guid") or tr.get("catalyst_row_id") or f"trace:{i}"
        key = f"trace:{guid}"
        ev = events[key]
        # Heuristic: a node with same guid OR target symbol present in nodes
        tgt = tr.get("target_security")
        sym = ""
        if isinstance(tgt, dict):
            sym = _norm_sym(tgt.get("symbol"))
        elif isinstance(tgt, str):
            sym = _norm_sym(tgt)
        matched = False
        if str(guid) in node_by_guid:
            matched = True
        elif sym and sym in node_syms:
            matched = True
        if matched:
            ev["persisted"] = True
            ev["processed"] = True
            # Graph snapshot + traces act as a weak archive of bound events.
            ev["archived"] = True
            if graph_obj is not None:
                ev["recoverable"] = True
        # else left false — drops already include graph skipped totals

    # Count graph skips as accepted-but-dropped (synthetic events) so denominator is honest.
    # Cap synthetic skip samples to keep census bounded while preserving rates.
    skip_total = sum(skipped.values())
    # Represent skips as aggregate accepted without later stages.
    if skip_total:
        # Inflate accepted/stages using aggregate counters rather than millions of fake keys.
        fam["notes"].append(
            f"catalyst_graph_skipped_aggregate={skip_total} "
            f"(counted in stages via aggregate, not per-row materialization)"
        )

    # 2) Hermes catalyst rows
    for i, row in enumerate(hermes_rows):
        sym = _norm_sym(row.get("symbol"))
        key = f"hermes:{sym}:{row.get('research_timestamp') or i}"
        ev = ensure(key)
        ev["accepted"] = True
        if _is_norm_symbol(sym) and row.get("catalyst_type"):
            ev["normalized"] = True
        else:
            drops["hermes_catalyst_not_normalized"] += 1
            if _is_norm_symbol(sym):
                ev["normalized"] = True
        # persisted if landed in graph nodes or earnings store (earnings is adjacent)
        if sym in node_syms or sym in earnings_syms:
            ev["persisted"] = True
        else:
            # daily jsonl *is* a persist of hermes output
            ev["persisted"] = True
            drops["hermes_persisted_daily_only"] += 1
        if row.get("catalyst_summary") or row.get("sources"):
            ev["processed"] = True
        else:
            drops["hermes_unprocessed"] += 1
        # daily files are the archive
        ev["archived"] = True
        ev["recoverable"] = True  # file still on disk

    # 3) Earnings dates
    for sym, row in earnings_syms.items():
        key = f"earnings:{sym}"
        ev = ensure(key)
        ev["accepted"] = True
        if _is_norm_symbol(sym):
            ev["normalized"] = True
        else:
            drops["earnings_symbol_not_normalized"] += 1
        ev["persisted"] = True
        if row.get("earnings_date"):
            ev["processed"] = True
        else:
            drops["earnings_date_missing"] += 1
        # earnings_dates.json is current; no dated archive observed → archived false unless fetched_at
        if row.get("fetched_at"):
            # still not a true archive; leave archived false, note it
            drops["earnings_no_dated_archive"] += 1
        ev["recoverable"] = earnings_obj is not None

    # Stage counts from materialized events
    for ev in events.values():
        for stage in STAGES:
            if ev.get(stage):
                fam["stages"][stage] += 1

    # Fold aggregate graph skips into accepted (and not into later stages).
    if skip_total:
        fam["stages"]["accepted"] += skip_total
        # skipped items were "accepted" by the binder input but failed normalize/persist
        # Do not add to normalized/persisted/etc.

    # Also count graph nodes that may not have matched a trace key
    for n in nodes:
        guid = n.get("event_guid")
        key = f"node:{guid or n.get('security_guid')}"
        if key in events or f"trace:{guid}" in events:
            continue
        ev = ensure(key)
        ev["accepted"] = True
        if n.get("event_type") and (n.get("security_guid") or n.get("issuer_guid")):
            ev["normalized"] = True
        else:
            drops["catalyst_node_weak_identity"] += 1
            if n.get("event_type"):
                ev["normalized"] = True
        ev["persisted"] = True
        if n.get("status"):
            ev["processed"] = True
        # graph snapshot is current; traces list is weak archive
        if traces:
            ev["archived"] = True
        if graph_obj is not None:
            ev["recoverable"] = True
        for stage in STAGES:
            if ev.get(stage):
                fam["stages"][stage] += 1

    fam["sample_n"] = len(events) + skip_total
    fam["notes"].append(
        f"graph_traces={len(traces)} graph_nodes={len(nodes)} "
        f"hermes_rows_sampled={len(hermes_rows)} hermes_files={len(hermes_files)} "
        f"earnings_symbols={len(earnings_syms)} skip_total={skip_total}"
    )
    if isinstance(graph_obj, dict):
        fam["notes"].append(f"bound_by_type={graph_obj.get('bound_by_type')}")
    if isinstance(earnings_obj, dict) and isinstance(earnings_obj.get("_meta"), dict):
        fam["notes"].append(f"earnings_meta={earnings_obj.get('_meta')}")

    fam["drop_reasons"] = dict(drops.most_common(40))
    if fam["errors"]:
        fam["ok"] = False
    return _finalize_family(fam)


def census_lineage_overlay(root: Path) -> dict[str, Any]:
    """Optional cross-cutting lineage completion (G-LOOP-01), fail-soft."""
    out: dict[str, Any] = {"available": False}
    try:
        from scripts.lib.cio_lineage_health import completion_report

        path = root / "data/cio/cio_workflow_lineage.jsonl"
        report = completion_report(str(path) if path.is_file() else None)
        out = {
            "available": True,
            "workflows": report.get("workflows"),
            "complete_to_checkpoint": report.get("complete_to_checkpoint"),
            "completion_rate": report.get("completion_rate"),
            "completion_pct": (
                round(100.0 * report["completion_rate"], 2)
                if report.get("completion_rate") is not None
                else None
            ),
            "with_checkpoint_id": report.get("with_checkpoint_id"),
            "arcs": report.get("arcs"),
            "stalled_at": report.get("stalled_at"),
            "note": "workflow lineage ≠ event-family lifecycle; shown for G-LOOP-01 context",
        }
    except Exception as exc:
        out = {"available": False, "reason": type(exc).__name__}
    return out


def run_census(root: Path) -> dict[str, Any]:
    families = [
        census_security_holdings_exit_reentry(root),
        census_sector_industry(root),
        census_catalyst_earnings(root),
    ]
    # If hermes catalysts were invisible under CURRENT, retry catalyst family against
    # persistent-state (fail-soft; do not change other families' roots).
    cat = families[2]
    notes = cat.get("notes") or []
    if any("hermes_files=0" in str(n) for n in notes):
        sibling = _persistent_sibling(root)
        if sibling is not None:
            retry = census_catalyst_earnings(sibling)
            retry_notes = retry.get("notes") or []
            if any("hermes_files=" in str(n) and "hermes_files=0" not in str(n) for n in retry_notes):
                retry["notes"] = list(retry_notes) + [
                    f"hermes_source_root_fallback={sibling}"
                ]
                families[2] = retry

    # Headline: unweighted mean across families + event-weighted overall; never invent 99.99.
    lifecycle_vals = [
        f["full_lifecycle_pct"]
        for f in families
        if isinstance(f.get("full_lifecycle_pct"), (int, float))
    ]
    processed_vals = [
        f["processed_pct"]
        for f in families
        if isinstance(f.get("processed_pct"), (int, float))
    ]
    acc_sum = sum(int((f.get("stages") or {}).get("accepted") or 0) for f in families)
    rec_sum = sum(int((f.get("stages") or {}).get("recoverable") or 0) for f in families)
    proc_sum = sum(int((f.get("stages") or {}).get("processed") or 0) for f in families)
    headline = {
        "mean_full_lifecycle_pct": (
            round(sum(lifecycle_vals) / len(lifecycle_vals), 2) if lifecycle_vals else None
        ),
        "mean_processed_pct": (
            round(sum(processed_vals) / len(processed_vals), 2) if processed_vals else None
        ),
        "min_full_lifecycle_pct": (min(lifecycle_vals) if lifecycle_vals else None),
        "weighted_full_lifecycle_pct": _pct(rec_sum, acc_sum),
        "weighted_processed_pct": _pct(proc_sum, acc_sum),
        "accepted_total": acc_sum,
        "recoverable_total": rec_sum,
        "processed_total": proc_sum,
        "families_measured": len(families),
        "claim_99_99": False,
        "claim_note": "99.99% is a Phase-9 KPI after instrumentation; this package measures baseline only",
    }
    pin = None
    try:
        pin = (root / "BUILD_SHA").read_text(encoding="utf-8").strip()
    except OSError:
        pin = None

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "as_of": _now(),
        "root": str(root),
        "current_pin": pin,
        "stages": list(STAGES),
        "headline": headline,
        "families": {f["family"]: f for f in families},
        "lineage_overlay": census_lineage_overlay(root),
        "rails": {
            "authority": AUTHORITY,
            "mbi": MBI,
            "broker_writes": False,
            "notify_on": False,
            "history_delete": False,
        },
    }


def render_human(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"CIO Event Lifecycle Census  ({report.get('schema')})")
    lines.append(f"root={report.get('root')}  pin={report.get('current_pin')}")
    lines.append(f"as_of={report.get('as_of')}  authority={report.get('authority')}  MBI={report.get('memory_behavior_influence')}")
    h = report.get("headline") or {}
    lines.append(
        f"HEADLINE  mean_full_lifecycle={h.get('mean_full_lifecycle_pct')}%  "
        f"weighted_full_lifecycle={h.get('weighted_full_lifecycle_pct')}%  "
        f"mean_processed={h.get('mean_processed_pct')}%  "
        f"weighted_processed={h.get('weighted_processed_pct')}%  "
        f"min_full_lifecycle={h.get('min_full_lifecycle_pct')}%  "
        f"claim_99.99={h.get('claim_99_99')}"
    )
    lines.append(
        f"          accepted_total={h.get('accepted_total')}  "
        f"processed_total={h.get('processed_total')}  "
        f"recoverable_total={h.get('recoverable_total')}"
    )
    lines.append("")
    lines.append(
        f"{'family':<34} {'accept':>7} {'norm':>7} {'persist':>7} "
        f"{'process':>7} {'arch':>7} {'recov':>7} {'full%':>7} {'proc%':>7}"
    )
    lines.append("-" * 100)
    for name in FAMILIES:
        fam = (report.get("families") or {}).get(name) or {}
        st = fam.get("stages") or {}
        lines.append(
            f"{name:<34} "
            f"{st.get('accepted', 0):7d} "
            f"{st.get('normalized', 0):7d} "
            f"{st.get('persisted', 0):7d} "
            f"{st.get('processed', 0):7d} "
            f"{st.get('archived', 0):7d} "
            f"{st.get('recoverable', 0):7d} "
            f"{str(fam.get('full_lifecycle_pct')):>7} "
            f"{str(fam.get('processed_pct')):>7}"
        )
    lines.append("")
    for name in FAMILIES:
        fam = (report.get("families") or {}).get(name) or {}
        lines.append(f"## {name}")
        drops = fam.get("drop_reasons") or {}
        if drops:
            top = list(drops.items())[:8]
            lines.append("  drop_reasons: " + ", ".join(f"{k}={v}" for k, v in top))
        for note in fam.get("notes") or []:
            lines.append(f"  note: {note}")
        for err in fam.get("errors") or []:
            lines.append(f"  error: {err}")
        lines.append("")
    lin = report.get("lineage_overlay") or {}
    if lin.get("available"):
        lines.append(
            f"lineage_overlay  workflows={lin.get('workflows')}  "
            f"complete_to_checkpoint={lin.get('complete_to_checkpoint')}  "
            f"({lin.get('completion_pct')}%)  arcs={lin.get('arcs')}"
        )
    else:
        lines.append(f"lineage_overlay  unavailable ({lin.get('reason')})")
    lines.append("")
    lines.append("Do NOT claim 99.99% from this baseline. See docs/audits/diligence/P1_WS2_*.md")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="CIO event lifecycle census (read-only baseline measurement)"
    )
    ap.add_argument("--root", default=str(LIVE), help="data root (default: CURRENT)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--human", action="store_true", help="emit human table (default)")
    ap.add_argument("--out", default="", help="optional path to write JSON evidence")
    args = ap.parse_args()

    root = Path(args.root)
    report = run_census(root)

    if args.out:
        out_path = Path(args.out)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            # fail-soft: still print report
            report.setdefault("write_errors", []).append(f"{out_path}:{type(exc).__name__}")

    if args.json and not args.human:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
            print()
        print(render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
