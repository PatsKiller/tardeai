"""CIO Situation Detector v1 — deterministic S1–S8 skeleton.

READ_ONLY_ADVISORY. SHADOW by default (plans + events only; notify off).

Emits draft plans via CIOPlanStore. Never invents numbers: every numeric claim
must come from the evidence pack or be labeled DATA_UNAVAILABLE.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from scripts.lib.cio_plans import (
    CIOPlanStore,
    DETECTOR_VERSION_DEFAULT,
    VALID_SITUATION_TYPES,
)

DETECTOR_VERSION = DETECTOR_VERSION_DEFAULT
DEFAULT_CONFIG_PATH = Path("config/cio_situations.yaml")

SITUATION_CODES = {
    "S1": "S1_POSITION_LIFECYCLE",
    "S2": "S2_STOP_GAP",
    "S3": "S3_REENTRY_CANDIDATE",
    "S4": "S4_SECTOR_ROTATION",
    "S5": "S5_CASH_DEPLOYMENT",
    "S6": "S6_CONCENTRATION_OR_DISPOSITION",
    "S7": "S7_WATCH_PROMOTION",
    "S8": "S8_DEFENSIVE_REGIME",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path or DEFAULT_CONFIG_PATH)
    if not p.exists():
        return {
            "enabled": True,
            "shadow": True,
            "notify": False,
            "dedup_hours": 6,
            "detector_version": DETECTOR_VERSION,
            "thresholds": {},
            "owners": {},
            "cc_deep_links": {},
            "revisit_hours": {"default": 24},
        }
    with open(p) as fh:
        cfg = yaml.safe_load(fh) or {}
    # env overrides
    en = os.environ.get("CIO_SITUATIONS_ENABLED")
    if en is not None:
        cfg["enabled"] = en.strip().lower() not in ("0", "false", "off", "no")
    sh = os.environ.get("CIO_SITUATIONS_SHADOW")
    if sh is not None:
        cfg["shadow"] = sh.strip().lower() not in ("0", "false", "off", "no")
    nt = os.environ.get("CIO_SITUATIONS_NOTIFY")
    if nt is not None:
        cfg["notify"] = nt.strip().lower() in ("1", "true", "on", "yes")
    return cfg


def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _as_of(pack: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = pack.get(k)
        if v:
            return str(v)
    return pack.get("as_of") or pack.get("collected_at") or _now_iso()


def _ref(domain: str, pack: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {
        "domain": domain,
        "as_of": _as_of(pack),
        "fields_used": fields,
        "quality_state": pack.get("quality_state") or pack.get("status") or "OK",
    }


def _revisit(cfg: dict[str, Any], situation_type: str) -> str:
    rh = cfg.get("revisit_hours") or {}
    hours = float(rh.get(situation_type) or rh.get("default") or 24)
    return (_now() + timedelta(hours=hours)).isoformat()


def _owner(cfg: dict[str, Any], situation_type: str) -> str:
    return str((cfg.get("owners") or {}).get(situation_type) or "alex")


def _links(cfg: dict[str, Any], situation_type: str) -> list[str]:
    return list((cfg.get("cc_deep_links") or {}).get(situation_type) or [])


# ── Evidence helpers (accept mock or live-shaped packs) ─────────────────────


def extract_holdings(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize holdings from various domain shapes."""
    hd = evidence.get("holdings_detail") or evidence.get("holdings") or {}
    if isinstance(hd, list):
        return hd
    if isinstance(hd, dict):
        rows = hd.get("holdings") or hd.get("positions") or hd.get("data") or []
        if isinstance(rows, list):
            return rows
        # map symbol -> row
        if rows and isinstance(rows, dict):
            out = []
            for sym, row in rows.items():
                if isinstance(row, dict):
                    r = dict(row)
                    r.setdefault("symbol", sym)
                    out.append(r)
            return out
    return []


