"""CIO desk product depth v1 — re-entry book, sector posture, cash-stage, disposition bias.

READ_ONLY_ADVISORY. Composes reentry_decision_desk + fund lookthrough + thesis
thresholds. Does not invent market data or emit order/stop language.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Classification thresholds (single place to tune) ───────────────────────
SECTOR_SOFT_CAP_PCT = 25.0  # report-only; desk@v4 has no formal sector cap yet

DEFENSIVE_SECTORS = frozenset({
    "consumer defensive", "consumer staples", "utilities", "healthcare",
    "health care", "real estate", "communication services",  # partial
})
# Income / quality ETF asset classes treated defensive when profile supports it
DEFENSIVE_ASSET_HINTS = frozenset({
    "dividend", "income", "quality", "investment grade", "bond", "fixed income",
    "staples", "utility", "defensive",
})
OFFENSIVE_SECTORS = frozenset({
    "consumer cyclical", "consumer discretionary", "industrials", "technology",
    "energy", "basic materials", "materials", "communication services",
})
# Theme / high-beta sleeves (symbol-level overrides)
OFFENSIVE_SYMBOLS = frozenset({
    "ARKX", "XAR", "SPCX", "ARKK", "ARKW", "ARKF", "ARKG", "TSLA", "COIN", "MSTR",
})
DEFENSIVE_SYMBOLS = frozenset({
    "SCHD", "JEPI", "JEPQ", "DIVI", "BND", "AGG", "TLT", "IEF", "SHY", "VCSH",
    "XLU", "XLP", "VIG", "DGRO", "HDV",
})

ACTIONABLE_STATES = frozenset({"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW"})
WATCH_STATES = frozenset({"WAIT", "OVERBOUGHT WAIT"})
EXCLUDE_FROM_ACTIONABLE = frozenset({
    "CURRENTLY HELD", "WASH BLOCK", "STALE", "MISSING MARKET", "MISSING PLAN",
})

# Re-entry quality filter (v1.2.2) — presentation only; does not change READY/NEAR.
# Engine R:R (reentry_decision_desk): (target - price) / (price - stop); criterion prefers >= 2.0.
# See docs/cio/REENTRY_RR.md.
CORE_MIN_PRICE = 5.0          # $ — below this is micro/speculative by default
CORE_MIN_ADV = 1_000_000.0    # optional avg dollar volume threshold when present
CORE_MIN_RR = 1.5             # full core card requires R:R >= this (engine criterion uses 2.0)
MAX_SANE_RR = 12.0            # R:R above this is treated as data error (not displayed as N:1)


STATE_RANK = {
    "READY TO REVIEW": 0,
    "NEAR ENTRY": 1,
    "OVERSOLD REVIEW": 2,
    "WAIT": 3,
    "OVERBOUGHT WAIT": 4,
}


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("TRADEAI_PROJECT_ROOT") or os.environ.get("TRADEAI_ROOT") or "").strip()
    if env:
        roots.append(Path(env))
    roots.append(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"))
    try:
        roots.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    roots.append(Path.cwd())
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        k = str(rp)
        if k not in seen and (rp / "data").exists():
            seen.add(k)
            out.append(rp)
    return out


def load_fund_lookthrough() -> dict[str, Any]:
    for root in _project_roots():
        p = root / "data" / "portfolios" / "state" / "fund_lookthrough.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


# ── Cash stage ─────────────────────────────────────────────────────────────

def compute_cash_stage(
    *,
    cash_pct: Optional[float],
    total_cash: Optional[float],
    total_value: Optional[float],
    cash_band_min_pct: float = 20.0,
    quality: str = "OK",
    operator_stage_opt_in: bool = False,
    heat_pct: Optional[float] = None,
) -> dict[str, Any]:
    """STAGE_0 observe | STAGE_1 paper plan | STAGE_2 operator-authorized slice (advisory only)."""
    quality_u = (quality or "OK").upper()
    if cash_pct is None or total_cash is None or total_value is None:
        return {
            "stage": 0,
            "label": "STAGE_0",
            "name": "Observe only",
            "recommendation": "watch only; no stage",
            "reason": "cash_pct or total_cash/total_value DATA_UNAVAILABLE",
            "quality": quality_u or "PARTIAL",
        }
    if quality_u in ("PARTIAL", "DATA_UNAVAILABLE", "UNKNOWN", ""):
        return {
            "stage": 0,
            "label": "STAGE_0",
            "name": "Observe only",
            "recommendation": "watch only; no stage",
            "reason": f"data quality {quality_u or 'PARTIAL'} — re-entry may list candidates but recommendation = watch only",
            "quality": quality_u or "PARTIAL",
        }
    if float(cash_pct) <= float(cash_band_min_pct):
        return {
            "stage": 0,
            "label": "STAGE_0",
            "name": "Observe only",
            "recommendation": "watch only; cash at/below band — no force-deploy",
            "reason": f"cash_pct {_fmt(cash_pct)}% ≤ band {cash_band_min_pct}%",
            "quality": quality_u,
        }
    # STAGE_2 requires explicit opt-in + quality OK + heat not extreme
    heat_ok = heat_pct is None or float(heat_pct) < 5.0
    if operator_stage_opt_in and quality_u == "OK" and heat_ok:
        return {
            "stage": 2,
            "label": "STAGE_2",
            "name": "Operator-authorized stage slice (advisory description only)",
            "recommendation": (
                "if you authorize, first slice would be sized under 1% book risk / 10% cap; "
                "still READ_ONLY — no orders from desk"
            ),
            "reason": "quality OK + operator opt-in/disposition + heat comfortable",
            "quality": quality_u,
        }
    return {
        "stage": 1,
        "label": "STAGE_1",
        "name": "Paper plan only",
        "recommendation": "allow sized plan text; require operator ack; no execution language",
        "reason": (
            f"cash_pct {_fmt(cash_pct)}% > band {cash_band_min_pct}%, quality {quality_u}, "
            "no operator stage opt-in yet"
        ),
        "quality": quality_u,
    }


def _fmt(n: Optional[float], digits: int = 2) -> str:
    if n is None:
        return "n/a"
    return f"{float(n):.{digits}f}"


# ── Disposition helpers ────────────────────────────────────────────────────

def dedupe_learning(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by plan_id+disposition+day (preferred) else disposition+situation+symbols+note."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        day = str(r.get("ts") or "")[:10]
        pid = str(r.get("plan_id") or "")
        disp = str(r.get("disposition") or "").lower()
        if pid and disp and day:
            key = f"pid:{pid}|{disp}|{day}"
        else:
            key = "|".join(
                [
                    disp,
                    str(r.get("situation_type") or ""),
                    ",".join(str(s) for s in (r.get("symbols") or [])),
                    str(r.get("note") or "").strip().lower()[:120],
                    day,
                ]
            )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def dispositions_for_symbol(
    learning: list[dict[str, Any]],
    symbol: str,
    *,
    situation_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    sym = (symbol or "").upper()
    out = []
    for L in learning:
        syms = [str(s).upper() for s in (L.get("symbols") or [])]
        if sym and sym not in syms:
            continue
        if situation_type and str(L.get("situation_type") or "") != situation_type:
            # still include if symbol matches strongly
            if not sym:
                continue
        out.append(L)
    return out


def disposition_constraint_line(L: dict[str, Any]) -> str:
    disp = str(L.get("disposition") or "prior").lower()
    note = str(L.get("note") or "").strip()
    syms = ",".join(str(s) for s in (L.get("symbols") or [])[:4]) or "—"
    st = str(L.get("situation_type") or "")
    day = str(L.get("ts") or "")[:10]
    pin = str(L.get("thesis_version") or "")
    base = f"CONSTRAINT: Operator {disp} {st} {syms}"
    if day:
        base += f" on {day}"
    if note:
        base += f" — reason: {note}"
    if pin:
        base += f" (pin {pin})"
    base += ". Honor this bias in recommendation text; do not reverse without stronger fire or operator revisit."
    return base


def active_disposition_phrase(learning: list[dict[str, Any]], symbols: list[str]) -> Optional[str]:
    """First-sentence phrase for recs when a prior disposition matches symbols."""
    syms = {str(s).upper() for s in symbols if s}
    for L in learning:
        Lsyms = {str(s).upper() for s in (L.get("symbols") or [])}
        if not syms.intersection(Lsyms):
            continue
        disp = str(L.get("disposition") or "").lower()
        if not disp:
            continue
        note = str(L.get("note") or "").strip()
        day = str(L.get("ts") or "")[:10]
        if disp == "defer":
            return (
                f"Operator prior: defer"
                + (f" ({note})" if note else "")
                + (f" as of {day}" if day else "")
                + " — do not push trim/dispose as primary while defer is active."
            )
        if disp == "reject":
            return f"Operator prior: reject" + (f" ({note})" if note else "") + " — do not restate rejected action as primary."
        if disp == "ack":
            return f"Operator prior: ack" + (f" ({note})" if note else "") + " — continue monitor; no forced change."
        if disp == "done":
            return f"Operator prior: done" + (f" ({note})" if note else "") + " — treat as closed unless fire strengthens."
        return f"Operator prior: {disp}" + (f" ({note})" if note else "") + "."
    return None


def has_operator_stage_opt_in(learning: list[dict[str, Any]]) -> bool:
    """True if any disposition signals willingness to stage/deploy (ack on S5, etc.)."""
    for L in learning:
        disp = str(L.get("disposition") or "").lower()
        st = str(L.get("situation_type") or "")
        note = str(L.get("note") or "").lower()
        if disp in ("ack", "accept", "accepted") and "S5" in st:
            return True
        if "stage" in note or "deploy" in note or "opt-in" in note or "authorize" in note:
            if disp in ("ack", "accept", "accepted", "done"):
                return True
    return False


# ── Sector defensive posture ───────────────────────────────────────────────

def _classify_symbol(
    symbol: str,
    sector: str,
    *,
    lookthrough: Optional[dict[str, Any]] = None,
    asset_class: str = "",
) -> str:
    """Return DEFENSIVE | OFFENSIVE | UNCLASSIFIED."""
    sym = (symbol or "").upper()
    if sym in DEFENSIVE_SYMBOLS:
        return "DEFENSIVE"
    if sym in OFFENSIVE_SYMBOLS:
        return "OFFENSIVE"
    sec = (sector or "").strip().lower()
    ac = (asset_class or "").strip().lower()
    fund_name = ""
    if lookthrough:
        fund_name = str(lookthrough.get("fund_name") or lookthrough.get("notes") or "").lower()
        ac = ac or str(lookthrough.get("asset_class") or "").lower()
        # Use dominant lookthrough sector if ticker sector empty
        sw = lookthrough.get("sector_weights") or {}
        if isinstance(sw, dict) and sw and not sec:
            top_sec = max(sw.items(), key=lambda kv: float(kv[1] or 0))[0]
            sec = str(top_sec).lower()
    blob = f"{sec} {ac} {fund_name}"
    if any(h in blob for h in DEFENSIVE_ASSET_HINTS):
        return "DEFENSIVE"
    if sec in DEFENSIVE_SECTORS or any(s in sec for s in ("staple", "utilit", "healthcare", "health care", "real estate")):
        # Healthcare can be mixed; dividend ETFs already caught. Pure biotech single-names → offensive if deep theme
        if "biotech" in blob or "speculative" in blob:
            return "OFFENSIVE"
        return "DEFENSIVE"
    if sec in OFFENSIVE_SECTORS or any(
        s in sec for s in ("cyclical", "discretionary", "industrial", "technolog", "energy", "material")
    ):
        return "OFFENSIVE"
    if sym.endswith("X") and len(sym) <= 5:  # many sector/theme ETFs
        if sym.startswith("XL") and sym in ("XLU", "XLP"):
            return "DEFENSIVE"
        if sym in ("XLI", "XLY", "XLB", "XLE", "XLK", "XAR"):
            return "OFFENSIVE"
    return "UNCLASSIFIED"


def build_sector_posture(
    *,
    symbol_weights: dict[str, float],
    symbol_sectors: dict[str, str],
    pin: str = "desk@v4",
    cash_pct: Optional[float] = None,
    stance: str = "defensive_observe",
) -> dict[str, Any]:
    """Lookthrough-aware sector concentration + defensive vs offensive tilt."""
    lt_all = load_fund_lookthrough()
    sector_w: dict[str, float] = defaultdict(float)
    tilt = {"DEFENSIVE": 0.0, "OFFENSIVE": 0.0, "UNCLASSIFIED": 0.0}
    per_symbol: list[dict[str, Any]] = []
    quality_notes: list[str] = []
    missing_sector = 0

    for sym, w in symbol_weights.items():
        if w is None or float(w) <= 0:
            continue
        w = float(w)
        lt = lt_all.get(sym) or lt_all.get(sym.upper()) or {}
        if not isinstance(lt, dict):
            lt = {}
        sec = (symbol_sectors.get(sym) or "").strip()
        if not sec and lt.get("sector_weights"):
            # attribute weight across lookthrough sectors
            sw = lt.get("sector_weights") or {}
            if isinstance(sw, dict) and sw:
                total_sw = sum(float(v or 0) for v in sw.values()) or 100.0
                for sk, sv in sw.items():
                    share = float(sv or 0) / total_sw * w
                    sector_w[str(sk)] += share
                sec = max(sw.items(), key=lambda kv: float(kv[1] or 0))[0]
            else:
                missing_sector += 1
                sector_w["Unknown"] += w
        elif sec:
            sector_w[sec] += w
        else:
            missing_sector += 1
            sector_w["Unknown"] += w

        label = _classify_symbol(
            sym, sec,
            lookthrough=lt if lt else None,
            asset_class=str(lt.get("asset_class") or ""),
        )
        tilt[label] += w
        per_symbol.append({
            "symbol": sym,
            "weight_pct": round(w, 3),
            "sector": sec or "Unknown",
            "tilt": label,
            "lookthrough": bool(lt.get("sector_weights")),
        })

    total_tilt = sum(tilt.values()) or 1.0
    tilt_pct = {k: round(v / total_tilt * 100.0, 2) for k, v in tilt.items()}
    # Also as % of book if weights are book %
    book_sum = sum(float(w) for w in symbol_weights.values() if w) or 1.0
    tilt_book = {k: round(v, 2) for k, v in tilt.items()}

    sector_table = sorted(
        [{"sector": s, "weight_pct": round(w, 2)} for s, w in sector_w.items()],
        key=lambda x: -x["weight_pct"],
    )
    top3 = sector_table[:3]
    over_cap = [s for s in sector_table if s["weight_pct"] >= SECTOR_SOFT_CAP_PCT]

    # Correlated sleeves
    sleeves = {
        "industrial_aero": [s for s in ("XLI", "XAR", "ARKX", "SPCX", "XLB") if s in symbol_weights],
        "dividend_income": [s for s in ("SCHD", "JEPI", "DIVI", "JEPQ", "HDV", "VIG") if s in symbol_weights],
        "tech_growth": [s for s in symbol_weights if (symbol_sectors.get(s) or "").lower() in ("technology",)],
    }
    sleeve_weights = {
        name: round(sum(float(symbol_weights.get(s) or 0) for s in syms), 2)
        for name, syms in sleeves.items()
        if syms
    }

    if missing_sector:
        quality_notes.append(f"{missing_sector} names missing sector label (lookthrough used when available)")
    if not any(lt_all.get(s) for s in symbol_weights):
        quality_notes.append("fund_lookthrough sparse for this book — quality may be PARTIAL")

    quality = "OK" if missing_sector <= max(2, len(symbol_weights) // 4) else "PARTIAL"

    # Posture narrative pieces
    tensions = []
    if tilt_book.get("DEFENSIVE", 0) >= 10:
        tensions.append(
            f"Dividend/defensive sleeve ≈{tilt_book['DEFENSIVE']:.1f}% book is consistent with defensive_observe"
        )
    if tilt_book.get("OFFENSIVE", 0) >= 8:
        tensions.append(
            f"Offensive/cyclical ≈{tilt_book['OFFENSIVE']:.1f}% book is the risk-on sleeve — correlated if industrials/tech re-rate"
        )
    if cash_pct is not None:
        tensions.append(
            f"Cash {_fmt(cash_pct)}% is the primary defensive buffer under {stance}"
        )
    if over_cap:
        tensions.append(
            "Sector cluster(s) ≥ soft report cap "
            f"{SECTOR_SOFT_CAP_PCT}%: "
            + ", ".join(f"{x['sector']} {x['weight_pct']}%" for x in over_cap)
            + " (no formal sector cap in desk@v4 yet — flag only)"
        )
    else:
        tensions.append(f"No sector ≥ soft report cap {SECTOR_SOFT_CAP_PCT}% (desk@v4 has no formal sector cap yet)")

    improve = [
        "Prefer STAGE_1 paper plans in under-weight defensive/quality sleeves only when quality OK",
        "Avoid STAGE language that increases an already-hot offensive correlated sleeve without operator opt-in",
        "Use cash as buffer; do not force-deploy to 'fix' sector balance",
    ]

    return {
        "pin": pin,
        "quality": quality,
        "quality_notes": quality_notes,
        "tilt_book_pct": tilt_book,
        "tilt_share_pct": tilt_pct,
        "sector_table": sector_table,
        "top3": top3,
        "over_soft_cap": over_cap,
        "sector_soft_cap_pct": SECTOR_SOFT_CAP_PCT,
        "sector_cap_policy": "no formal sector cap in desk@v4 yet",
        "correlated_sleeves": sleeve_weights,
        "sleeve_members": sleeves,
        "per_symbol": sorted(per_symbol, key=lambda x: -x["weight_pct"])[:20],
        "tensions": tensions,
        "improve": improve,
        "as_of": _now(),
        "authority": "READ_ONLY_ADVISORY",
    }


# ── Re-entry book ──────────────────────────────────────────────────────────

def _db_query_factory():
    try:
        from db_adapter import _execute as _db_exec  # type: ignore

        def _db(sql: str, params=None, fetch: str = "all"):
            return _db_exec(sql, params, fetch=fetch)

        return _db
    except Exception:
        try:
            from scripts.db_adapter import _execute as _db_exec  # type: ignore

            def _db(sql: str, params=None, fetch: str = "all"):
                return _db_exec(sql, params, fetch=fetch)

            return _db
        except Exception:
            return None


def fetch_reentry_rows(*, max_symbols: int = 250) -> dict[str, Any]:
    """Call build_decision_desk; fail-soft to empty."""
    db = _db_query_factory()
    if db is None:
        return {"ok": False, "error": "db_unavailable", "rows": []}
    try:
        try:
            from lib.data_broker.reentry_decision_desk import build_decision_desk  # type: ignore
        except Exception:
            from scripts.lib.data_broker.reentry_decision_desk import build_decision_desk  # type: ignore
        return build_decision_desk(db, max_symbols=max_symbols)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}:{e}", "rows": []}


def _desk_fit_for_candidate(
    row: dict[str, Any],
    *,
    pin: str,
    stage: dict[str, Any],
    thr: dict[str, Any],
    cash_pct: Optional[float],
    symbol_weights: dict[str, float],
    sector_posture: Optional[dict[str, Any]] = None,
) -> str:
    sym = str(row.get("symbol") or "").upper()
    state = str((row.get("intel") or {}).get("state") or "")
    adv = row.get("advisory") or {}
    sizing = adv.get("sizing") or {}
    alloc = _f(sizing.get("allocation"))
    book = _f(sizing.get("book_equity"))
    max_name = float(thr.get("max_single_name_weight_pct") or 12)
    cash_band = float(thr.get("cash_band_min_pct") or 20)
    post_w = None
    if alloc is not None and book and book > 0:
        post_w = alloc / book * 100.0
    # existing weight if any
    cur_w = float(symbol_weights.get(sym) or 0)
    projected = (cur_w + (post_w or 0)) if post_w is not None else cur_w

    bits = [
        f"({pin}): state={state}.",
        f"Cash stage {stage.get('label')} — {stage.get('recommendation')}.",
    ]
    if cash_pct is not None:
        bits.append(
            f"Book cash {_fmt(cash_pct)}% vs band {cash_band}%: "
            f"{'elevated optionality supports paper plans only until operator opt-in' if cash_pct > cash_band else 'limited dry powder'}."
        )
    if post_w is not None:
        breach = projected >= max_name
        bits.append(
            f"Sized sketch ~{_fmt(post_w)}% book"
            f"{' would approach/breach max_single_name ' + str(max_name) + '%' if breach else ' stays under max_single_name ' + str(max_name) + '%'}."
        )
    # Sector tension
    if sector_posture:
        per = {p["symbol"]: p for p in (sector_posture.get("per_symbol") or [])}
        # candidate not held — classify via company/sector from row
        company = str(row.get("company") or "")
        tilt = "UNCLASSIFIED"
        for part in company.split("·"):
            t = _classify_symbol(sym, part.strip())
            if t != "UNCLASSIFIED":
                tilt = t
                break
        if tilt == "OFFENSIVE" and float((sector_posture.get("tilt_book_pct") or {}).get("OFFENSIVE") or 0) >= 8:
            bits.append(
                "Tension: adding would increase offensive/cyclical exposure while book already has a non-trivial risk-on sleeve."
            )
        elif tilt == "DEFENSIVE":
            bits.append("Fit: candidate tilts defensive/quality — better alignment with defensive_observe if stage advances.")
        else:
            bits.append("Fit: constructive setup possible, but defensive_observe still requires stage gates + operator opt-in.")
    else:
        bits.append(
            "Constructive setup may exist, but under defensive_observe stage only after quality totals + operator opt-in — never buy-now language."
        )
    if not adv.get("confirmations_complete", True):
        gaps = ", ".join(str(g) for g in (adv.get("confirmation_gaps") or [])[:4]) or "gaps"
        bits.append(f"Confirmations incomplete ({gaps}) — not STAGE_2 eligible.")
    return " ".join(bits)



def sanitize_rr(rr: Any) -> tuple[Optional[float], Optional[str]]:
    """Return (display_rr, error_flag).

    - missing → (None, "rr_missing")
    - non-finite / <=0 → (None, "rr_invalid")
    - > MAX_SANE_RR → (None, "rr_absurd")  # data error, excluded
    - else → (rounded, None)
    """
    v = _f(rr)
    if v is None:
        return None, "rr_missing"
    if v != v:  # NaN
        return None, "rr_invalid"
    if v <= 0:
        return None, "rr_invalid"
    if v > MAX_SANE_RR:
        return None, f"rr_absurd_{v:.1f}"
    return round(v, 2), None


def classify_core_rr(rr: Any) -> str:
    """Classify R:R for core-liquidity names: full | sub | dropped."""
    rr_disp, rr_err = sanitize_rr(rr)
    if rr_err and str(rr_err).startswith("rr_absurd"):
        return "dropped_bad_rr"
    if rr_disp is None:
        return "dropped_bad_rr"  # missing / invalid / non-positive
    if rr_disp >= CORE_MIN_RR:
        return "full"
    # 0 < R:R < CORE_MIN_RR
    return "sub_rr"


def _adv_from_row(row: dict[str, Any]) -> Optional[float]:
    """Best-effort average dollar volume if broker/advisory attached it."""
    for key in ("adv", "avg_dollar_volume", "dollar_volume", "avg_volume_usd"):
        v = _f(row.get(key))
        if v is not None:
            return v
    adv = row.get("advisory") or {}
    if isinstance(adv, dict):
        for key in ("adv", "avg_dollar_volume", "dollar_volume"):
            v = _f(adv.get(key))
            if v is not None:
                return v
        sizing = adv.get("sizing") or {}
        if isinstance(sizing, dict):
            v = _f(sizing.get("adv") or sizing.get("avg_dollar_volume"))
            if v is not None:
                return v
    return None


def is_core_relevant(row: dict[str, Any]) -> bool:
    """Core-relevant re-entry: price≥$5 (or ADV ok), not wash-blocked, confirmations evaluated."""
    price = _f(row.get("price"))
    if row.get("wash_blocked"):
        return False
    adv = row.get("advisory") or {}
    # Confirmations must have been evaluated (complete OR non-empty gap list OR criteria present)
    conf_ok = bool(adv.get("confirmations_complete"))
    gaps = adv.get("confirmation_gaps")
    criteria = adv.get("criteria")
    conf_evaluated = (
        conf_ok
        or (isinstance(gaps, list) and len(gaps) > 0)
        or (isinstance(criteria, list) and len(criteria) > 0)
        or gaps is not None
    )
    if not conf_evaluated:
        return False
    adv_usd = _adv_from_row(row)
    if price is not None and price >= CORE_MIN_PRICE:
        return True
    if adv_usd is not None and adv_usd >= CORE_MIN_ADV and price is not None and price >= 1.0:
        # Liquid name under $5 still can be core if ADV is institutional
        return True
    return False


def _row_to_card(
    r: dict[str, Any],
    *,
    pin: str,
    stage_n: int,
    cash_stage: dict[str, Any],
    thr: dict[str, Any],
    cash_pct: Optional[float],
    symbol_weights: dict[str, float],
    sector_posture: Optional[dict[str, Any]],
    heat_pct: Optional[float],
    tier: str,
) -> dict[str, Any]:
    intel = r.get("intel") or {}
    adv = r.get("advisory") or {}
    sizing = adv.get("sizing") or {}
    state = str(intel.get("state") or "")
    conf_ok = bool(adv.get("confirmations_complete"))
    if stage_n == 0:
        gate = "STAGE_0 watch only; no stage"
    elif stage_n == 1:
        gate = "STAGE_1 paper plan only — sized sketch OK; operator ack required; no execution"
    else:
        alloc = _f(sizing.get("allocation"))
        book = _f(sizing.get("book_equity"))
        post_w = (alloc / book * 100.0) if alloc and book else None
        max_name = float(thr.get("max_single_name_weight_pct") or 12)
        heat_ok = heat_pct is None or float(heat_pct) < 5.0
        if (
            state == "READY TO REVIEW"
            and conf_ok
            and (post_w is None or post_w < max_name)
            and heat_ok
        ):
            gate = (
                "STAGE_2 advisory first-slice eligible — "
                f"if you authorize, first slice ≈ {sizing.get('shares')} sh / "
                f"${_fmt(alloc, 0) if alloc else 'n/a'} "
                f"({sizing.get('note') or '1% risk / 10% cap'}); still READ_ONLY"
            )
        else:
            gate = (
                "STAGE_2 not met — treat as STAGE_1 paper plan "
                "(need READY + confirmations + size under max_name + heat OK)"
            )

    zone = None
    if r.get("entry_low") is not None and r.get("entry_high") is not None:
        zone = f"${_fmt(r.get('entry_low'))}–${_fmt(r.get('entry_high'))}"
    rr_disp, rr_err = sanitize_rr(r.get("rr"))
    return {
        "symbol": r.get("symbol"),
        "state": state,
        "action": intel.get("action") or adv.get("action"),
        "price": r.get("price"),
        "entry_zone": zone,
        "entry_low": r.get("entry_low"),
        "entry_high": r.get("entry_high"),
        "stop": r.get("stop"),
        "target": r.get("target"),
        "rr": rr_disp,
        "rr_raw": _f(r.get("rr")),
        "rr_error": rr_err,
        "rsi": r.get("rsi"),
        "rsi_band": "40≤RSI<70",
        "distance_pct": intel.get("distance_pct"),
        "sizing": {
            "shares": sizing.get("shares"),
            "allocation": sizing.get("allocation"),
            "note": sizing.get("note"),
            "risk_pct": sizing.get("risk_pct"),
            "max_alloc_pct": sizing.get("max_alloc_pct"),
        },
        "wash_blocked": r.get("wash_blocked"),
        "wash_until": r.get("wash_until"),
        "earnings_date": r.get("earnings_date"),
        "confirmation_gaps": adv.get("confirmation_gaps") or [],
        "confirmations_complete": conf_ok,
        "why": list(r.get("why") or [])[:4],
        "desk_fit": _desk_fit_for_candidate(
            r,
            pin=pin,
            stage=cash_stage,
            thr=thr,
            cash_pct=cash_pct,
            symbol_weights=symbol_weights,
            sector_posture=sector_posture,
        ),
        "stage_gate": gate,
        "tier": tier,
        "thesis_version": pin,
        "authority": "READ_ONLY_ADVISORY",
    }


def build_reentry_book(
    *,
    pin: str,
    thr: dict[str, Any],
    cash_stage: dict[str, Any],
    cash_pct: Optional[float],
    symbol_weights: dict[str, float],
    sector_posture: Optional[dict[str, Any]] = None,
    heat_pct: Optional[float] = None,
    max_display: int = 10,
) -> dict[str, Any]:
    """Build desk-governed re-entry book with core R:R≥1.5 / sub / micro split (v1.2.2)."""
    raw = fetch_reentry_rows()
    rows = raw.get("rows") or []
    actionable: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []

    for r in rows:
        if not isinstance(r, dict):
            continue
        state = str((r.get("intel") or {}).get("state") or "")
        if state in EXCLUDE_FROM_ACTIONABLE or state == "CURRENTLY HELD":
            continue
        if state in ACTIONABLE_STATES:
            actionable.append(r)
        elif state in WATCH_STATES and (
            r.get("entry_low") is not None or r.get("entry_high") is not None
        ):
            watch.append(r)

    def _sort_key(r: dict[str, Any]) -> tuple:
        state = str((r.get("intel") or {}).get("state") or "")
        rr_disp, _err = sanitize_rr(r.get("rr"))
        dist = _f((r.get("intel") or {}).get("distance_pct"))
        # Prefer sane R:R; absurd R:R sorts last among peers
        rr_key = -(rr_disp if rr_disp is not None else -1)
        return (
            STATE_RANK.get(state, 50),
            rr_key,
            abs(dist) if dist is not None else 999,
            str(r.get("symbol") or ""),
        )

    actionable.sort(key=_sort_key)
    watch.sort(key=_sort_key)

    # Liquidity/price core vs micro first
    core_liq_rows: list[dict[str, Any]] = []
    micro_rows: list[dict[str, Any]] = []
    for r in actionable:
        if is_core_relevant(r):
            core_liq_rows.append(r)
        else:
            micro_rows.append(r)

    # Split core-liquidity by R:R quality (presentation layer only)
    core_full_rows: list[dict[str, Any]] = []
    sub_rr_rows: list[dict[str, Any]] = []
    dropped_bad_rr_rows: list[dict[str, Any]] = []
    for r in core_liq_rows:
        cls = classify_core_rr(r.get("rr"))
        if cls == "full":
            core_full_rows.append(r)
        elif cls == "sub_rr":
            sub_rr_rows.append(r)
        else:
            dropped_bad_rr_rows.append(r)

    stage_n = int(cash_stage.get("stage") or 0)
    card_kw = dict(
        pin=pin,
        stage_n=stage_n,
        cash_stage=cash_stage,
        thr=thr,
        cash_pct=cash_pct,
        symbol_weights=symbol_weights,
        sector_posture=sector_posture,
        heat_pct=heat_pct,
    )

    # Full cards only for R:R >= CORE_MIN_RR
    core_cards = [
        _row_to_card(r, tier="core", **card_kw) for r in core_full_rows[:max_display]
    ]

    # Sub-quality NEAR: collapse (no full cards)
    sub_rr_parts = []
    for r in sub_rr_rows[:20]:
        rr_disp, _ = sanitize_rr(r.get("rr"))
        sym = r.get("symbol")
        sub_rr_parts.append(f"{sym} {rr_disp}" if rr_disp is not None else f"{sym} ?")
    sub_rr_line = None
    if sub_rr_rows:
        stage_label = cash_stage.get("label") or f"STAGE_{stage_n}"
        sub_rr_line = (
            f"Near but R:R < {CORE_MIN_RR:g} ({len(sub_rr_rows)}): "
            + ", ".join(sub_rr_parts[:16])
            + f" — watch only under {stage_label}."
        )

    # Micro: expand only READY + confirmations_complete; rest collapsed
    micro_expanded: list[dict[str, Any]] = []
    micro_collapsed: list[dict[str, Any]] = []
    for r in micro_rows:
        adv = r.get("advisory") or {}
        state = str((r.get("intel") or {}).get("state") or "")
        if state == "READY TO REVIEW" and bool(adv.get("confirmations_complete")):
            micro_expanded.append(_row_to_card(r, tier="micro_ready", **card_kw))
        else:
            micro_collapsed.append(r)

    # Primary cards list = core full only (+ optional micro READY)
    cards = list(core_cards)
    for c in micro_expanded[:3]:
        cards.append(c)

    micro_summary_parts = []
    for r in micro_collapsed[:24]:
        sym = r.get("symbol")
        st = str((r.get("intel") or {}).get("state") or "")
        px = _f(r.get("price"))
        px_s = f"${px:.2f}" if px is not None else "?"
        micro_summary_parts.append(f"{sym}({st}@{px_s})")
    micro_line = None
    if micro_collapsed or micro_expanded:
        n_micro = len(micro_rows)
        n_ready = len(micro_expanded)
        micro_line = (
            f"Micro / speculative watch ({n_micro} names, price < ${CORE_MIN_PRICE:.0f} "
            f"or wash/confirmations thin): "
            + (", ".join(micro_summary_parts[:18]) if micro_summary_parts else "—")
            + (f" · +{n_ready} READY+confirmed expanded above" if n_ready else "")
            + ". Not core-relevant under desk quality filter."
        )

    # Stage-eligible core: READY/NEAR with confirmations complete + full R:R
    stage_eligible_core = []
    for r in core_full_rows:
        adv = r.get("advisory") or {}
        state = str((r.get("intel") or {}).get("state") or "")
        if state in ("READY TO REVIEW", "NEAR ENTRY") and bool(adv.get("confirmations_complete")):
            stage_eligible_core.append(r)
    has_stage_eligible_core = len(stage_eligible_core) > 0

    watch_cards = []
    for r in watch[:4]:
        intel = r.get("intel") or {}
        rr_disp, rr_err = sanitize_rr(r.get("rr"))
        watch_cards.append({
            "symbol": r.get("symbol"),
            "state": intel.get("state"),
            "price": r.get("price"),
            "entry_low": r.get("entry_low"),
            "entry_high": r.get("entry_high"),
            "rr": rr_disp,
            "rr_error": rr_err,
            "note": "watch only — not in actionable book",
        })

    return {
        "ok": bool(raw.get("ok", True)) and not raw.get("error"),
        "error": raw.get("error"),
        "source": "data_broker.reentry_decision_desk.build_decision_desk",
        "pin": pin,
        "stage": cash_stage,
        "actionable_count": len(actionable),
        # v1.2.2 counts
        "core_full": len(core_full_rows),
        "sub_rr": len(sub_rr_rows),
        "micro_count": len(micro_rows),
        "dropped_bad_rr": len(dropped_bad_rr_rows),
        # back-compat aliases
        "core_count": len(core_full_rows),
        "core_display": len(core_cards),
        "core_liq_count": len(core_liq_rows),
        "micro_expanded_count": len(micro_expanded),
        "micro_collapsed_count": len(micro_collapsed),
        "has_stage_eligible_core": has_stage_eligible_core,
        "cards": cards,
        "core_cards": core_cards,
        "micro_expanded": micro_expanded,
        "micro_line": micro_line,
        "sub_rr_line": sub_rr_line,
        "sub_rr_symbols": [
            {
                "symbol": r.get("symbol"),
                "rr": sanitize_rr(r.get("rr"))[0],
                "state": (r.get("intel") or {}).get("state"),
            }
            for r in sub_rr_rows[:20]
        ],
        "watch": watch_cards,
        "freshness": raw.get("freshness") or {},
        "criteria": {
            **(raw.get("criteria") or {}),
            "core_min_price": CORE_MIN_PRICE,
            "core_min_adv": CORE_MIN_ADV,
            "core_min_rr": CORE_MIN_RR,
            "max_sane_rr": MAX_SANE_RR,
        },
        "footer": (
            "Candidates from Data Broker reentry_decision_desk; READY is deterministic; "
            f"{pin} governs stage. Core full card: px≥${CORE_MIN_PRICE:.0f} (or ADV≥${CORE_MIN_ADV/1e6:.0f}M), "
            f"not wash-blocked, confirmations evaluated, {CORE_MIN_RR:g}≤R:R≤{MAX_SANE_RR:.0f}. "
            f"0<R:R<{CORE_MIN_RR:g} collapsed as sub-quality; R:R missing/>{MAX_SANE_RR:.0f} dropped. "
            "READ_ONLY_ADVISORY — never buy-now / no orders."
        ),
        "as_of": raw.get("computed_at") or _now(),
        "authority": "READ_ONLY_ADVISORY",
    }
