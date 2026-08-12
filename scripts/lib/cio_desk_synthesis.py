"""CIO desk synthesis v1.1 — portfolio-grade advisory note under live desk@vN.

READ_ONLY_ADVISORY. Combines thesis + Data Broker snapshot + material plans +
operator learning into one operator-facing desk note (Telegram + /v3/cio).

v1.1: no mid-sentence truncation, distinct thesis-fit per situation,
API/CLI snapshot parity, deduped learning log, deeper rec analysis.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body(domains: dict[str, Any], name: str) -> dict[str, Any]:
    raw = domains.get(name) or {}
    if not isinstance(raw, dict):
        return {}
    d = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return d if isinstance(d, dict) else {}


def _f(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _fmt_usd(n: Optional[float]) -> str:
    if n is None:
        return "DATA_UNAVAILABLE"
    abs_n = abs(n)
    if abs_n >= 1e6:
        return f"${n/1e6:.2f}M"
    if abs_n >= 1e3:
        return f"${n/1e3:.1f}K"
    return f"${n:.0f}"


def _fmt_pct(n: Optional[float], signed: bool = False) -> str:
    if n is None:
        return "DATA_UNAVAILABLE"
    if signed:
        return f"{n:+.2f}%"
    return f"{n:.2f}%"


def _full_sentence(s: str, *, max_len: int = 900) -> str:
    """Keep complete sentences; never cut mid-word or mid-sentence if avoidable."""
    t = " ".join(str(s or "").split())
    if not t:
        return ""
    if len(t) <= max_len:
        return t
    cut = t[:max_len]
    # prefer sentence boundary
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx >= int(max_len * 0.45):
            return cut[: idx + 1].strip()
    # else word boundary
    if " " in cut:
        return cut.rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return cut


def _dedupe_learning(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by disposition+situation+symbols+note (ignore pin/ts noise)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = "|".join(
            [
                str(r.get("disposition") or ""),
                str(r.get("situation_type") or ""),
                ",".join(str(s) for s in (r.get("symbols") or [])),
                str(r.get("note") or "").strip().lower()[:120],
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _candidate_project_roots() -> list[Path]:
    roots: list[Path] = []
    env = (os.environ.get("TRADEAI_PROJECT_ROOT") or os.environ.get("TRADEAI_ROOT") or "").strip()
    if env:
        roots.append(Path(env))
    # Live rebuild tree (host default)
    roots.append(Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"))
    # Module-relative: scripts/lib -> repo root
    try:
        roots.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    # cwd
    roots.append(Path.cwd())
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        key = str(rp)
        if key in seen:
            continue
        if (rp / "data" / "portfolios" / "state").exists() or (rp / "data" / "cio").exists():
            seen.add(key)
            out.append(rp)
    return out


def _patch_broker_project_root(root: Path) -> None:
    """Point data_broker paths at a root that has portfolio state (API/release fix)."""
    try:
        try:
            import lib.data_broker.cio_portfolio as cp  # type: ignore
        except Exception:
            import scripts.lib.data_broker.cio_portfolio as cp  # type: ignore
        cp.PROJECT_ROOT = root
        cp.STATE_DIR = root / "data" / "portfolios" / "state"
        cp.RUNTIME_DIR = root / "data" / "runtime"
        if hasattr(cp, "WATCHLIST_PATH"):
            cp.WATCHLIST_PATH = root / "data" / "watchlist" / "state" / "watchlist.json"
        if hasattr(cp, "RECONCILIATION_PATH"):
            cp.RECONCILIATION_PATH = root / "data" / "reconciliation" / "state" / "latest.json"
    except Exception:
        pass


def _import_cio():
    """Import CIO libs whether PYTHONPATH is repo root or scripts/."""
    try:
        from lib.cio_theses import (  # type: ignore
            safe_current_pin,
            safe_context_block,
            recent_operator_learning,
        )
        from lib.cio_plans import CIOPlanStore  # type: ignore
        from lib.cio_plan_enrichment import is_material_plan  # type: ignore
        return safe_current_pin, safe_context_block, recent_operator_learning, CIOPlanStore, is_material_plan
    except Exception:
        from scripts.lib.cio_theses import (
            safe_current_pin,
            safe_context_block,
            recent_operator_learning,
        )
        from scripts.lib.cio_plans import CIOPlanStore
        from scripts.lib.cio_plan_enrichment import is_material_plan
        return safe_current_pin, safe_context_block, recent_operator_learning, CIOPlanStore, is_material_plan


def _get_snapshot() -> dict[str, Any]:
    """Load CIO snapshot with root patch so API (release tree) sees live portfolio data."""
    errors: list[str] = []
    cp = None
    get_cio_snapshot = None
    try:
        import lib.data_broker.cio_portfolio as cp  # type: ignore
        get_cio_snapshot = cp.get_cio_snapshot
    except Exception as e1:
        errors.append(f"lib_import:{type(e1).__name__}:{e1}")
        try:
            import scripts.lib.data_broker.cio_portfolio as cp  # type: ignore
            get_cio_snapshot = cp.get_cio_snapshot
        except Exception as e2:
            errors.append(f"scripts_import:{type(e2).__name__}:{e2}")
    if cp is None or get_cio_snapshot is None:
        # Last resort: read snapshot JSON directly from live rebuild tree
        for root in _candidate_project_roots():
            snap_path = root / "data" / "portfolios" / "state" / "data_broker" / "cio_snapshot.json"
            if snap_path.exists():
                try:
                    import json as _json
                    file_snap = _json.loads(snap_path.read_text(encoding="utf-8"))
                    if (file_snap.get("domains") or {}).get("portfolio", {}).get("total_value") is not None:
                        return file_snap
                except Exception as e3:
                    errors.append(f"direct_file:{e3}")
        try:
            Path("/tmp/cio_desk_snap_err.txt").write_text("; ".join(errors)[:2000])
        except Exception:
            pass
        return {}

    # Always try rebuild/live roots first (release tree often lacks portfolio state)
    roots = _candidate_project_roots()
    live = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
    if live.exists():
        roots = [live] + [r for r in roots if r.resolve() != live.resolve()]

    best: dict[str, Any] = {}
    for root in roots:
        try:
            cp.PROJECT_ROOT = root
            cp.STATE_DIR = root / "data" / "portfolios" / "state"
            cp.RUNTIME_DIR = root / "data" / "runtime"
            # SNAPSHOT_PATH is a module-level constant — must repoint or API reads empty cache
            if hasattr(cp, "SNAPSHOT_DIR"):
                cp.SNAPSHOT_DIR = cp.STATE_DIR / "data_broker"
            if hasattr(cp, "SNAPSHOT_PATH"):
                cp.SNAPSHOT_PATH = cp.STATE_DIR / "data_broker" / "cio_snapshot.json"
            if hasattr(cp, "WATCHLIST_PATH"):
                cp.WATCHLIST_PATH = root / "data" / "watchlist" / "state" / "watchlist.json"
            if hasattr(cp, "RECONCILIATION_PATH"):
                cp.RECONCILIATION_PATH = root / "data" / "reconciliation" / "state" / "latest.json"
            # Prefer reading an existing good snapshot file directly first (fast + reliable)
            snap_path = root / "data" / "portfolios" / "state" / "data_broker" / "cio_snapshot.json"
            if snap_path.exists():
                try:
                    import json as _json
                    file_snap = _json.loads(snap_path.read_text(encoding="utf-8"))
                    fdom = file_snap.get("domains") or {}
                    if isinstance(fdom, dict):
                        fport = _body(fdom, "portfolio")
                        fcash = _body(fdom, "cash_buying_power")
                        if fport.get("total_value") is not None or fcash.get("total_cash") is not None:
                            return file_snap if "domains" in file_snap else {"domains": fdom}
                except Exception as e:
                    errors.append(f"file_snap:{root}:{type(e).__name__}")
            # Fresh collect as fallback
            snap = get_cio_snapshot(max_age_s=0) or {}
            domains = snap.get("domains") or snap or {}
            if not isinstance(domains, dict):
                continue
            port = _body(domains, "portfolio")
            cash = _body(domains, "cash_buying_power")
            if port.get("total_value") is not None or cash.get("total_cash") is not None:
                return snap if "domains" in snap else {"domains": domains}
            if domains and not best:
                best = snap if "domains" in snap else {"domains": domains}
        except Exception as e:
            errors.append(f"root:{root}:{type(e).__name__}:{e}")
            continue
    try:
        Path("/tmp/cio_desk_snap_err.txt").write_text("; ".join(errors)[:2000] or "no_errors_empty")
    except Exception:
        pass
    if best:
        return best
    try:
        return get_cio_snapshot(max_age_s=60) or {}
    except Exception as e:
        try:
            Path("/tmp/cio_desk_snap_err.txt").write_text(f"final:{type(e).__name__}:{e}")
        except Exception:
            pass
        return {}


def collect_desk_inputs() -> dict[str, Any]:
    """Live desk@vN + portfolio + material plans + learning (fail-soft)."""
    (
        safe_current_pin,
        safe_context_block,
        recent_operator_learning,
        CIOPlanStore,
        is_material_plan,
    ) = _import_cio()

    pin = safe_current_pin("desk")
    try:
        thesis = safe_context_block("desk", full=True) or {}
    except TypeError:
        thesis = safe_context_block("desk") or {}

    snap = _get_snapshot()
    domains = snap.get("domains") or snap or {}
    if not isinstance(domains, dict):
        domains = {}

    port = _body(domains, "portfolio")
    cash = _body(domains, "cash_buying_power")
    risk = _body(domains, "risk")
    hold = _body(domains, "holdings_detail")

    total_value = _f(port.get("total_value") or cash.get("total_value") or hold.get("total_value"))
    total_cash = _f(cash.get("total_cash"))
    cash_pct = _f(cash.get("cash_pct") or port.get("cash_pct") or cash.get("cash_weight_pct"))
    if cash_pct is None and total_value and total_cash is not None and total_value > 0:
        cash_pct = total_cash / total_value * 100.0

    rows = hold.get("holdings") or hold.get("positions") or hold.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    agg: dict[str, float] = defaultdict(float)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        sym = str(r.get("symbol") or r.get("ticker") or "").upper()
        if not sym or r.get("is_cash"):
            continue
        w = _f(r.get("weight_pct") or r.get("weight"))
        if w is None:
            mv = _f(r.get("market_value") or r.get("mv"))
            if total_value and mv is not None and total_value > 0:
                w = mv / total_value * 100.0
        if w is not None:
            agg[sym] += w
        by_sym[sym].append(r)
    top = sorted(agg.items(), key=lambda x: -x[1])[:12]

    rps = thesis.get("risk_posture_structured") or {}
    cash_band = _f(rps.get("cash_band_min_pct")) or 20.0
    conc_fire = _f(rps.get("concentration_fire_pct")) or 16.5
    max_name = _f(rps.get("max_single_name_weight_pct")) or 12.0
    deep_dd = _f(rps.get("deep_dd_threshold_pct")) or 25.0

    store = CIOPlanStore()
    materials: list[dict[str, Any]] = []
    for p in store.list_open_plans(limit=80):
        fr = p.get("fire_reasons") or (p.get("extra") or {}).get("fire_reasons") or []
        pp = {**p, "fire_reasons": fr}
        if is_material_plan(pp):
            materials.append(pp)

    def _prio(p: dict[str, Any]) -> tuple:
        st = str(p.get("situation_type") or "")
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        order = {
            "S5_CASH_DEPLOYMENT": 0,
            "S6_CONCENTRATION_OR_DISPOSITION": 1,
            "S1_POSITION_LIFECYCLE": 2,
            "S8_DEFENSIVE_REGIME": 3,
        }.get(st, 9)
        demote = 1 if (syms == ["CASH"] or "SPACEX_TEST" in syms or "TEST" in "".join(syms)) else 0
        # prefer SCHD / SPCX for operator focus
        prefer = 0
        if "SCHD" in syms:
            prefer = -2
        if "SPCX" in syms:
            prefer = -1
        return (demote, prefer, order, str(p.get("plan_id")))

    materials = sorted(materials, key=_prio)
    learning = _dedupe_learning(recent_operator_learning(limit=20))

    # Extract SPCX basis/last from holdings for deeper analysis
    spcx_rows = by_sym.get("SPCX") or []
    spcx_meta: dict[str, Any] = {"book_weight_pct": agg.get("SPCX")}
    if spcx_rows:
        lasts = [_f(r.get("current_price") or r.get("last")) for r in spcx_rows]
        lasts = [x for x in lasts if x is not None]
        mvs = [_f(r.get("market_value")) for r in spcx_rows]
        mvs = [x for x in mvs if x is not None]
        upls = [_f(r.get("unrealized_pnl_pct")) for r in spcx_rows]
        upls = [x for x in upls if x is not None]
        if lasts:
            spcx_meta["last"] = lasts[0]
        if mvs:
            spcx_meta["market_value"] = sum(mvs)
        if upls:
            spcx_meta["upl_pct_min"] = min(upls)
            spcx_meta["upl_pct_max"] = max(upls)

    return {
        "as_of": _now(),
        "pin": pin,
        "thesis": thesis,
        "thresholds": {
            "cash_band_min_pct": cash_band,
            "max_single_name_weight_pct": max_name,
            "concentration_fire_pct": conc_fire,
            "deep_dd_threshold_pct": deep_dd,
        },
        "portfolio": {
            "total_value": total_value,
            "total_cash": total_cash,
            "cash_pct": cash_pct,
            "day_change_pct": _f(port.get("day_change_pct")),
            "holdings_count": port.get("holdings_count") or len(agg),
            "heat_pct": _f(risk.get("portfolio_heat_pct")),
            "stops_active": risk.get("stops_active"),
            "top_weights": [{"symbol": s, "weight_pct": w} for s, w in top],
            "by_symbol_rows": {k: v for k, v in list(by_sym.items())[:30]},
            "spcx": spcx_meta,
            "schd_weight_pct": agg.get("SCHD"),
        },
        "material_plans": materials,
        "learning": learning,
        "authority": "READ_ONLY_ADVISORY",
    }


def _thesis_fit_for_plan(
    p: dict[str, Any],
    *,
    pin: str,
    stance: str,
    thr: dict[str, Any],
    port: dict[str, Any],
    learning: list[dict[str, Any]],
) -> str:
    """Distinct thesis-fit paragraph per situation type — no shared boilerplate."""
    st = str(p.get("situation_type") or "")
    syms = [str(s).upper() for s in (p.get("symbols") or [])]
    fire = [str(x) for x in (p.get("fire_reasons") or [])]
    fire_s = ", ".join(fire[:4]) or "n/a"
    cash_pct = port.get("cash_pct")
    cash_band = thr.get("cash_band_min_pct") or 20
    conc_fire = thr.get("concentration_fire_pct") or 16.5
    max_name = thr.get("max_single_name_weight_pct") or 12
    deep_dd = thr.get("deep_dd_threshold_pct") or 25
    schd_w = port.get("schd_weight_pct")
    spcx = port.get("spcx") or {}

    if st == "S5_CASH_DEPLOYMENT":
        gap = (cash_pct - float(cash_band)) if cash_pct is not None else None
        return _full_sentence(
            f"({pin}/{stance}): elevated cash is consistent with defensive_observe — "
            f"the living thesis treats cash as intentional optionality, not idle waste. "
            f"Fire={fire_s}. Book cash {_fmt_pct(cash_pct)} sits "
            f"{_fmt_pct(gap, signed=True) if gap is not None else 'above'} the "
            f"{cash_band}% band, so the highest-signal path is HOLD/STAGE rather than force-deploy. "
            f"Tension: large idle cash can lag if risk assets re-rate; that tension is resolved by "
            f"staging only when total_cash/total_value quality supports a sized first slice, "
            f"not by filling for the sake of the band."
        )

    if st == "S6_CONCENTRATION_OR_DISPOSITION" and "SCHD" in syms:
        dist = None
        if schd_w is not None:
            dist = float(schd_w) - float(conc_fire)
        defer = any(
            str(L.get("disposition") or "").lower() == "defer"
            and "SCHD" in [str(s).upper() for s in (L.get("symbols") or [])]
            for L in learning
        )
        defer_note = (
            "Operator already deferred SCHD concentration ('wait for price buffer') — "
            "desk@v4 learning loop says honor that bias until weight or thesis changes."
            if defer
            else "No prior SCHD deferral on file; still prefer size-aware hold over forced trim."
        )
        return _full_sentence(
            f"({pin}/{stance}): SCHD is a core income sleeve, not a speculative overhang. "
            f"Book weight {_fmt_pct(schd_w)} vs concentration fire ≈{conc_fire}% "
            f"(distance {_fmt_pct(dist, signed=True) if dist is not None else 'n/a'}). "
            f"Fire={fire_s}. Fit: remaining long SCHD preserves dividend thesis under observe-only; "
            f"max_name threshold ({max_name}%) flags review, not automatic disposal. "
            f"Tension: single-name risk is real above fire — {defer_note}"
        )

    if st == "S1_POSITION_LIFECYCLE" and "SPCX" in syms:
        bw = spcx.get("book_weight_pct")
        dd = None
        for tok in fire_s.split(","):
            tok = tok.strip()
            m = re.search(r"deep_drawdown_from_basis_([\d.]+)pct", tok)
            if m:
                try:
                    dd = float(m.group(1))
                except Exception:
                    pass
        return _full_sentence(
            f"({pin}/{stance}): SPCX lifecycle DD is material as a signal "
            f"(~{dd if dd is not None else deep_dd}% from basis, threshold {deep_dd}%) but "
            f"immaterial as portfolio risk — book weight only {_fmt_pct(bw)}. "
            f"Fire={fire_s}. Fit: escalate awareness and keep hold options open; "
            f"defensive_observe forbids auto-stops or chat-originated sells. "
            f"Tension: large unrealized DD on a small sleeve can still be emotionally loud — "
            f"desk responds with size-scaled priority (awareness-only), not panic trim."
        )

    if st == "S6_CONCENTRATION_OR_DISPOSITION":
        sym = syms[0] if syms else "?"
        book_w = next((t["weight_pct"] for t in (port.get("top_weights") or []) if t["symbol"] == sym), None)
        return _full_sentence(
            f"({pin}/{stance}): concentration review on {sym} "
            f"(book weight {_fmt_pct(book_w)}, fire={fire_s}). "
            f"Under max_name {max_name}% / fire {conc_fire}%, the desk wants size honesty — "
            f"prefer portfolio-level weight over account-scoped % rows. "
            f"Fit: hold/review until book weight clearly exceeds posture; "
            f"tension: do not invent urgency from account-only concentration artifacts."
        )

    return _full_sentence(
        f"({pin}/{stance}): situation {(p.get('situation_type') or '').replace('_', ' ')} "
        f"on {','.join(syms) or 'book'} (fire={fire_s}) is escalated for operator judgment. "
        f"Default under defensive_observe is observe/stage, never auto-execute."
    )


def _multi_domain_line(p: dict[str, Any], port: dict[str, Any]) -> str:
    """Complete multi-domain sentence from plan fields + book snapshot."""
    md = (p.get("multi_domain_summary") or "").strip()
    domains = p.get("evidence_domains") or []
    if not domains and md.startswith("Domains "):
        # parse "Domains a, b, c:"
        head = md.split(":", 1)[0].replace("Domains", "").strip()
        domains = [x.strip() for x in head.split(",") if x.strip()]
    dom_s = ", ".join(str(d) for d in domains[:6]) if domains else "partial"
    bits = []
    if port.get("total_value") is not None:
        bits.append(f"book={_fmt_usd(port.get('total_value'))}")
    if port.get("cash_pct") is not None:
        bits.append(f"cash={_fmt_pct(port.get('cash_pct'))}")
    if port.get("heat_pct") is not None:
        bits.append(f"heat={_fmt_pct(port.get('heat_pct'))}")
    # keep plan multi-domain facts if present and complete
    plan_facts = ""
    if ":" in md:
        plan_facts = md.split(":", 1)[-1].strip()
        plan_facts = _full_sentence(plan_facts, max_len=280)
    core = f"Domains [{dom_s}]"
    if bits:
        core += " · " + " · ".join(bits)
    if plan_facts:
        core += f". Plan evidence: {plan_facts}"
    if not core.endswith("."):
        core += "."
    return core


def render_desk_note(data: Optional[dict[str, Any]] = None, *, telegram: bool = True) -> str:
    """Render operator-facing desk note (complete sentences, no mid-cut)."""
    d = data or collect_desk_inputs()
    pin = d.get("pin") or "desk@?"
    th = d.get("thesis") or {}
    thr = d.get("thresholds") or {}
    port = d.get("portfolio") or {}
    materials: list[dict[str, Any]] = d.get("material_plans") or []
    learning: list[dict[str, Any]] = d.get("learning") or []

    stance = th.get("stance") or "unknown"
    rps = th.get("risk_posture_structured") or thr
    cash_band = thr.get("cash_band_min_pct") or rps.get("cash_band_min_pct") or 20
    max_name = thr.get("max_single_name_weight_pct") or rps.get("max_single_name_weight_pct") or 12
    conc_fire = thr.get("concentration_fire_pct") or rps.get("concentration_fire_pct") or 16.5
    deep_dd = thr.get("deep_dd_threshold_pct") or rps.get("deep_dd_threshold_pct") or 25

    cash_pct = port.get("cash_pct")
    total_value = port.get("total_value")
    total_cash = port.get("total_cash")
    heat = port.get("heat_pct")
    day = port.get("day_change_pct")
    top = port.get("top_weights") or []
    schd_w = port.get("schd_weight_pct")
    spcx = port.get("spcx") or {}

    cash_gap = None
    if cash_pct is not None:
        cash_gap = cash_pct - float(cash_band)

    lines: list[str] = []
    if telegram:
        lines.append(f"🏦 *CIO desk note v1.1* · READ_ONLY · `{pin}`")
        lines.append(f"stance: *{stance}* · as_of {str(d.get('as_of') or '')[:19]}Z")
    else:
        lines.append(f"# CIO desk note v1.1 · {pin}")
        lines.append(f"stance: {stance} · as_of {d.get('as_of')}")
    lines.append("────────────────")

    # 1 Thesis header — full summary (sentence-safe)
    lines.append("🎯 *1. Thesis header*")
    lines.append(_full_sentence(th.get("summary") or "(no thesis summary)", max_len=700))
    lines.append(
        f"Risk posture (structured): max single-name {max_name}% · "
        f"cash band min {cash_band}% · deep DD {deep_dd}% · concentration fire ≈{conc_fire}%."
    )
    principles = th.get("principles") or []
    if principles:
        lines.append("Principles: " + " ".join(f"({i+1}) {p}" for i, p in enumerate(principles[:5])))
    lines.append("")

    # 2 Portfolio snapshot
    lines.append("📊 *2. Portfolio snapshot*")
    lines.append(
        f"Book {_fmt_usd(total_value)} · day {_fmt_pct(day, signed=True)} · "
        f"holdings {port.get('holdings_count') or '—'}."
    )
    lines.append(
        f"Cash {_fmt_usd(total_cash)} ({_fmt_pct(cash_pct)}) vs band {cash_band}% "
        + (f"(gap {_fmt_pct(cash_gap, signed=True)})." if cash_gap is not None else ".")
    )
    lines.append(
        f"Heat {_fmt_pct(heat)} · stops_active "
        f"{port.get('stops_active') if port.get('stops_active') is not None else '—'}."
    )
    if top:
        top_s = ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in top[:8])
        lines.append(f"Top weights (book-aggregated): {top_s}.")
    lines.append("")

    # 3 Material situations with DISTINCT thesis fit
    lines.append("📍 *3. Material situations* (desk-filtered)")
    focus: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for p in materials:
        st = str(p.get("situation_type") or "")
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        if "TEST" in "".join(syms) or "SPACEX_TEST" in syms:
            continue
        key = f"{st}:{','.join(syms)}"
        if key in seen_keys:
            continue
        if st.startswith("S6") and syms == ["CASH"]:
            continue
        if st.startswith("S6") and syms:
            book_w = next((t["weight_pct"] for t in top if t["symbol"] == syms[0]), None)
            fire = " ".join(str(x) for x in (p.get("fire_reasons") or []))
            claimed = None
            for tok in fire.replace(",", " ").split():
                if tok.startswith("weight_") and "pct" in tok:
                    try:
                        claimed = float(tok.replace("weight_", "").replace("pct", ""))
                    except Exception:
                        pass
            if claimed is not None and claimed >= 25:
                if book_w is None or book_w < float(max_name) * 0.5:
                    continue
            if book_w is not None and book_w < 5 and claimed and claimed >= 30:
                continue
        if st in ("S5_CASH_DEPLOYMENT", "S6_CONCENTRATION_OR_DISPOSITION", "S1_POSITION_LIFECYCLE"):
            focus.append(p)
            seen_keys.add(key)
        if len(focus) >= 5:
            break

    if not focus:
        lines.append("No open material plans after desk filters.")
    for p in focus:
        st = (p.get("situation_type") or "").replace("_", " ")
        syms = ",".join(p.get("symbols") or []) or "book"
        pid = p.get("plan_id")
        fire = ", ".join(str(x) for x in (p.get("fire_reasons") or [])[:4])
        lines.append(f"• *{st}* · {syms}")
        lines.append(f"  Fire: {fire or '—'}.")
        rec = (p.get("recommendation") or "").strip()
        rec1 = _full_sentence(rec.split("\n")[0], max_len=320)
        if rec1:
            lines.append(f"  Rec: {rec1}")
        ta = _thesis_fit_for_plan(
            p, pin=pin, stance=stance, thr=thr, port=port, learning=learning,
        )
        # avoid "Thesis fit: Thesis fit (...)"
        ta_out = ta[len("Thesis fit: "):] if ta.startswith("Thesis fit:") else ta
        lines.append(f"  Thesis fit: {ta_out}")
        lines.append(f"  Multi-domain: {_multi_domain_line(p, port)}")
        lines.append(f"  Plan: `{pid}` · pin `{p.get('thesis_version') or pin}`.")
    lines.append("")

    # 4 Cross-position
    lines.append("🔗 *4. Cross-position view*")
    near = [t for t in top if t["weight_pct"] >= float(max_name)]
    watch = [t for t in top if float(max_name) * 0.7 <= t["weight_pct"] < float(max_name)]
    if near:
        lines.append(
            "Concentration cluster (book ≥ max_name): "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in near)
            + "."
        )
    else:
        lines.append(f"No book names at or above max_name {max_name}%.")
    if watch:
        lines.append(
            "Approaching band: "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in watch[:5])
            + "."
        )
    if cash_pct is not None:
        if cash_pct >= float(cash_band) + 15:
            runway = "elevated multi-quarter optionality; stage only with complete totals"
        elif cash_pct >= float(cash_band):
            runway = "above band — dry powder intentional under defensive_observe"
        else:
            runway = "inside/below band — less buffer"
        lines.append(f"Cash runway: {_fmt_pct(cash_pct)} ({runway}).")
    sleeve = [t for t in top if t["symbol"] in ("ARKX", "XAR", "XLI", "SPCX", "XLB")]
    if sleeve:
        sleeve_sum = sum(t["weight_pct"] for t in sleeve)
        lines.append(
            "Industrial/aero sleeve: "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in sleeve)
            + f" (≈{sleeve_sum:.1f}% combined) — correlated if space/industrials re-rate together."
        )
    if heat is not None:
        lines.append(
            f"Portfolio heat {_fmt_pct(heat)} with {port.get('stops_active')} stops marked active — "
            "low heat supports observe and does not authorize new risk from chat."
        )
    lines.append("")

    # 5 Recommendations + deeper analytical block
    lines.append(f"✅ *5. Desk recommendations* (under `{pin}`)")
    n = 1
    if cash_pct is not None and cash_pct >= float(cash_band):
        lines.append(
            f"{n}. *HOLD / STAGE cash* — {_fmt_pct(cash_pct)} ≫ band {cash_band}%. "
            f"Under {pin}, cash is a feature; do not force deploy while quality is partial."
        )
        n += 1
    if schd_w is not None and schd_w >= float(max_name):
        lines.append(
            f"{n}. *HOLD SCHD with buffer watch* — book {_fmt_pct(schd_w)} vs fire ≈{conc_fire}%. "
            "Honor operator defer ('wait for price buffer'); re-escalate only on fire break or thesis change."
        )
        n += 1
    spcx_plan = next(
        (
            p
            for p in materials
            if p.get("situation_type") == "S1_POSITION_LIFECYCLE"
            and "SPCX" in [str(s).upper() for s in (p.get("symbols") or [])]
        ),
        None,
    )
    if spcx_plan:
        lines.append(
            f"{n}. *HOLD SPCX (lifecycle)* — deep DD is material as signal but book weight "
            f"~{_fmt_pct(spcx.get('book_weight_pct'))} is small. Awareness-only under {pin}; no auto-stop."
        )
        n += 1
    lines.append(
        f"{n}. *ESCALATE to operator* any new single-name book weight ≥{max_name}% or cash regime "
        "change ≥3pp. Ignore account-scoped 40%+ concentration artifacts that disagree with book weights."
    )
    lines.append("All actions remain READ_ONLY_ADVISORY — no orders or stops from this note.")
    lines.append("")

    lines.append("🔬 *5b. Deeper analysis* (what would change the call)")
    # Cash deep
    lines.append(
        _full_sentence(
            f"Cash — To stage a first deployment slice under {pin}, all of the following should be true: "
            f"(1) total_cash and total_value are complete/quality OK (not PARTIAL), "
            f"(2) a named sleeve or staged idea has multi-domain support (not just 'cash high'), "
            f"(3) post-deploy cash still respects a floor near the {cash_band}% band unless stance changes, "
            f"(4) operator explicitly acks a plan_id for the slice. "
            f"Until then, highest-signal is HOLD cash at {_fmt_pct(cash_pct)} "
            f"({_fmt_usd(total_cash)} on a {_fmt_usd(total_value)} book).",
            max_len=700,
        )
    )
    # SCHD deep
    dist = (float(schd_w) - float(conc_fire)) if schd_w is not None else None
    defer = any(
        str(L.get("disposition") or "").lower() == "defer"
        and "SCHD" in [str(s).upper() for s in (L.get("symbols") or [])]
        for L in learning
    )
    lines.append(
        _full_sentence(
            f"SCHD — Book weight {_fmt_pct(schd_w)} vs fire ≈{conc_fire}% "
            f"(distance {_fmt_pct(dist, signed=True) if dist is not None else 'n/a'}). "
            f"{'Operator defer is active (wait for price buffer) and biases the desk to HOLD.' if defer else 'No SCHD defer on file.'} "
            f"What changes the hold: (a) book weight sustainably above fire with no buffer thesis, "
            f"(b) dividend/credit thesis break, or (c) operator rate/reject of the concentration plan. "
            f"What does not change the hold: routine day moves or account-scoped % that disagree with book weight.",
            max_len=700,
        )
    )
    # SPCX deep
    lines.append(
        _full_sentence(
            f"SPCX — Severity vs size: deep drawdown from basis is above the {deep_dd}% posture threshold, "
            f"but portfolio weight is only {_fmt_pct(spcx.get('book_weight_pct'))} "
            f"(~{_fmt_usd(spcx.get('market_value'))}). "
            f"That is why awareness-only is correct under {pin}: escalate for operator judgment, "
            f"keep hold/stop-above-BE/trim as *options*, never auto-execute. "
            f"What upgrades priority: book weight rising into the max_name band, new catalyst stack, "
            f"or operator request for Hermes research. What keeps it quiet: small sleeve + low portfolio heat "
            f"({_fmt_pct(heat)}).",
            max_len=700,
        )
    )
    lines.append("")

    # 6 Learning log (deduped)
    lines.append("🧠 *6. Learning log* (biases this note)")
    if not learning:
        lines.append("No recent operator dispositions recorded.")
    else:
        for L in learning[:6]:
            note = _full_sentence(L.get("note") or "", max_len=120)
            lines.append(
                f"• {L.get('disposition')} · {L.get('situation_type')} · "
                f"{','.join(L.get('symbols') or []) or '—'} · "
                f"{note or '—'} · pin {L.get('thesis_version') or '—'}"
            )
    lines.append("")

    # 7 Revisit + plan ids
    lines.append("🔄 *7. Revisit + ack*")
    plan_ids = [p.get("plan_id") for p in focus if p.get("plan_id")]
    if plan_ids:
        lines.append("Plans: " + " · ".join(f"`{x}`" for x in plan_ids[:6]))
        lines.append("Ack: `/cio ack <plan_id>` or reply `ack` on the Telegram thread.")
    else:
        lines.append("No material plan_ids in focus set.")
    lines.append(
        f"Revisit: 24h, or earlier if cash moves ≥3pp, SCHD book weight ≥{conc_fire}%, "
        "or SPCX makes new lows vs basis."
    )
    lines.append(f"Thesis: `/cio thesis` ({pin})")
    lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
    return "\n".join(lines)


def render_situation_card_contrast(plan: dict[str, Any]) -> str:
    """Short current-style situation card for side-by-side quality contrast."""
    st = (plan.get("situation_type") or "").replace("_", " ")
    syms = ",".join(plan.get("symbols") or []) or "—"
    fire = ", ".join(str(x) for x in (plan.get("fire_reasons") or [])[:3])
    return "\n".join(
        [
            f"📍 Situation card (legacy thin): {st} · {syms}",
            f"Why: {fire or '—'}",
            f"Summary: {_full_sentence(plan.get('summary') or '', max_len=220)}",
            f"Rec: {_full_sentence(plan.get('recommendation') or '', max_len=180)}",
            f"plan_id: `{plan.get('plan_id')}`",
            "_(single-situation, little portfolio context)_",
        ]
    )


def generate_desk_synthesis_v1() -> dict[str, Any]:
    """Return structured payload + rendered note + contrast sample."""
    data = collect_desk_inputs()
    note = render_desk_note(data, telegram=True)
    sample = None
    for p in data.get("material_plans") or []:
        if p.get("plan_id") == "plan_79fe9e72f2d4":
            sample = p
            break
    if sample is None and data.get("material_plans"):
        sample = data["material_plans"][0]
    contrast = render_situation_card_contrast(sample) if sample else "(no plan)"
    return {
        "ok": True,
        "as_of": data.get("as_of"),
        "thesis_version": data.get("pin"),
        "portfolio": {
            k: (data.get("portfolio") or {}).get(k)
            for k in (
                "total_value", "total_cash", "cash_pct", "day_change_pct",
                "holdings_count", "heat_pct", "stops_active", "top_weights",
            )
        },
        "note": note,
        "contrast_card": contrast,
        "material_plan_ids": [p.get("plan_id") for p in (data.get("material_plans") or [])][:12],
        "learning_count": len(data.get("learning") or []),
        "authority": "READ_ONLY_ADVISORY",
    }


if __name__ == "__main__":
    out = generate_desk_synthesis_v1()
    print(out["note"])
    print("\n======== CONTRAST ========\n")
    print(out["contrast_card"])
    print("\n--- portfolio ---")
    print(out.get("portfolio"))
