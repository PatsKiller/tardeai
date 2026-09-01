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
    # Naming footgun: docs/ops mixed CIO_SITUATIONS_NOTIFY (plural, yaml) with
    # CIO_SITUATION_NOTIFY (singular, enrichment). Accept either (OR). Default off.
    notify_on = False
    notify_seen = False
    for key in ("CIO_SITUATIONS_NOTIFY", "CIO_SITUATION_NOTIFY"):
        raw = os.environ.get(key)
        if raw is None:
            continue
        notify_seen = True
        if raw.strip().lower() in ("1", "true", "on", "yes"):
            notify_on = True
            break
    if notify_seen:
        cfg["notify"] = notify_on
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


def _is_cash_row(row: dict[str, Any]) -> bool:
    sym = str(row.get("symbol") or "").upper()
    if row.get("is_cash") is True:
        return True
    if sym in ("CASH", "USD", "MMDA", "SPAXX", "VMFXX", "FDRXX", "SGOV"):
        return True
    at = str(row.get("asset_type") or row.get("type") or "").lower()
    return at in ("cash", "money_market", "currency")


# ── dust rule (S1 + S6) ──────────────────────────────────────────────────────
# Both evaluators ask a question that presupposes a position, and both reached a
# residual through a *price-ratio* branch that a residual can never escape:
#
#   S6  disposition_loss_100.0pct_hold_36.0m   (basis - last) / basis
#   S1  deep_drawdown_from_basis_…pct          (basis - last) / basis  >= 25%
#
# A $0.90 residual is permanently ~100% below its cost basis, so both fire on
# every pass forever. That is why cancelling never held: 20 S6 plans cancelled on
# 2026-08-29 and one back within twenty minutes, and 35 open S1 plans across
# JEPI (20), SRNE (14) and LDOS (1) accumulated the same way.
# It fired forever on SRNE: a $0.90 residual against its cost basis is a 100%
# loss held 36 months, so the disposition branch matched on every pass — and a
# residual can never stop being a 100% loss. Twenty such plans were cancelled by
# hand on 2026-08-29 and a new one reappeared within twenty minutes.
#
# Same documented threshold as everywhere else in Wave 2 (holdings_universe
# .DUST_POLICY): aggregate market value < $50 per ticker. Two guards carry over —
# the value is aggregated across accounts, and an UNKNOWN value is never dust, so
# a missing price cannot silently suppress a real concentration.
#
# This only ever SKIPS a fire. No threshold is loosened and no new fire is added.

def _subject_skip_reason(
    symbol: str,
    *,
    market_value: float | None,
    market_value_known: bool,
) -> Optional[str]:
    """Why S6 must not fire on this subject, or None when it may.

    Fails OPEN. The only caller of eval_s6 wraps it in `except Exception: pass`,
    so anything raised here would silently disable S6 *entirely* — trading a
    nuisance dust plan for a missed concentration alert. If the policy module
    cannot be read, fall back to the pre-rule behaviour and let the subject
    through rather than losing the detector.
    """
    try:
        from scripts.lib.holdings_universe import (
            CASH_SYMBOLS,
            classify_instrument_id,
            is_dust_market_value,
            is_held_equity_ticker,
        )
    except Exception:
        return None

    sym = str(symbol or "").strip().upper()
    if not sym:
        return "no_symbol"
    if sym in CASH_SYMBOLS:
        return "cash_or_non_entity"
    # Only genuine instrument ids are excluded here — a CUSIP or ISIN sitting in
    # the symbol column (Wave 2 slice 12). `is_held_equity_ticker` alone would be
    # too blunt: it rejects anything over five characters, which would also
    # silence the detector's own synthetic fixtures and any long symbol. The
    # narrow test is what this branch was always for.
    if not is_held_equity_ticker(sym) and classify_instrument_id(sym) in {"CUSIP", "ISIN"}:
        return "not_a_ticker"
    if not market_value_known:
        return None                      # unknown is HELD, never dust
    if is_dust_market_value(market_value):
        return "dust_residual"
    return None