def holding_row(evidence: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    sym = symbol.upper()
    for h in extract_holdings(evidence):
        if str(h.get("symbol") or h.get("ticker") or "").upper() == sym:
            return h
    # flat mock: evidence["positions"][sym]
    pos = evidence.get("positions") or {}
    if isinstance(pos, dict) and sym in pos:
        r = dict(pos[sym])
        r["symbol"] = sym
        return r
    return None


def get_basis(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    for k in ("avg_cost", "average_cost", "cost_basis_per_share", "basis", "avg_cost_basis"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    # cost_basis domain map
    cb = evidence.get("cost_basis") or {}
    if isinstance(cb, dict):
        by_sym = cb.get("by_symbol") or cb.get("lots") or cb.get("data") or cb
        if isinstance(by_sym, dict):
            entry = by_sym.get(symbol.upper()) or by_sym.get(symbol)
            if isinstance(entry, dict):
                for k in ("avg_cost", "average_cost", "basis", "cost_per_share"):
                    v = _num(entry.get(k))
                    if v is not None and v > 0:
                        return v
            v = _num(entry) if not isinstance(entry, dict) else None
            if v and v > 0:
                return v
    return None


def get_last(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    for k in ("last", "price", "mark", "current_price", "last_price", "mkt_price"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    q = evidence.get("market_quote") or evidence.get("quotes") or {}
    if isinstance(q, dict):
        entry = q.get(symbol.upper()) or q.get("data", {}).get(symbol.upper()) if isinstance(q.get("data"), dict) else q.get(symbol.upper())
        if isinstance(entry, dict):
            for k in ("last", "price", "mark", "close"):
                v = _num(entry.get(k))
                if v is not None and v > 0:
                    return v
        v = _num(q.get("last") or q.get("price"))
        if v and v > 0:
            return v
    return None


def get_weight_pct(row: dict[str, Any]) -> Optional[float]:
    for k in ("weight_pct", "portfolio_weight_pct", "weight", "pct_of_portfolio"):
        v = _num(row.get(k))
        if v is not None:
            # if 0-1 fraction, convert
            if 0 < v <= 1.0:
                return v * 100.0
            return v
    return None


def get_stop(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    for k in ("stop", "stop_price", "protective_stop", "stop_level"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    risk = evidence.get("risk_snapshot") or evidence.get("risk") or {}
    if isinstance(risk, dict):
        stops = risk.get("stops") or risk.get("by_symbol") or risk.get("data") or {}
        if isinstance(stops, dict):
            entry = stops.get(symbol.upper()) or stops.get(symbol)
            if isinstance(entry, dict):
                for k in ("stop", "stop_price", "price"):
                    v = _num(entry.get(k))
                    if v is not None and v > 0:
                        return v
            v = _num(entry) if not isinstance(entry, dict) else None
            if v and v > 0:
                return v
        # no_stop list
        no_stop = risk.get("no_stop_symbols") or []
        if symbol.upper() in [str(x).upper() for x in no_stop]:
            return None
    if row.get("has_stop") is False or row.get("stop_missing") is True:
        return None
    return _num(row.get("stop_price"))


def get_mean_target(evidence: dict[str, Any], symbol: str) -> Optional[float]:
    ar = evidence.get("analyst_rollup") or evidence.get("analyst") or {}
    if isinstance(ar, dict):
        entry = ar.get(symbol.upper()) or ar.get("by_symbol", {}).get(symbol.upper()) if isinstance(ar.get("by_symbol"), dict) else ar.get(symbol.upper())
        if entry is None and ar.get("symbol", "").upper() == symbol.upper():
            entry = ar
        if isinstance(entry, dict):
            for k in ("mean_target", "target_mean", "avg_target", "price_target_mean", "target"):
                v = _num(entry.get(k))
                if v is not None and v > 0:
                    return v
    return None


def get_trough(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    for k in ("trough", "low_52w", "drawdown_low", "hwm_low", "period_low"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    ctx = evidence.get("path_context") or evidence.get("technicals") or {}
    if isinstance(ctx, dict):
        entry = ctx.get(symbol.upper()) or ctx
        if isinstance(entry, dict):
            for k in ("trough", "low_52w", "drawdown_low"):
                v = _num(entry.get(k))
                if v is not None and v > 0:
                    return v
    return None


def catalyst_tags(evidence: dict[str, Any], symbol: str) -> list[str]:
    cr = evidence.get("catalyst_record") or evidence.get("catalysts") or {}
    tags: list[str] = []
    items: list[Any] = []
    if isinstance(cr, list):
        items = cr
    elif isinstance(cr, dict):
        items = cr.get(symbol.upper()) or cr.get("items") or cr.get("events") or []
        if not items and cr.get("symbol", "").upper() == symbol.upper():
            items = cr.get("catalysts") or [cr]
    for it in items or []:
        if isinstance(it, str):
            tags.append(it.lower())
        elif isinstance(it, dict):
            for k in ("type", "tag", "name", "label", "event_type"):
                if it.get(k):
                    tags.append(str(it[k]).lower())
            if it.get("description"):
                tags.append(str(it["description"]).lower())
    return tags


def has_major_catalyst(tags: list[str]) -> bool:
    blob = " ".join(tags)
    return any(k in blob for k in ("earnings", "lockup", "lock-up", "fda", "merger", "offering"))


# ── Predicates ──────────────────────────────────────────────────────────────


def eval_s1(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    """POSITION_LIFECYCLE."""
    row = holding_row(evidence, symbol)
    if not row:
        return None
    thr = cfg.get("thresholds") or {}
    basis = get_basis(row, evidence, symbol)
    last = get_last(row, evidence, symbol)
    trough = get_trough(row, evidence, symbol)
    target = get_mean_target(evidence, symbol)
    tags = catalyst_tags(evidence, symbol)
    major_cat = has_major_catalyst(tags)

    refs = []
    fields = []
    if basis is not None:
        fields.append("basis")
    if last is not None:
        fields.append("last")
    if trough is not None:
        fields.append("trough")
    if target is not None:
        fields.append("mean_target")
    if tags:
        fields.append("catalysts")
    refs.append(_ref("holdings_detail", evidence.get("holdings_detail") or row, ["symbol", "shares"] + fields))
    if evidence.get("cost_basis"):
        refs.append(_ref("cost_basis", evidence["cost_basis"], ["avg_cost"]))
    if evidence.get("market_quote"):
        refs.append(_ref("market_quote", evidence["market_quote"], ["last"]))
    if evidence.get("analyst_rollup"):
        refs.append(_ref("analyst_rollup", evidence["analyst_rollup"], ["mean_target"]))
    if evidence.get("catalyst_record") or evidence.get("catalysts"):
        refs.append(_ref("catalyst_record", evidence.get("catalyst_record") or evidence.get("catalysts") or {}, ["type"]))

    reasons: list[str] = []
    dd_thr = float(thr.get("basis_drawdown_pct") or 25)
    reclaim_eps = float(thr.get("reclaim_eps_pct") or 1.0)
    part_rec = float(thr.get("partial_recovery_pct") or 15)

    if basis is None or last is None:
        # cannot evaluate path without basis/last — fail soft, no fire
        return None

    dd_pct = (basis - last) / basis * 100.0 if basis > 0 else 0.0
    if dd_pct >= dd_thr:
        reasons.append(f"deep_drawdown_from_basis_{dd_pct:.1f}pct")
    if trough is not None and basis > trough and last > trough:
        span = basis - trough
        if span > 0:
            rec_pct = (last - trough) / span * 100.0
            if rec_pct >= part_rec and last < basis:
                reasons.append(f"partial_recovery_from_trough_{rec_pct:.1f}pct_of_span")
    if basis > 0 and abs(last - basis) / basis * 100.0 <= reclaim_eps:
        reasons.append("basis_reclaim_zone")
    if last >= basis and dd_pct > 0:
        # recovered through basis after being down — still lifecycle if was material
        pass
    if major_cat:
        reasons.append("major_catalyst_while_held")

    if not reasons:
        return None

    # template summary — only cite available numbers
    bits = [f"Held {symbol}"]
    bits.append(f"basis={basis}")
    bits.append(f"last={last}")
    if trough is not None:
        bits.append(f"trough={trough}")
    if target is not None:
        bits.append(f"street_mean_target={target}")
    else:
        bits.append("street_mean_target=DATA_UNAVAILABLE")
    bits.append("reasons=" + ",".join(reasons))

    options = [
        {"id": "hold", "label": "Hold", "pros": "Stay in name; path may continue", "cons": "Drawdown risk remains"},
        {
            "id": "hold_stop_above_be",
            "label": "Hold + stop above break-even once last ≥ basis",
            "pros": "Protects reclaimed capital; advisory only",
            "cons": "Stop still operator-placed; no auto order",
        },
        {"id": "trim", "label": "Trim", "pros": "Reduce exposure after material path", "cons": "May cut recovery early"},
    ]
    rec = (
        f"Recommend reviewing hold vs hold+stop-above-BE (once last ≥ basis={basis}) vs trim. "
        f"Last={last}. Reasons: {', '.join(reasons)}. READ_ONLY_ADVISORY — no auto stop."
    )
    return {
        "situation_type": SITUATION_CODES["S1"],
        "symbols": [symbol.upper()],
        "title": f"S1 POSITION_LIFECYCLE — {symbol.upper()}",
        "summary": "; ".join(bits),
        "options": options,
        "recommendation": rec,
        "risks": [
            "Further drawdown if catalyst disappoints",
            "Stop placement is operator-owned; system will not place stops",
        ],
        "evidence_refs": refs,
        "fire_reasons": reasons,
    }


def eval_s2(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    """STOP_GAP."""
    row = holding_row(evidence, symbol)
    if not row:
        return None
    basis = get_basis(row, evidence, symbol)
    last = get_last(row, evidence, symbol)
    stop = get_stop(row, evidence, symbol)
    if basis is None or last is None:
        return None

    reasons: list[str] = []
    if stop is None:
        reasons.append("no_stop")
    else:
        # stop inconsistent: recovered toward/above basis but stop still deep underwater
        if last >= basis * 0.95 and stop < basis * 0.85:
            reasons.append("stop_deep_underwater_after_recovery")
        if last >= basis and stop < basis:
            reasons.append("last_at_or_above_basis_stop_below_be")

    # Fire when no stop and (last recovering toward basis OR last >= basis)
    thr = cfg.get("thresholds") or {}
    dd_thr = float(thr.get("basis_drawdown_pct") or 25)
    dd_pct = (basis - last) / basis * 100.0 if basis > 0 else 0
    if stop is None:
        if last >= basis:
            reasons.append("no_stop_above_be_after_reclaim_path")
        elif dd_pct >= dd_thr * 0.5:  # material underwater without stop
            reasons.append("no_stop_while_materially_underwater")

    # de-dupe reasons uniqueness
    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        return None
    # Require at least a meaningful gap: no stop, or inconsistent stop
    if "no_stop" not in reasons and "stop_deep_underwater_after_recovery" not in reasons and "last_at_or_above_basis_stop_below_be" not in reasons and "no_stop_above_be_after_reclaim_path" not in reasons and "no_stop_while_materially_underwater" not in reasons:
        return None

    refs = [
        _ref("holdings_detail", evidence.get("holdings_detail") or row, ["symbol", "basis", "last"]),
        _ref("risk_snapshot", evidence.get("risk_snapshot") or evidence.get("risk") or {}, ["stop"]),
    ]
    stop_s = "DATA_UNAVAILABLE" if stop is None else str(stop)
    options = [
        {
            "id": "place_stop_above_be",
            "label": "Advisory: place protective stop above break-even (not at BE)",
            "pros": "Locks reclaim if last ≥ basis",
            "cons": "Operator must place; system does not execute",
        },
        {"id": "review_stop_policy", "label": "Review stop policy vs basis", "pros": "Align risk with thesis", "cons": "Delay"},
        {"id": "hold_no_change", "label": "Hold without stop change", "pros": "No action", "cons": "Unprotected gap risk"},
    ]
    rec = (
        f"{symbol}: last={last}, basis={basis}, stop={stop_s}. "
        f"Advisory: if last ≥ basis, prefer stop *above* BE — not at BE. Reasons: {', '.join(reasons)}. "
        f"No auto order."
    )
    return {
        "situation_type": SITUATION_CODES["S2"],
        "symbols": [symbol.upper()],
        "title": f"S2 STOP_GAP — {symbol.upper()}",
        "summary": f"stop={stop_s}; basis={basis}; last={last}; reasons={','.join(reasons)}",
        "options": options,
        "recommendation": rec,
        "risks": ["Unprotected downside if no stop", "Operator execution required"],
        "evidence_refs": refs,
        "fire_reasons": reasons,
    }


def eval_s3(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str | None = None) -> list[dict[str, Any]]:
    """REENTRY_CANDIDATE — read reentry desk only."""
    desk = evidence.get("reentry_decision_desk") or evidence.get("reentry") or {}
    thr = cfg.get("thresholds") or {}
    ok_status = {str(s).upper() for s in (thr.get("reentry_statuses") or ["READY", "NEAR"])}
    rows = []
    if isinstance(desk, dict):
        rows = desk.get("candidates") or desk.get("items") or desk.get("rows") or desk.get("data") or []
        if isinstance(rows, dict):
            rows = [{"symbol": k, **v} if isinstance(v, dict) else {"symbol": k, "status": v} for k, v in rows.items()]
    elif isinstance(desk, list):
        rows = desk
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym:
            continue
        if symbol and sym != symbol.upper():
            continue
        st = str(r.get("status") or r.get("decision") or r.get("state") or "").upper()
        if st not in ok_status:
            continue
        refs = [_ref("reentry_decision_desk", desk if isinstance(desk, dict) else {"items": rows}, ["status", "symbol"])]
        out.append({
            "situation_type": SITUATION_CODES["S3"],
            "symbols": [sym],
            "title": f"S3 REENTRY_CANDIDATE — {sym}",
            "summary": f"reentry_desk status={st} (read-only; not re-ranked)",
            "options": [
                {"id": "watch_reentry", "label": "Watch reentry levels", "pros": "Follow desk", "cons": "May miss fill"},
                {"id": "staged_interest", "label": "Staged interest plan (advisory)", "pros": "Size framing only", "cons": "No order"},
                {"id": "pass", "label": "Pass", "pros": "Capital preserved", "cons": "Miss recovery"},
            ],
            "recommendation": f"{sym} reentry desk={st}. Surface only — no broker order. Align sizing with Steph if proceeding.",
            "risks": ["False READY from desk lag", "Does not create orders"],
            "evidence_refs": refs,
            "fire_reasons": [f"reentry_{st}"],
        })
    return out


def eval_s4(evidence: dict[str, Any], cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    rot = evidence.get("rotation_ladders") or evidence.get("sector_momentum") or evidence.get("rotation") or {}
    holdings = extract_holdings(evidence)
    if not rot and not holdings:
        return None
    # Fire if explicit material_change flag or non-empty rotation with held sectors
    material = False
    if isinstance(rot, dict):
        material = bool(rot.get("material_change") or rot.get("changed") or rot.get("ladders") or rot.get("sectors"))
    elif isinstance(rot, list) and rot:
        material = True
    if not material:
        return None
    held_syms = [str(h.get("symbol") or "").upper() for h in holdings if h.get("symbol")]
    refs = [_ref("rotation", rot if isinstance(rot, dict) else {"items": rot}, ["material_change", "ladders"])]
    if holdings:
        refs.append(_ref("holdings_detail", evidence.get("holdings_detail") or {}, ["weights"]))
    return {
        "situation_type": SITUATION_CODES["S4"],
        "symbols": held_syms[:12],
        "title": "S4 SECTOR_ROTATION — material ladder/momentum change",
        "summary": "sector_momentum/rotation_ladders material_change flagged vs holdings weights",
        "options": [
            {"id": "review_weights", "label": "Review sector weights", "pros": "Align with momentum", "cons": "Turnover"},
            {"id": "hold_allocation", "label": "Hold allocation", "pros": "Stability", "cons": "Drift vs momentum"},
        ],
        "recommendation": "Steph+Alex: review rotation ladders against held sector weights. Advisory only.",
        "risks": ["Rotation signal lag", "Correlation spike"],
        "evidence_refs": refs,
        "fire_reasons": ["rotation_material_change"],
    }


def eval_s5(evidence: dict[str, Any], cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    thr = cfg.get("thresholds") or {}
    cash_band = float(thr.get("cash_pct_band_min") or 15.0)
    cash_pack = evidence.get("cash") or evidence.get("buying_power") or evidence.get("portfolio") or {}
    cash_pct = None
    cash_quality = "OK"
    if isinstance(cash_pack, dict):
        cash_pct = _num(cash_pack.get("cash_pct") or cash_pack.get("cash_weight_pct") or cash_pack.get("pct_cash"))
        if cash_pack.get("quality_state") in ("PARTIAL", "STALE"):
            cash_quality = str(cash_pack.get("quality_state"))
        if cash_pack.get("partial"):
            cash_quality = "PARTIAL"
    # portfolio totals
    port = evidence.get("portfolio") or {}
    if cash_pct is None and isinstance(port, dict):
        tv = _num(port.get("total_value") or port.get("portfolio_value"))
        cash = _num(port.get("total_cash") or port.get("cash"))
        if tv and cash is not None and tv > 0:
            cash_pct = cash / tv * 100.0
    if cash_pct is None:
        return None
    if cash_pct < cash_band:
        return None
    # constructive rotation or watch READY cluster
    rot = evidence.get("rotation_ladders") or evidence.get("sector_momentum") or {}
    constructive = False
    if isinstance(rot, dict) and (rot.get("constructive") or rot.get("material_change") or rot.get("bias") in ("risk_on", "constructive")):
        constructive = True
    watch = evidence.get("watch_intelligence") or evidence.get("watch") or {}
    ready_n = 0
    if isinstance(watch, dict):
        items = watch.get("items") or watch.get("candidates") or watch.get("rows") or []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and str(it.get("status") or it.get("signal") or "").upper() in ("READY", "GO"):
                    ready_n += 1
    if ready_n >= 2:
        constructive = True
    if not constructive and not (isinstance(rot, dict) and rot.get("ladders")):
        # still allow fire if cash high + explicit constructive flag missing but watch cluster
        if ready_n < 1:
            return None
    refs = [
        _ref("cash", cash_pack if isinstance(cash_pack, dict) else {"cash_pct": cash_pct}, ["cash_pct"]),
    ]
    if cash_quality != "OK":
        refs[0]["quality_state"] = cash_quality
    summary = f"cash_pct={cash_pct:.2f} (band_min={cash_band}); quality={cash_quality}; watch_ready_go={ready_n}"
    return {
        "situation_type": SITUATION_CODES["S5"],
        "symbols": [],
        "title": "S5 CASH_DEPLOYMENT — cash above policy band",
        "summary": summary,
        "options": [
            {"id": "staged_deploy", "label": "Staged deployment options (advisory)", "pros": "Put cash to work gradually", "cons": "Timing risk"},
            {"id": "hold_cash", "label": "Hold cash reserve", "pros": "Dry powder", "cons": "Opportunity cost"},
            {"id": "exit_if_fades", "label": "Pre-define revisit if momentum fades", "pros": "Discipline", "cons": "Requires operator"},
        ],
        "recommendation": (
            f"Cash share {cash_pct:.2f}% exceeds band {cash_band}% (quality={cash_quality}). "
            f"Stage deployment options only — never 'buy now' execution. Revisit if rotation fades."
        ),
        "risks": ["Soft cash figure" if cash_quality == "PARTIAL" else "Opportunity cost of idle cash", "No auto deploy"],
        "evidence_refs": refs,
        "fire_reasons": [f"cash_pct_above_band", f"quality_{cash_quality}"],
    }


def eval_s6(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str | None = None) -> list[dict[str, Any]]:
    thr = cfg.get("thresholds") or {}
    w_thr = float(thr.get("concentration_weight_pct") or 12.0)
    loss_thr = float(thr.get("disposition_loss_pct") or 20.0)
    months_thr = float(thr.get("disposition_hold_months") or 6.0)
    out = []
    for row in extract_holdings(evidence):
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        if symbol and sym != symbol.upper():
            continue
        reasons = []
        w = get_weight_pct(row)
        if w is not None and w >= w_thr:
            reasons.append(f"weight_{w:.1f}pct")
        basis = get_basis(row, evidence, sym)
        last = get_last(row, evidence, sym)
        loss_pct = None
        if basis and last and basis > 0 and last < basis:
            loss_pct = (basis - last) / basis * 100.0
            hold_m = _num(row.get("holding_months") or row.get("hold_months") or row.get("months_held"))
            if loss_pct >= loss_thr and hold_m is not None and hold_m >= months_thr:
                reasons.append(f"disposition_loss_{loss_pct:.1f}pct_hold_{hold_m}m")
            elif loss_pct >= loss_thr and row.get("disposition_flag"):
                reasons.append(f"disposition_flag_loss_{loss_pct:.1f}pct")
        if row.get("disposition_flag") and "disposition" not in " ".join(reasons):
            reasons.append("disposition_flag")
        if not reasons:
            continue
        refs = [_ref("holdings_detail", row, ["weight_pct", "basis", "last", "holding_months"])]
        out.append({
            "situation_type": SITUATION_CODES["S6"],
            "symbols": [sym],
            "title": f"S6 CONCENTRATION_OR_DISPOSITION — {sym}",
            "summary": f"reasons={','.join(reasons)}; weight={w}; loss_pct={loss_pct}",
            "options": [
                {"id": "trim", "label": "Trim concentration", "pros": "Reduce single-name risk", "cons": "Tax/feel"},
                {"id": "hold_with_thesis", "label": "Hold with explicit thesis", "pros": "Conviction", "cons": "Bias risk"},
                {"id": "morgan_review", "label": "Morgan behavioral review", "pros": "Disposition Rule-1", "cons": "Delay"},
            ],
            "recommendation": f"Morgan primary: {sym} — {', '.join(reasons)}. Alex synthesizes. Advisory only.",
            "risks": ["Disposition effect", "Concentration gap risk"],
            "evidence_refs": refs,
            "fire_reasons": reasons,
        })
    return out


def eval_s7(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str | None = None) -> list[dict[str, Any]]:
    thr = cfg.get("thresholds") or {}
    ok = {str(s).upper() for s in (thr.get("watch_statuses") or ["READY", "GO", "NEAR"])}
    near_min = float(thr.get("watch_near_min_score") or 70)
    watch = evidence.get("watch_intelligence") or evidence.get("watch") or {}
    items = []
    if isinstance(watch, dict):
        items = watch.get("items") or watch.get("candidates") or watch.get("rows") or []
    elif isinstance(watch, list):
        items = watch
    held = {str(h.get("symbol") or "").upper() for h in extract_holdings(evidence)}
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or it.get("ticker") or "").upper()
        if not sym:
            continue
        if symbol and sym != symbol.upper():
            continue
        st = str(it.get("status") or it.get("signal") or it.get("tier") or "").upper()
        score = _num(it.get("score") or it.get("watch_score"))
        if st == "NEAR" and score is not None and score < near_min:
            continue
        if st not in ok:
            continue
        if st == "NEAR" and score is None and not it.get("strong_near"):
            # require strong NEAR marker if no score
            continue
        is_held = sym in held
        tags = catalyst_tags(evidence, sym)
        if is_held and not has_major_catalyst(tags) and not it.get("street_shift"):
            # held without new catalyst — still allow READY/GO as promotion note
            if st not in ("READY", "GO"):
                continue
        refs = [_ref("watch_intelligence", it, ["status", "score"])]
        out.append({
            "situation_type": SITUATION_CODES["S7"],
            "symbols": [sym],
            "title": f"S7 WATCH_PROMOTION — {sym}",
            "summary": f"watch status={st}; held={is_held}; score={score}",
            "options": [
                {"id": "promote_research", "label": "Promote for research/size framing", "pros": "Follow Watch desk", "cons": "Not an order"},
                {"id": "keep_watch", "label": "Keep on watch", "pros": "Patience", "cons": "Miss move"},
            ],
            "recommendation": f"{sym} Watch desk={st} (not re-ranked). Held={is_held}. Maria evidence → Alex synthesis. No order.",
            "risks": ["Desk lag", "False GO"],
            "evidence_refs": refs,
            "fire_reasons": [f"watch_{st}"],
        })
    return out


def eval_s8(evidence: dict[str, Any], cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    thr = cfg.get("thresholds") or {}
    labels = {str(x).lower() for x in (thr.get("regime_risk_off_labels") or ["risk_off", "defensive"])}
    regime = evidence.get("risk_regime") or evidence.get("regime") or {}
    risk = evidence.get("risk_snapshot") or evidence.get("risk") or {}
    defensive = evidence.get("defensive") or evidence.get("defense") or {}
    reasons = []
    if isinstance(regime, dict):
        lab = str(regime.get("label") or regime.get("regime") or regime.get("state") or "").lower()
        if lab in labels or regime.get("risk_off") is True:
            reasons.append(f"regime_{lab or 'risk_off'}")
    if isinstance(risk, dict):
        heat = _num(risk.get("heat") or risk.get("portfolio_heat") or risk.get("heat_score"))
        if heat is not None and heat >= float(risk.get("heat_threshold") or thr.get("heat_threshold") or 70):
            reasons.append(f"heat_{heat}")
        if risk.get("heat_up") or risk.get("heat_increased"):
            reasons.append("heat_increased")
    if isinstance(defensive, dict) and (defensive.get("material_proposals") or defensive.get("proposals")):
        reasons.append("defensive_proposals")
    if not reasons:
        return None
    refs = []
    if regime:
        refs.append(_ref("risk_regime", regime if isinstance(regime, dict) else {}, ["label"]))
    if risk:
        refs.append(_ref("risk_snapshot", risk if isinstance(risk, dict) else {}, ["heat", "stops"]))
    return {
        "situation_type": SITUATION_CODES["S8"],
        "symbols": [],
        "title": "S8 DEFENSIVE_REGIME",
        "summary": "reasons=" + ",".join(reasons),
        "options": [
            {"id": "tighten_risk", "label": "Tighten risk review (advisory)", "pros": "Protect capital", "cons": "May cut winners"},
            {"id": "review_stops", "label": "Review stop coverage", "pros": "Gap control", "cons": "Operator action"},
            {"id": "hold_course", "label": "Hold course with monitoring", "pros": "Avoid whipsaw", "cons": "Regime risk"},
        ],
        "recommendation": f"Alex+risk: defensive posture signals ({', '.join(reasons)}). Review stops/heat. No auto orders.",
        "risks": ["Regime flip", "Over-hedging"],
        "evidence_refs": refs,
        "fire_reasons": reasons,
    }


# ── Detector orchestration ──────────────────────────────────────────────────


class CIOSituationDetector:
    """Run S1–S8 predicates and persist draft plans (SHADOW)."""

    def __init__(
        self,
        *,
        config_path: Path | str | None = None,
        plan_store: Optional[CIOPlanStore] = None,
        event_bus: Any = None,
        goal_store: Any = None,
    ):
        self.cfg = load_config(config_path)
        self.plans = plan_store or CIOPlanStore()
        self.bus = event_bus
        self.goals = goal_store
        self.detector_version = str(self.cfg.get("detector_version") or DETECTOR_VERSION)

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def collect_candidates(self, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate all situations against evidence pack (no I/O)."""
        cfg = self.cfg
        found: list[dict[str, Any]] = []
        symbols = set()
        for h in extract_holdings(evidence):
            s = str(h.get("symbol") or "").upper()
            if s:
                symbols.add(s)
        # also from explicit list
        for s in evidence.get("symbols") or []:
            symbols.add(str(s).upper())

        for sym in sorted(symbols):
            try:
                r = eval_s1(evidence, cfg, sym)
                if r:
                    found.append(r)
            except Exception:
                pass
            try:
                r = eval_s2(evidence, cfg, sym)
                if r:
                    found.append(r)
            except Exception:
                pass
            try:
                found.extend(eval_s6(evidence, cfg, sym))
            except Exception:
                pass

        try:
            found.extend(eval_s3(evidence, cfg))
        except Exception:
            pass
        try:
            r = eval_s4(evidence, cfg)
            if r:
                found.append(r)
        except Exception:
            pass
        try:
            r = eval_s5(evidence, cfg)
            if r:
                found.append(r)
        except Exception:
            pass
        try:
            found.extend(eval_s7(evidence, cfg))
        except Exception:
            pass
        try:
            r = eval_s8(evidence, cfg)
            if r:
                found.append(r)
        except Exception:
            pass
        return found

    def _emit_situation_raised(self, plan: dict[str, Any]) -> None:
        if self.bus is None:
            try:
                from scripts.lib.cio_event_bus import CIOEventBus
                self.bus = CIOEventBus()
            except Exception:
                return
        try:
            self.bus.emit(
                "situation.raised",
                {
                    "plan_id": plan.get("plan_id"),
                    "situation_type": plan.get("situation_type"),
                    "symbols": plan.get("symbols"),
                    "owner_agent": plan.get("owner_agent"),
                    "shadow": bool(self.cfg.get("shadow", True)),
                },
                source="cio_situation_detector",
            )
        except Exception:
            pass

    def persist_candidate(self, cand: dict[str, Any]) -> Optional[dict[str, Any]]:
        st = cand["situation_type"]
        syms = cand.get("symbols") or []
        dedup_h = float(self.cfg.get("dedup_hours") or 6)
        existing = self.plans.find_recent_dedup(st, syms, within_hours=dedup_h)
        if existing:
            return None  # dedup skip
        owner = _owner(self.cfg, st)
        # optional goal link
        linked_goals: list[str] = []
        if self.goals is None:
            try:
                from scripts.lib.cio_goals import CIOGoalStore
                self.goals = CIOGoalStore()
            except Exception:
                self.goals = False  # type: ignore
        if self.goals and self.goals is not False:
            try:
                open_g = self.goals.list_open_goals(owner_agent=owner, limit=20)
                for g in open_g:
                    gsyms = {str(x).upper() for x in (g.get("linked_symbols") or [])}
                    if not syms or gsyms & {s.upper() for s in syms}:
                        linked_goals.append(g["goal_id"])
                        if len(linked_goals) >= 3:
                            break
            except Exception:
                pass

        plan = self.plans.create_plan(
            situation_type=st,
            symbols=syms,
            title=cand["title"],
            summary=cand.get("summary") or "",
            options=cand["options"],
            recommendation=cand["recommendation"],
            risks=cand.get("risks") or [],
            evidence_refs=cand.get("evidence_refs") or [],
            linked_goal_ids=linked_goals,
            revisit_at=_revisit(self.cfg, st),
            owner_agent=owner,
            cc_deep_links=_links(self.cfg, st),
            status="draft",
            detector_version=self.detector_version,
            actor_id="cio_situation_detector",
            extra={"fire_reasons": cand.get("fire_reasons") or [], "shadow": bool(self.cfg.get("shadow", True))},
        )
        self._emit_situation_raised(plan)
        # P2b: enrich narrative (LLM under cap, else template)
        # In tests, set CIO_LLM_ENRICH=0 for speed; still applies template path.
        try:
            from scripts.lib.cio_plan_enrichment import enrich_plan, maybe_notify_plan
            enr = enrich_plan(
                plan,
                source=st,
                wake_id=f"situation:{st}:{','.join(syms)[:40]}",
                plan_store=self.plans,
                force_template=os.environ.get("CIO_LLM_ENRICH", "1").strip().lower()
                in ("0", "false", "off", "no"),
            )
            if enr.get("plan"):
                plan = enr["plan"]
            try:
                maybe_notify_plan(plan)
            except Exception:
                pass
        except Exception:
            pass
        return plan

    def run(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Full detector pass. Fail-soft: never raises to caller for domain issues."""
        out: dict[str, Any] = {
            "ts": _now_iso(),
            "enabled": self.enabled(),
            "shadow": bool(self.cfg.get("shadow", True)),
            "notify": bool(self.cfg.get("notify", False)),
            "detector_version": self.detector_version,
            "candidates": 0,
            "plans_created": [],
            "dedup_skipped": 0,
            "errors": [],
            "authority": "READ_ONLY_ADVISORY",
        }
        if not out["enabled"]:
            out["errors"].append("detector_disabled")
            return out
        try:
            cands = self.collect_candidates(evidence)
        except Exception as exc:
            out["errors"].append(f"collect:{type(exc).__name__}:{exc}")
            return out
        out["candidates"] = len(cands)
        for c in cands:
            try:
                plan = self.persist_candidate(c)
                if plan:
                    out["plans_created"].append(plan.get("plan_id"))
                else:
                    out["dedup_skipped"] += 1
            except Exception as exc:
                out["errors"].append(f"persist:{c.get('situation_type')}:{exc}")
        return out


def build_evidence_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map heartbeat-style snapshot domains into detector evidence (best-effort)."""
    domains = snapshot.get("domains") or snapshot
    evidence: dict[str, Any] = {}
    if isinstance(domains, dict):
        for k, v in domains.items():
            if isinstance(v, dict) and "data" in v:
                evidence[k] = v.get("data") if v.get("data") is not None else v
            else:
                evidence[k] = v
    # aliases
    if "holdings_detail" not in evidence and "portfolio" in evidence:
        evidence.setdefault("holdings_detail", evidence.get("portfolio"))
    return evidence


def run_detector_safe(
    evidence: Optional[dict[str, Any]] = None,
    *,
    snapshot: Optional[dict[str, Any]] = None,
    plan_store: Optional[CIOPlanStore] = None,
) -> dict[str, Any]:
    """Entry point for heartbeat/reactive hooks — never raises."""
    try:
        det = CIOSituationDetector(plan_store=plan_store)
        if evidence is None and snapshot is not None:
            evidence = build_evidence_from_snapshot(snapshot)
        if evidence is None:
            return {"ts": _now_iso(), "enabled": det.enabled(), "errors": ["no_evidence"], "plans_created": []}
        return det.run(evidence)
    except Exception as exc:
        return {
            "ts": _now_iso(),
            "errors": [f"detector_fatal:{type(exc).__name__}:{exc}"],
            "plans_created": [],
            "authority": "READ_ONLY_ADVISORY",
        }