def extract_holdings(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize holdings from various domain shapes (live broker + mock)."""
    hd = evidence.get("holdings_detail") or evidence.get("holdings") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(hd, list):
        rows = [r for r in hd if isinstance(r, dict)]
    elif isinstance(hd, dict):
        cand = hd.get("holdings") or hd.get("positions") or hd.get("data") or []
        if isinstance(cand, list):
            rows = [r for r in cand if isinstance(r, dict)]
        elif isinstance(cand, dict):
            for sym, row in cand.items():
                if isinstance(row, dict):
                    r = dict(row)
                    r.setdefault("symbol", sym)
                    rows.append(r)
    # Attach portfolio totals for weight recompute
    port = evidence.get("portfolio") or {}
    total = None
    if isinstance(port, dict):
        total = _num(port.get("total_value") or port.get("portfolio_value") or port.get("total_mv"))
    if total is None and isinstance(hd, dict):
        total = _num(hd.get("total_value"))
    if total is None and rows:
        total = sum(float(_num(r.get("market_value")) or 0) for r in rows) or None
    # Normalize last aliases; do NOT invent avg_cost from total cost_basis
    # (holdings_detail.cost_basis is often incomplete total — use cost_basis domain).
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
        if sym:
            row["symbol"] = sym
        if row.get("current_price") is not None and row.get("last") is None:
            row["last"] = row.get("current_price")
        # portfolio weight: recompute from MV / total
        mv = _num(row.get("market_value"))
        if total and total > 0 and mv is not None:
            row["portfolio_weight_pct"] = (mv / total) * 100.0
        out.append(row)
    return out


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
    # Prefer verified cost_basis domain (avg_cost_per_share) over holdings total $
    cb = evidence.get("cost_basis") or {}
    if isinstance(cb, dict):
        positions = cb.get("positions") or cb.get("data") or []
        if isinstance(positions, list):
            matches = [
                p for p in positions
                if isinstance(p, dict) and str(p.get("symbol") or "").upper() == symbol.upper()
            ]
            if matches:
                num = den = 0.0
                for p in matches:
                    sh = _num(p.get("shares") or p.get("quantity")) or 0.0
                    ac = _num(p.get("avg_cost_per_share") or p.get("avg_cost") or p.get("basis"))
                    if ac and sh > 0:
                        num += ac * sh
                        den += sh
                if den > 0:
                    return num / den
                for k in ("avg_cost_per_share", "avg_cost", "basis", "cost_per_share"):
                    v = _num(matches[0].get(k))
                    if v is not None and v > 0:
                        return v
        by_sym = cb.get("by_symbol") or cb.get("lots") or {}
        if isinstance(by_sym, dict):
            entry = by_sym.get(symbol.upper()) or by_sym.get(symbol)
            if isinstance(entry, dict):
                for k in ("avg_cost_per_share", "avg_cost", "average_cost", "basis", "cost_per_share"):
                    v = _num(entry.get(k))
                    if v is not None and v > 0:
                        return v
    for k in ("avg_cost", "average_cost", "cost_basis_per_share", "basis", "avg_cost_basis", "avg_cost_per_share"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    return None


def get_last(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    for k in ("last", "price", "mark", "current_price", "last_price", "mkt_price"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    # cost_basis domain current_price
    cb = evidence.get("cost_basis") or {}
    if isinstance(cb, dict):
        for p in cb.get("positions") or []:
            if isinstance(p, dict) and str(p.get("symbol") or "").upper() == symbol.upper():
                v = _num(p.get("current_price") or p.get("last"))
                if v and v > 0:
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
    """Portfolio weight percent. Prefer recomputed portfolio_weight_pct.

    Important: live broker rows use weight_pct already in percent (e.g. 0.70 = 0.70%,
    not a 0–1 fraction). Only convert bare ``weight`` when clearly a fraction.
    """
    for k in ("portfolio_weight_pct", "pct_of_portfolio"):
        v = _num(row.get(k))
        if v is not None:
            return v
    v = _num(row.get("weight_pct"))
    if v is not None:
        return v  # already percent on this host's holdings_detail
    v = _num(row.get("weight"))
    if v is not None:
        if 0 < v <= 1.0:
            return v * 100.0
        return v
    return None


def get_stop(row: dict[str, Any], evidence: dict[str, Any], symbol: str) -> Optional[float]:
    """Return stop price, or None if known-missing. Raises nothing.

    When risk domain only has aggregate stops_active (no per-symbol map),
    return a sentinel via row metadata: callers should treat unknown as
    DATA_UNAVAILABLE (not 'no stop').
    """
    for k in ("stop", "stop_price", "protective_stop", "stop_level"):
        v = _num(row.get(k))
        if v is not None and v > 0:
            return v
    risk = evidence.get("risk_snapshot") or evidence.get("risk") or {}
    if isinstance(risk, dict):
        stops = risk.get("stops") or risk.get("by_symbol") or risk.get("positions") or {}
        if isinstance(stops, dict) and stops:
            entry = stops.get(symbol.upper()) or stops.get(symbol)
            if isinstance(entry, dict):
                for k in ("stop", "stop_price", "price"):
                    v = _num(entry.get(k))
                    if v is not None and v > 0:
                        return v
            v = _num(entry) if not isinstance(entry, dict) else None
            if v and v > 0:
                return v
        no_stop = risk.get("no_stop_symbols") or []
        if symbol.upper() in [str(x).upper() for x in no_stop]:
            return None
        # Aggregate-only risk domain: stop state unknown (not fireable as no_stop)
        if risk.get("stops_active") is not None and not stops:
            row["_stop_unknown"] = True
            return -1.0  # sentinel: unknown (not missing)
    if row.get("has_stop") is False or row.get("stop_missing") is True:
        return None
    v = _num(row.get("stop_price"))
    return v if v and v > 0 else None


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


def catalyst_pack_for_symbol(evidence: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    """Prefer structured domain=catalyst pack for symbol; fail-soft None."""
    sym = (symbol or "").upper()
    by = evidence.get("catalyst_by_symbol")
    if isinstance(by, dict) and isinstance(by.get(sym), dict):
        return by[sym]
    for key in ("catalyst", "catalysts", "catalyst_record"):
        pack = evidence.get(key)
        if not isinstance(pack, dict):
            continue
        # Structured calendar pack
        if pack.get("domain") == "catalyst" or pack.get("events") is not None:
            psym = str(pack.get("symbol") or "").upper()
            if not psym or psym == sym or psym == "BOOK":
                return pack
        # Nested by symbol
        nested = pack.get(sym)
        if isinstance(nested, dict):
            return nested
    return None


def catalyst_tags(evidence: dict[str, Any], symbol: str) -> list[str]:
    tags: list[str] = []
    pack = catalyst_pack_for_symbol(evidence, symbol)
    if isinstance(pack, dict):
        for ev in pack.get("events") or []:
            if isinstance(ev, dict):
                for k in ("kind", "type", "tag", "name", "label", "event_type", "title", "severity"):
                    if ev.get(k):
                        tags.append(str(ev[k]).lower())
            elif isinstance(ev, str):
                tags.append(ev.lower())
        if pack.get("kind"):
            tags.append(str(pack["kind"]).lower())
        if pack.get("catalyst_type"):
            tags.append(str(pack["catalyst_type"]).lower())
        if pack.get("headline"):
            tags.append(str(pack["headline"]).lower())
    cr = evidence.get("catalyst_record") or evidence.get("catalysts") or {}
    items: list[Any] = []
    if isinstance(cr, list):
        items = cr
    elif isinstance(cr, dict) and cr.get("events") is None:
        items = cr.get(symbol.upper()) or cr.get("items") or []
        if not items and str(cr.get("symbol") or "").upper() == symbol.upper():
            items = cr.get("catalysts") or [cr]
    for it in items or []:
        if isinstance(it, str):
            tags.append(it.lower())
        elif isinstance(it, dict):
            for k in ("type", "tag", "name", "label", "event_type", "kind", "catalyst_type"):
                if it.get(k):
                    tags.append(str(it[k]).lower())
            if it.get("description"):
                tags.append(str(it["description"]).lower())
            if it.get("headline"):
                tags.append(str(it["headline"]).lower())
    return tags


def has_major_catalyst(tags: list[str]) -> bool:
    blob = " ".join(tags)
    return any(
        k in blob
        for k in (
            "earnings", "lockup", "lock-up", "fda", "merger", "offering",
            "regulatory", "guidance", "critical", "high",
        )
    )


def calendar_catalyst_material(
    evidence: dict[str, Any],
    symbol: str,
) -> tuple[bool, list[str], Optional[dict[str, Any]]]:
    """
    Structured calendar materiality: medium+ within research horizon, or high+ within warm horizon.

    Returns (is_material, fire_reason_tags, pack).
    """
    pack = catalyst_pack_for_symbol(evidence, symbol)
    if not pack or pack.get("quality") == "DATA_UNAVAILABLE" or pack.get("quality_state") == "DATA_UNAVAILABLE":
        return False, [], pack
    try:
        try:
            from lib.catalyst_domain import materiality_bump, catalyst_research_gap_eligible
            from lib.catalyst_policy import (
                HORIZON_HERMES_RESEARCH_GAP,
                HORIZON_HERMES_WARM,
                MIN_SEV_MATERIALITY_BUMP,
                MIN_SEV_RESEARCH_GAP,
                next_relevant_event,
                clamp_severity,
            )
        except Exception:
            from scripts.lib.catalyst_domain import (  # type: ignore
                materiality_bump,
                catalyst_research_gap_eligible,
            )
            from scripts.lib.catalyst_policy import (  # type: ignore
                HORIZON_HERMES_RESEARCH_GAP,
                HORIZON_HERMES_WARM,
                MIN_SEV_MATERIALITY_BUMP,
                MIN_SEV_RESEARCH_GAP,
                next_relevant_event,
                clamp_severity,
            )
        reasons: list[str] = []
        # High/critical ≤ warm horizon → materiality bump
        if materiality_bump(pack):
            ev = next_relevant_event(
                pack.get("events") or [],
                max_days=HORIZON_HERMES_WARM,
                min_sev=MIN_SEV_MATERIALITY_BUMP,
            )
            if ev:
                reasons.append(
                    f"calendar_catalyst_{clamp_severity(ev.get('severity'))}"
                    f"_{ev.get('kind')}_h{ev.get('horizon_days')}"
                )
        # Medium+ ≤ research gap horizon on held name → still material for S1 path
        elif catalyst_research_gap_eligible(pack):
            ev = next_relevant_event(
                pack.get("events") or [],
                max_days=HORIZON_HERMES_RESEARCH_GAP,
                min_sev=MIN_SEV_RESEARCH_GAP,
            )
            if ev:
                reasons.append(
                    f"calendar_catalyst_{clamp_severity(ev.get('severity'))}"
                    f"_{ev.get('kind')}_h{ev.get('horizon_days')}"
                )
        return bool(reasons), reasons, pack
    except Exception:
        return False, [], pack


# ── Predicates ──────────────────────────────────────────────────────────────


def _subject_market_value(evidence: dict[str, Any], symbol: str) -> tuple[float, bool]:
    """Aggregate market value for one symbol across accounts, plus known-ness.

    A single unpriced leg makes the aggregate unknown, so a real position with a
    missing price is never mistaken for a residual.
    """
    sym = str(symbol or "").upper()
    total = 0.0
    known = False
    saw_unpriced = False
    for row in extract_holdings(evidence):
        if str(row.get("symbol") or row.get("ticker") or "").upper() != sym:
            continue
        mv = _num(row.get("market_value"))
        if mv is None:
            saw_unpriced = True
        else:
            total += mv
            known = True
    return total, (known and not saw_unpriced)


def eval_s1_skip_reason(evidence: dict[str, Any], symbol: str) -> Optional[str]:
    """Why S1 must not fire on this subject, or None when it may. Read-only."""
    mv, known = _subject_market_value(evidence, symbol)
    return _subject_skip_reason(symbol, market_value=mv, market_value_known=known)


def eval_s1(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    """POSITION_LIFECYCLE."""
    row = holding_row(evidence, symbol)
    if not row:
        return None
    # A residual is not a position to have a lifecycle. Without this,
    # deep_drawdown_from_basis fires forever on a name that is already exited —
    # 35 such plans had accumulated on JEPI, SRNE and LDOS.
    if eval_s1_skip_reason(evidence, symbol):
        return None
    thr = cfg.get("thresholds") or {}
    basis = get_basis(row, evidence, symbol)
    last = get_last(row, evidence, symbol)
    trough = get_trough(row, evidence, symbol)
    target = get_mean_target(evidence, symbol)
    tags = catalyst_tags(evidence, symbol)
    major_cat = has_major_catalyst(tags)
    cal_material, cal_reasons, cat_pack = calendar_catalyst_material(evidence, symbol)

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
    if tags or cal_material:
        fields.append("catalysts")
    refs.append(_ref("holdings_detail", evidence.get("holdings_detail") or row, ["symbol", "shares"] + fields))
    if evidence.get("cost_basis"):
        refs.append(_ref("cost_basis", evidence["cost_basis"], ["avg_cost"]))
    if evidence.get("market_quote"):
        refs.append(_ref("market_quote", evidence["market_quote"], ["last"]))
    if evidence.get("analyst_rollup"):
        refs.append(_ref("analyst_rollup", evidence["analyst_rollup"], ["mean_target"]))
    if cat_pack:
        refs.append(cat_pack if cat_pack.get("domain") == "catalyst" else _ref(
            "catalyst", cat_pack, ["events", "max_severity", "next_event"],
        ))
    elif evidence.get("catalyst_record") or evidence.get("catalysts"):
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
    # Structured calendar: medium+ ≤10d or high ≤5d elevates materiality
    for r in cal_reasons:
        if r not in reasons:
            reasons.append(r)
    if cal_material and "major_catalyst_while_held" not in reasons:
        reasons.append("major_catalyst_while_held")

    if not reasons:
        return None
    # Noise control: pure "near basis" without DD / recovery / catalyst is not actionable
    material_path = any(
        r.startswith("deep_drawdown")
        or r.startswith("partial_recovery")
        or r == "major_catalyst_while_held"
        or r.startswith("calendar_catalyst_")
        for r in reasons
    )
    if not material_path and reasons == ["basis_reclaim_zone"]:
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
        "catalyst_pack": cat_pack,
    }


def eval_s2(evidence: dict[str, Any], cfg: dict[str, Any], symbol: str) -> Optional[dict[str, Any]]:
    """STOP_GAP."""
    row = holding_row(evidence, symbol)
    if not row:
        return None
    if _is_cash_row(row):
        return None
    basis = get_basis(row, evidence, symbol)
    last = get_last(row, evidence, symbol)
    stop = get_stop(row, evidence, symbol)
    if basis is None or last is None:
        return None
    # Unknown stop state (aggregate risk only) → do not spam no_stop for every name
    if stop is not None and stop < 0:
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
    # If only bare no_stop without underwater/reclaim context, skip (noise)
    if reasons == ["no_stop"]:
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
        # A held name is not a re-entry candidate. Re-entry is the former/watch
        # universe by definition (LITMUS_COVERAGE 2026-09-01: "S3 does not help
        # position coverage: intersection with held equity is empty by design").
        #
        # That intersection was empty only by accident of desk state, not by any
        # rule here: measured 2026-09-01 the desk carried
        #   (held=False, READY) 1 · (held=False, NEAR) 24
        #   (held=False, BLOCK) 71 · (held=True, BLOCK) 10
        # so all ten held names were excluded by BLOCK, and nothing in this
        # predicate looked at `held`. SCHG returned 0 for exactly that reason --
        # status=BLOCK, held=True -- and would have been emitted as a re-entry
        # candidate for a position already owned the moment the desk moved it to
        # NEAR. The empty intersection was luck, and it read like a rule.
        if r.get("held") is True:
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
    try:
        from scripts.lib.cio_subject_guid import stamp_row
        out = [stamp_row(c) for c in out]
    except Exception:
        pass
    return out


def eval_s4(evidence: dict[str, Any], cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    rot = evidence.get("rotation_ladders") or evidence.get("sector_momentum") or evidence.get("rotation") or {}
    holdings = extract_holdings(evidence)
    if not rot and not holdings:
        return None
    # Require explicit material flags — mere presence of sector tables is not enough
    material = False
    if isinstance(rot, dict):
        material = bool(
            rot.get("material_change")
            or rot.get("changed")
            or rot.get("material")
            or rot.get("significant_change")
        )
        # optional: large transition list with material marker
        transitions = rot.get("transitions") or []
        if not material and isinstance(transitions, list) and len(transitions) >= 3 and rot.get("alert"):
            material = True
    elif isinstance(rot, list) and rot and isinstance(rot[0], dict) and rot[0].get("material_change"):
        material = True
    if not material:
        return None
    held_syms = [
        str(h.get("symbol") or "").upper()
        for h in holdings
        if h.get("symbol") and not _is_cash_row(h)
    ]
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
    cash_pack = (
        evidence.get("cash_buying_power")
        or evidence.get("cash")
        or evidence.get("buying_power")
        or {}
    )
    cash_pct = None
    cash_quality = "OK"
    if isinstance(cash_pack, dict):
        cash_pct = _num(cash_pack.get("cash_pct") or cash_pack.get("cash_weight_pct") or cash_pack.get("pct_cash"))
        if cash_pack.get("quality_state") in ("PARTIAL", "STALE"):
            cash_quality = str(cash_pack.get("quality_state"))
        if cash_pack.get("partial"):
            cash_quality = "PARTIAL"
        # live domain: total_cash + portfolio.total_value
        if cash_pct is None:
            cash = _num(cash_pack.get("total_cash") or cash_pack.get("cash"))
            port = evidence.get("portfolio") or {}
            tv = _num(port.get("total_value") or port.get("portfolio_value")) if isinstance(port, dict) else None
            if tv is None:
                tv = _num((evidence.get("holdings_detail") or {}).get("total_value"))
            if tv and cash is not None and tv > 0:
                cash_pct = cash / tv * 100.0
                # derived cash is soft
                if "NOT_verified" in str(cash_pack.get("source") or ""):
                    cash_quality = "PARTIAL"
    # portfolio totals fallback
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
    # High cash alone is material for S5; rotation/watch are boosters not hard gates
    rot = evidence.get("rotation_ladders") or evidence.get("sector_momentum") or evidence.get("rotation") or {}
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
    # Always allow fire when cash well above band (idle capital is the situation)
    refs = [
        _ref(
            "cash_buying_power",
            cash_pack if isinstance(cash_pack, dict) else {"cash_pct": cash_pct},
            ["total_cash", "cash_pct"],
        ),
        _ref("portfolio", port if isinstance(port, dict) else {}, ["total_value"]),
    ]
    if cash_quality != "OK":
        refs[0]["quality_state"] = cash_quality
    summary = (
        f"cash_pct={cash_pct:.2f} (band_min={cash_band}); quality={cash_quality}; "
        f"watch_ready_go={ready_n}; constructive_rot={constructive}"
    )
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
    # Aggregate multi-account rows by symbol for true portfolio concentration
    by_sym: dict[str, dict[str, Any]] = {}
    for row in extract_holdings(evidence):
        if _is_cash_row(row):
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        if symbol and sym != symbol.upper():
            continue
        acc = by_sym.setdefault(sym, {
            "symbol": sym,
            "market_value": 0.0,
            "market_value_known": True,
            "rows": [],
            "last": get_last(row, evidence, sym),
        })
        row_mv = _num(row.get("market_value"))
        if row_mv is None:
            # One unpriced leg makes the aggregate unknown. Without this the sum
            # would read 0.0 and a real position would be mistaken for dust.
            acc["market_value_known"] = False
        acc["market_value"] = float(acc["market_value"] or 0) + float(row_mv or 0)
        acc["rows"].append(row)
        if acc.get("last") is None:
            acc["last"] = get_last(row, evidence, sym)

    port = evidence.get("portfolio") or evidence.get("holdings_detail") or {}
    total = _num(port.get("total_value") or port.get("portfolio_value")) if isinstance(port, dict) else None
    if total is None:
        total = sum(float(a["market_value"] or 0) for a in by_sym.values()) or None

    out = []
    skipped_subjects: list[dict[str, str]] = []
    for sym, acc in by_sym.items():
        skip = _subject_skip_reason(
            sym,
            market_value=acc.get("market_value"),
            market_value_known=bool(acc.get("market_value_known", True)),
        )
        if skip:
            skipped_subjects.append({"symbol": sym, "reason": skip})
            continue
        reasons = []
        w = None
        if total and total > 0:
            w = 100.0 * float(acc["market_value"] or 0) / float(total)
        else:
            # fallback first row weight
            w = get_weight_pct(acc["rows"][0]) if acc["rows"] else None
        if w is not None and w >= w_thr:
            reasons.append(f"weight_{w:.1f}pct")
        basis = get_basis(acc["rows"][0] if acc["rows"] else {}, evidence, sym)
        last = acc.get("last") or get_last(acc["rows"][0] if acc["rows"] else {}, evidence, sym)
        loss_pct = None
        hold_m = None
        # holding months from cost_basis domain
        cb = evidence.get("cost_basis") or {}
        if isinstance(cb, dict):
            for p in cb.get("positions") or []:
                if isinstance(p, dict) and str(p.get("symbol") or "").upper() == sym:
                    hm = _num(p.get("holding_months"))
                    if hm is not None:
                        hold_m = max(hold_m or 0, hm)
        if basis and last and basis > 0 and last < basis:
            loss_pct = (basis - last) / basis * 100.0
            if loss_pct >= loss_thr and hold_m is not None and hold_m >= months_thr:
                reasons.append(f"disposition_loss_{loss_pct:.1f}pct_hold_{hold_m}m")
            elif loss_pct >= loss_thr and any(r.get("disposition_flag") for r in acc["rows"]):
                reasons.append(f"disposition_flag_loss_{loss_pct:.1f}pct")
        if any(r.get("disposition_flag") for r in acc["rows"]) and "disposition" not in " ".join(reasons):
            reasons.append("disposition_flag")
        if not reasons:
            continue
        refs = [
            _ref("holdings_detail", acc["rows"][0], ["market_value", "portfolio_weight_pct", "last"]),
            _ref("cost_basis", evidence.get("cost_basis") or {}, ["avg_cost_per_share", "holding_months"]),
        ]
        out.append({
            "situation_type": SITUATION_CODES["S6"],
            "symbols": [sym],
            "title": f"S6 CONCENTRATION_OR_DISPOSITION — {sym}",
            "summary": f"reasons={','.join(reasons)}; weight={w}; loss_pct={loss_pct}; mv={acc.get('market_value')}",
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
    if skipped_subjects:
        # Visible, not silent: a dropped subject is reported on the candidates
        # that did fire, and in the dry receipt when nothing fired at all.
        for cand in out:
            cand["s6_skipped_subjects"] = skipped_subjects
    return out


def eval_s6_skipped_subjects(
    evidence: dict[str, Any], cfg: dict[str, Any], symbol: str | None = None,
) -> list[dict[str, str]]:
    """Subjects S6 refused, for a dry run that fires nothing. Read-only."""
    from scripts.lib.holdings_universe import is_dust_market_value  # noqa: F401  (policy anchor)

    by_sym: dict[str, dict[str, Any]] = {}
    for row in extract_holdings(evidence):
        if _is_cash_row(row):
            continue
        sym = str(row.get("symbol") or "").upper()
        if not sym or (symbol and sym != symbol.upper()):
            continue
        acc = by_sym.setdefault(sym, {"market_value": 0.0, "market_value_known": True})
        row_mv = _num(row.get("market_value"))
        if row_mv is None:
            acc["market_value_known"] = False
        acc["market_value"] = float(acc["market_value"] or 0) + float(row_mv or 0)
    out: list[dict[str, str]] = []
    for sym, acc in sorted(by_sym.items()):
        reason = _subject_skip_reason(
            sym,
            market_value=acc["market_value"],
            market_value_known=bool(acc["market_value_known"]),
        )
        if reason:
            out.append({"symbol": sym, "reason": reason})
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
    try:
        from scripts.lib.cio_subject_guid import stamp_row
        out = [stamp_row(c) for c in out]
    except Exception:
        pass
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


def fairness_order_s3(
    cands_sorted: list[dict[str, Any]],
    priority: dict[str, int],
) -> list[dict[str, Any]]:
    """If S3 candidates exist, guarantee one S3 sits before the persist cap.

    S5/S6 stay first. Does not raise notify or expand max_plans.
    """
    s3 = [c for c in cands_sorted if str(c.get("situation_type")) == "S3_REENTRY_CANDIDATE"]
    if not s3:
        return list(cands_sorted)
    first = s3[0]
    rest = [c for c in cands_sorted if c is not first]
    insert_at = 0
    for i, c in enumerate(rest):
        pr = priority.get(str(c.get("situation_type")), 9)
        if pr > 1:
            insert_at = i
            break
        insert_at = i + 1
    return rest[:insert_at] + [first] + rest[insert_at:]


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

    def persist_candidate(
        self,
        cand: dict[str, Any],
        *,
        do_notify: bool = True,
    ) -> Optional[dict[str, Any]]:
        st = cand["situation_type"]
        syms = cand.get("symbols") or []
        dedup_h = float(self.cfg.get("dedup_hours") or 6)
        existing = self.plans.find_recent_dedup(st, syms, within_hours=dedup_h)
        if existing:
            return None  # dedup skip
        if st == "S1_POSITION_LIFECYCLE":
            for s in syms:
                if self.plans.list_open_plans(situation_type=st, symbol=s, limit=1):
                    return None  # skip duplicate open S1 same symbol
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

        revisit_at = _revisit(self.cfg, st)
        # Tighten revisit when structured catalyst pack has medium+ within horizon
        cat_pack = cand.get("catalyst_pack")
        if not cat_pack and cand.get("symbols"):
            # best-effort: pull from evidence_refs already on candidate
            for r in cand.get("evidence_refs") or []:
                if isinstance(r, dict) and (r.get("domain") == "catalyst" or r.get("events") is not None):
                    cat_pack = r
                    break
        if cat_pack:
            try:
                try:
                    from lib.catalyst_domain import adjust_revisit_at
                except Exception:
                    from scripts.lib.catalyst_domain import adjust_revisit_at  # type: ignore
                revisit_at = adjust_revisit_at(revisit_at, cat_pack).isoformat()
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
            revisit_at=revisit_at,
            owner_agent=owner,
            cc_deep_links=_links(self.cfg, st),
            status="draft",
            detector_version=self.detector_version,
            actor_id="cio_situation_detector",
            extra={
                "fire_reasons": cand.get("fire_reasons") or [],
                "shadow": bool(self.cfg.get("shadow", True)),
                "catalyst_max_severity": (cat_pack or {}).get("max_severity") if isinstance(cat_pack, dict) else None,
            },
        )
        self._emit_situation_raised(plan)
        # P5: open situation wake trace (synthetic wake_id; fail-soft)
        sit_wake_id = f"situation:{st}:{','.join(syms)[:40]}"
        try:
            from scripts.lib.cio_wake_traces import open_trace
            open_trace(
                wake_id=sit_wake_id,
                source="situation.raised",
                situation_type=st,
                agent_id=owner or "alex",
                plan_id=plan.get("plan_id"),
                thesis_version=plan.get("thesis_version"),
            )
        except Exception:
            try:
                from lib.cio_wake_traces import open_trace  # type: ignore
                open_trace(
                    wake_id=sit_wake_id,
                    source="situation.raised",
                    situation_type=st,
                    agent_id=owner or "alex",
                    plan_id=plan.get("plan_id"),
                )
            except Exception:
                pass
        # P2b: enrich under LIVE desk@vN (safe_context_block + safe_current_pin).
        # Material situations always attempt LLM unless CIO_LLM_FORCE_TEMPLATE=1.
        # CIO_LLM_ENRICH=0 still forces template for routine tests only.
        try:
            from scripts.lib.cio_plan_enrichment import (
                enrich_plan, maybe_notify_plan, is_material_plan,
            )
            force_tpl = os.environ.get("CIO_LLM_ENRICH", "1").strip().lower() in (
                "0", "false", "off", "no",
            )
            force_hard = os.environ.get("CIO_LLM_FORCE_TEMPLATE", "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            # Gate deferred path: material plans still get enrichment under live pin
            if force_tpl and not force_hard:
                try:
                    if is_material_plan({**plan, "fire_reasons": cand.get("fire_reasons") or []}):
                        force_tpl = False
                except Exception:
                    pass
            enr = enrich_plan(
                plan,
                source=st,
                wake_id=sit_wake_id,
                plan_store=self.plans,
                force_template=force_tpl,
            )
            if enr.get("plan"):
                plan = enr["plan"]
            # attach llm status for notify clarity
            plan.setdefault("llm_status", enr.get("llm"))
            plan.setdefault("narrative_source", enr.get("narrative_source"))
            # fire_reasons live in create extra — promote for Telegram "Why"
            if not plan.get("fire_reasons"):
                plan["fire_reasons"] = (
                    cand.get("fire_reasons")
                    or (plan.get("extra") or {}).get("fire_reasons")
                    or []
                )
            if do_notify:
                try:
                    plan["_notified"] = bool(maybe_notify_plan(plan))
                except Exception:
                    plan["_notified"] = False
            # Hermes research loop: S1/S6/S8 material gaps → fingerprint enqueue (fail-soft)
            try:
                try:
                    from lib.hermes_research_loop import emit_research_for_plan
                except Exception:
                    from scripts.lib.hermes_research_loop import emit_research_for_plan  # type: ignore
                # Promote fire_reasons for escalation heuristics
                if not plan.get("fire_reasons"):
                    plan["fire_reasons"] = cand.get("fire_reasons") or []
                hr = emit_research_for_plan(
                    plan,
                    reason=f"situation.raised:{st}",
                    actor_id="cio_situation_detector",
                )
                plan["hermes_enqueue"] = {
                    k: hr.get(k)
                    for k in ("ok", "reason", "research_id", "status", "skipped", "reused", "deduped")
                    if hr.get(k) is not None
                }
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
            "notified": 0,
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
        # Prefer high-value types first for cap (cash/concentration/lifecycle before mass stop noise)
        # S5/S6 first (book-level), then material S1 (DD), then stops/regime, then watch noise
        priority = {
            "S5_CASH_DEPLOYMENT": 0,
            "S6_CONCENTRATION_OR_DISPOSITION": 1,
            "S8_DEFENSIVE_REGIME": 2,
            "S1_POSITION_LIFECYCLE": 3,
            "S2_STOP_GAP": 4,
            "S3_REENTRY_CANDIDATE": 5,
            "S7_WATCH_PROMOTION": 6,
            "S4_SECTOR_ROTATION": 7,
        }
        cands_sorted = sorted(
            cands,
            key=lambda c: (priority.get(str(c.get("situation_type")), 9), str(c.get("symbols"))),
        )
        cands_sorted = fairness_order_s3(cands_sorted, priority)
        max_plans = int(self.cfg.get("max_plans_per_pass") or 5)
        max_notify = int(self.cfg.get("max_notify_per_pass") or 3)
        notified = 0
        for c in cands_sorted:
            if len(out["plans_created"]) >= max_plans:
                out["dedup_skipped"] += 1
                continue
            try:
                allow_notify = notified < max_notify
                plan = self.persist_candidate(c, do_notify=allow_notify)
                if plan:
                    out["plans_created"].append(plan.get("plan_id"))
                    if plan.pop("_notified", False):
                        notified += 1
                    out.setdefault("plans_detail", []).append({
                        "plan_id": plan.get("plan_id"),
                        "situation_type": plan.get("situation_type"),
                        "symbols": plan.get("symbols"),
                        "status": plan.get("status"),
                        "narrative_source": plan.get("narrative_source"),
                    })
                else:
                    out["dedup_skipped"] += 1
            except Exception as exc:
                out["errors"].append(f"persist:{c.get('situation_type')}:{exc}")
        out["notified"] = notified
        return out


def build_evidence_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Map heartbeat/Data Broker snapshot domains into detector evidence.

    Live ``get_cio_snapshot`` domains are flat dicts with ``state`` + fields
    (not always nested under ``data``). Preserve full domain payloads.
    """
    domains = snapshot.get("domains") or snapshot
    evidence: dict[str, Any] = {}
    if isinstance(domains, dict):
        for k, v in domains.items():
            if isinstance(v, dict) and "data" in v and v.get("data") is not None:
                # Nested envelope: prefer data but keep state/as_of on sibling keys
                payload = dict(v.get("data") or {})
                if isinstance(payload, dict):
                    for sk in ("state", "as_of", "quality_state", "source"):
                        if sk in v and sk not in payload:
                            payload[sk] = v[sk]
                    evidence[k] = payload
                else:
                    evidence[k] = v.get("data")
            else:
                evidence[k] = v
    # aliases for detectors
    if "holdings_detail" not in evidence and "portfolio" in evidence:
        evidence.setdefault("holdings_detail", evidence.get("portfolio"))
    if "risk_snapshot" not in evidence and "risk" in evidence:
        evidence["risk_snapshot"] = evidence.get("risk")
    if "cash" not in evidence and "cash_buying_power" in evidence:
        evidence["cash"] = evidence.get("cash_buying_power")
    return evidence


def enrich_evidence_with_catalysts(
    evidence: dict[str, Any],
    *,
    max_symbols: int = 8,
) -> dict[str, Any]:
    """
    Attach structured catalyst packs for held symbols (fail-soft).

    Sets evidence['catalyst_by_symbol'] and primary evidence['catalyst'] for
    the first held name so detectors see calendar severity without enrich-only path.
    """
    if not isinstance(evidence, dict):
        return evidence or {}
    try:
        rows = extract_holdings(evidence)
    except Exception:
        rows = []
    symbols: list[str] = []
    for r in rows:
        if not isinstance(r, dict) or _is_cash_row(r):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym and sym not in symbols:
            symbols.append(sym)
        if len(symbols) >= max_symbols:
            break
    if not symbols:
        return evidence

    try:
        try:
            from db_adapter import _execute as _db_exec
        except Exception:
            from scripts.db_adapter import _execute as _db_exec  # type: ignore

        def _db(sql: str, params=None, fetch: str = "all"):
            return _db_exec(sql, params, fetch=fetch)

        try:
            from lib.data_broker.catalyst_record import get_catalyst_record
            from lib.catalyst_domain import pack_from_broker_record, unavailable_pack
        except Exception:
            from scripts.lib.data_broker.catalyst_record import get_catalyst_record  # type: ignore
            from scripts.lib.catalyst_domain import pack_from_broker_record, unavailable_pack  # type: ignore
    except Exception:
        return evidence

    by_sym: dict[str, dict[str, Any]] = dict(evidence.get("catalyst_by_symbol") or {})
    for sym in symbols:
        if sym in by_sym:
            continue
        try:
            rec = get_catalyst_record(_db, sym)
            if isinstance(rec, dict) and rec:
                by_sym[sym] = pack_from_broker_record(rec, symbol=sym)
            else:
                by_sym[sym] = unavailable_pack(symbol=sym, gap_reason="no_catalyst_record")
        except Exception as e:
            by_sym[sym] = unavailable_pack(symbol=sym, gap_reason=type(e).__name__)

    evidence["catalyst_by_symbol"] = by_sym
    if "catalyst" not in evidence and symbols:
        evidence["catalyst"] = by_sym.get(symbols[0]) or unavailable_pack(symbol=symbols[0])
    return evidence


def build_evidence_from_broker() -> dict[str, Any]:
    """Pull live CIO Data Broker snapshot → detector evidence. Fail-soft empty."""
    try:
        try:
            from lib.data_broker.cio_portfolio import get_cio_snapshot
        except Exception:
            from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot  # type: ignore
        snap = get_cio_snapshot(max_age_s=0)
        evidence = build_evidence_from_snapshot(snap if isinstance(snap, dict) else {})
        return enrich_evidence_with_catalysts(evidence)
    except Exception:
        return {}


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
