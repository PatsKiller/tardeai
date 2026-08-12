"""CIO desk synthesis v1.2.1 — portfolio-grade advisory note under live desk@vN.

READ_ONLY_ADVISORY. Combines thesis + Data Broker snapshot + material plans +
operator learning + re-entry book + sector defensive posture into one
operator-facing desk note (Telegram + /v3/cio).

v1.2.1: re-entry book (desk-governed stage 0/1/2), sector posture (lookthrough),
disposition-conditioned recommendation text, section order extended,
no mid-sentence truncation, CLI/API parity.
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
    """Dedupe by plan_id+disposition+day (preferred) else content key."""
    try:
        try:
            from lib.cio_desk_depth import dedupe_learning  # type: ignore
        except Exception:
            from scripts.lib.cio_desk_depth import dedupe_learning  # type: ignore
        return dedupe_learning(rows)
    except Exception:
        pass
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        day = str(r.get("ts") or "")[:10]
        pid = str(r.get("plan_id") or "")
        disp = str(r.get("disposition") or "")
        if pid and disp:
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

    # Snapshot quality for cash-stage
    quality = "OK"
    if total_value is None or total_cash is None or cash_pct is None:
        quality = "PARTIAL"
    # Partial if S5 plans claim PARTIAL in fire reasons
    for p in materials:
        fr = " ".join(str(x) for x in (p.get("fire_reasons") or []))
        if "PARTIAL" in fr.upper() or "quality_PARTIAL" in fr:
            quality = "PARTIAL"
            break

    thr = {
        "cash_band_min_pct": cash_band,
        "max_single_name_weight_pct": max_name,
        "concentration_fire_pct": conc_fire,
        "deep_dd_threshold_pct": deep_dd,
    }

    # Sector labels from holdings rows
    symbol_sectors: dict[str, str] = {}
    for sym, rlist in by_sym.items():
        for r in rlist:
            sec = str(r.get("sector") or "").strip()
            if sec and sec.lower() != "cash":
                symbol_sectors[sym] = sec
                break

    symbol_weights = {s: float(w) for s, w in agg.items()}

    # Depth modules (fail-soft)
    cash_stage: dict[str, Any] = {"stage": 0, "label": "STAGE_0", "name": "Observe only"}
    sector_posture: dict[str, Any] = {}
    reentry_book: dict[str, Any] = {"ok": False, "cards": []}
    try:
        try:
            from lib.cio_desk_depth import (  # type: ignore
                compute_cash_stage,
                build_sector_posture,
                build_reentry_book,
                has_operator_stage_opt_in,
            )
        except Exception:
            from scripts.lib.cio_desk_depth import (  # type: ignore
                compute_cash_stage,
                build_sector_posture,
                build_reentry_book,
                has_operator_stage_opt_in,
            )
        cash_stage = compute_cash_stage(
            cash_pct=cash_pct,
            total_cash=total_cash,
            total_value=total_value,
            cash_band_min_pct=float(cash_band),
            quality=quality,
            operator_stage_opt_in=has_operator_stage_opt_in(learning),
            heat_pct=_f(risk.get("portfolio_heat_pct")),
        )
        sector_posture = build_sector_posture(
            symbol_weights=symbol_weights,
            symbol_sectors=symbol_sectors,
            pin=pin or "desk@?",
            cash_pct=cash_pct,
            stance=str(thesis.get("stance") or "defensive_observe"),
        )
        reentry_book = build_reentry_book(
            pin=pin or "desk@?",
            thr=thr,
            cash_stage=cash_stage,
            cash_pct=cash_pct,
            symbol_weights=symbol_weights,
            sector_posture=sector_posture,
            heat_pct=_f(risk.get("portfolio_heat_pct")),
            max_display=10,
        )
    except Exception as e:
        try:
            Path("/tmp/cio_desk_depth_err.txt").write_text(f"{type(e).__name__}:{e}"[:2000])
        except Exception:
            pass

    return {
        "as_of": _now(),
        "pin": pin,
        "thesis": thesis,
        "thresholds": thr,
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
            "symbol_weights": symbol_weights,
            "symbol_sectors": symbol_sectors,
            "data_quality": quality,
        },
        "cash_stage": cash_stage,
        "sector_posture": sector_posture,
        "reentry_book": reentry_book,
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



def _book_weight_for_plan(p: dict[str, Any], top: list[dict[str, Any]], port: dict[str, Any]) -> Optional[float]:
    syms = [str(s).upper() for s in (p.get("symbols") or [])]
    if not syms:
        return None
    # top_weights
    for t in top:
        if t.get("symbol") == syms[0]:
            return _f(t.get("weight_pct"))
    sw = port.get("symbol_weights") or {}
    if syms[0] in sw:
        return _f(sw.get(syms[0]))
    # by_symbol_rows aggregate
    rows = (port.get("by_symbol_rows") or {}).get(syms[0]) or []
    if rows:
        total = 0.0
        any_w = False
        for r in rows:
            w = _f(r.get("weight_pct") or r.get("weight"))
            if w is not None:
                total += w
                any_w = True
        if any_w:
            return total
    return None


def _is_residual_dead_name(
    p: dict[str, Any],
    *,
    book_w: Optional[float],
) -> bool:
    """True when fire is residual disposition/DD and book weight missing or ≈0."""
    if book_w is not None and book_w >= 0.25:
        return False
    fire = " ".join(str(x) for x in (p.get("fire_reasons") or [])).lower()
    st = str(p.get("situation_type") or "")
    residual_tokens = (
        "disposition_loss_100",
        "deep_drawdown_from_basis_100",
        "disposition_loss_99",
        "weight_0",
        "dead",
        "worthless",
    )
    if any(tok in fire for tok in residual_tokens):
        return True
    # 100% style DD/loss with no meaningful book weight
    if re.search(r"(drawdown|loss|dd)[_ ].*100", fire) or "100.0pct" in fire or "100pct" in fire:
        if book_w is None or book_w < 0.25:
            return True
    # S1/S6 on name not in book at all
    if st in ("S1_POSITION_LIFECYCLE", "S6_CONCENTRATION_OR_DISPOSITION"):
        if book_w is None or book_w < 0.05:
            # keep SCHD always in main if somehow zero - safety
            syms = [str(s).upper() for s in (p.get("symbols") or [])]
            if "SCHD" in syms or "SPCX" in syms:
                return False
            # residual if fire claims huge loss/DD or disposition
            if "disposition" in fire or "drawdown" in fire or "100" in fire:
                return True
    return False


def render_desk_note(data: Optional[dict[str, Any]] = None, *, telegram: bool = True) -> str:
    """Render operator-facing desk note v1.2 (complete sentences, disposition-aware)."""
    d = data or collect_desk_inputs()
    pin = d.get("pin") or "desk@?"
    th = d.get("thesis") or {}
    thr = d.get("thresholds") or {}
    port = d.get("portfolio") or {}
    materials: list[dict[str, Any]] = d.get("material_plans") or []
    learning: list[dict[str, Any]] = d.get("learning") or []
    cash_stage = d.get("cash_stage") or {}
    sector_posture = d.get("sector_posture") or {}
    reentry = d.get("reentry_book") or {}

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
    quality = port.get("data_quality") or "OK"

    cash_gap = None
    if cash_pct is not None:
        cash_gap = cash_pct - float(cash_band)

    # Disposition helpers
    try:
        try:
            from lib.cio_desk_depth import active_disposition_phrase  # type: ignore
        except Exception:
            from scripts.lib.cio_desk_depth import active_disposition_phrase  # type: ignore
    except Exception:
        def active_disposition_phrase(learning, symbols):  # type: ignore
            return None

    def _rec_for_plan(p: dict[str, Any]) -> str:
        """Disposition-aware recommendation first line (must mention prior when present)."""
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        prior = active_disposition_phrase(learning, syms)
        raw = (p.get("recommendation") or "").strip()
        raw1 = _full_sentence(raw.split("\n")[0], max_len=280) if raw else ""
        st = str(p.get("situation_type") or "")
        if prior:
            # Lead with operator prior; never primary-trim on active defer
            if "defer" in prior.lower() and st.startswith("S6"):
                return _full_sentence(
                    f"{prior} Primary under {pin}: HOLD / size-watch — not trim/dispose — "
                    f"while defer is active and no stronger rule breach.",
                    max_len=500,
                )
            return _full_sentence(
                f"{prior} Desk path under {pin}: observe/stage; no auto-execute.",
                max_len=400,
            )
        if raw1:
            return raw1
        return _full_sentence(
            f"Highest-signal under {pin} ({stance}): observe/stage — never auto-execute.",
            max_len=280,
        )

    lines: list[str] = []
    stage_label = cash_stage.get("label") or "STAGE_?"
    if telegram:
        lines.append(f"🏦 *CIO desk note v1.2.1* · READ_ONLY · `{pin}`")
        lines.append(
            f"stance: *{stance}* · cash {stage_label} · as_of {str(d.get('as_of') or '')[:19]}Z"
        )
    else:
        lines.append(f"# CIO desk note v1.2.1 · {pin}")
        lines.append(f"stance: {stance} · cash {stage_label} · as_of {d.get('as_of')}")
    lines.append("────────────────")

    # 1 Thesis header
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
        f"holdings {port.get('holdings_count') or '—'} · data_quality={quality}."
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
    lines.append(
        f"Cash stage: *{stage_label}* — {cash_stage.get('name') or ''}. "
        f"{cash_stage.get('recommendation') or ''} "
        f"({cash_stage.get('reason') or ''})."
    )
    lines.append("")

    # 3 Sector defensive posture (NEW)
    lines.append(f"🛡️ *3. Sector posture* · `{pin}`")
    if not sector_posture:
        lines.append("Sector posture DATA_UNAVAILABLE (depth module did not load).")
    else:
        tb = sector_posture.get("tilt_book_pct") or {}
        lines.append(
            f"Book defensive share ≈ {tb.get('DEFENSIVE', 0):.1f}% | "
            f"offensive/cyclical ≈ {tb.get('OFFENSIVE', 0):.1f}% | "
            f"unclassified ≈ {tb.get('UNCLASSIFIED', 0):.1f}% "
            f"(quality={sector_posture.get('quality') or '—'})."
        )
        top3 = sector_posture.get("top3") or []
        if top3:
            lines.append(
                "Largest sector concentrations (lookthrough-aware when available): "
                + ", ".join(f"{x['sector']} {x['weight_pct']}%" for x in top3)
                + "."
            )
        lines.append(
            f"Sector policy: {sector_posture.get('sector_cap_policy') or 'no formal sector cap in desk@v4 yet'} "
            f"(soft report cap {sector_posture.get('sector_soft_cap_pct')}%)."
        )
        for t in (sector_posture.get("tensions") or [])[:4]:
            lines.append(f"• {_full_sentence(t, max_len=280)}")
        sleeves = sector_posture.get("correlated_sleeves") or {}
        if sleeves:
            lines.append(
                "Correlated sleeves: "
                + ", ".join(f"{k.replace('_', '/')} ≈{v}%" for k, v in sleeves.items())
                + "."
            )
        improve = sector_posture.get("improve") or []
        if improve:
            lines.append("What would improve posture without force-deploy: " + "; ".join(improve[:3]) + ".")
        qn = sector_posture.get("quality_notes") or []
        if qn:
            lines.append("Data notes: " + "; ".join(qn[:2]) + ".")
    lines.append("")

    # 4 Material situations — disposition-aware; residual dead names → appendix
    lines.append("📍 *4. Material situations* (desk-filtered, disposition-aware)")
    focus: list[dict[str, Any]] = []
    appendix: list[dict[str, Any]] = []
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
        book_w = _book_weight_for_plan(p, top, port)
        if st.startswith("S6") and syms:
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
                    # account-scoped artifact — skip entirely (not even appendix)
                    continue
            if book_w is not None and book_w < 5 and claimed and claimed >= 30:
                continue
        if st not in ("S5_CASH_DEPLOYMENT", "S6_CONCENTRATION_OR_DISPOSITION", "S1_POSITION_LIFECYCLE"):
            continue
        seen_keys.add(key)
        if _is_residual_dead_name(p, book_w=book_w):
            appendix.append({**p, "_book_w": book_w})
            continue
        focus.append(p)
        if len(focus) >= 5:
            # keep scanning for appendix demotions
            pass
    focus = focus[:5]

    if not focus:
        lines.append("No open material plans after desk filters.")
    for p in focus:
        st = (p.get("situation_type") or "").replace("_", " ")
        syms = ",".join(p.get("symbols") or []) or "book"
        pid = p.get("plan_id")
        fire = ", ".join(str(x) for x in (p.get("fire_reasons") or [])[:4])
        lines.append(f"• *{st}* · {syms}")
        lines.append(f"  Fire: {fire or '—'}.")
        lines.append(f"  Rec: {_rec_for_plan(p)}")
        ta = _thesis_fit_for_plan(
            p, pin=pin, stance=stance, thr=thr, port=port, learning=learning,
        )
        ta_out = ta[len("Thesis fit: "):] if ta.startswith("Thesis fit:") else ta
        lines.append(f"  Thesis fit: {ta_out}")
        lines.append(f"  Multi-domain: {_multi_domain_line(p, port)}")
        lines.append(f"  Plan: `{pid}` · pin `{p.get('thesis_version') or pin}`.")
    if appendix:
        lines.append(
            f"📎 *Appendix — residual / dead-name situations* ({len(appendix)}; "
            "book weight missing or ≈0 — not main material)"
        )
        for p in appendix[:8]:
            st = (p.get("situation_type") or "").replace("_", " ")
            syms = ",".join(p.get("symbols") or []) or "—"
            fire = ", ".join(str(x) for x in (p.get("fire_reasons") or [])[:3])
            bw = p.get("_book_w")
            lines.append(
                f"• {st} · {syms} · fire={fire or '—'} · "
                f"book_w={_fmt_pct(bw) if bw is not None else 'missing/≈0'} · "
                f"`{p.get('plan_id')}` — demoted (residual disposition/DD)."
            )
    lines.append("")

    # 5 Re-entry book — core vs micro (v1.2.1)
    core_n = reentry.get("core_count")
    micro_n = reentry.get("micro_count")
    lines.append(
        f"📋 *5. Re-entry book* · `{pin}` · stage={cash_stage.get('stage', '?')} ({stage_label}) · "
        f"core={core_n if core_n is not None else '?'} micro={micro_n if micro_n is not None else '?'}"
    )
    if reentry.get("error"):
        lines.append(f"Re-entry desk error: {reentry.get('error')} (fail-soft).")
    core_cards = reentry.get("core_cards") or [
        c for c in (reentry.get("cards") or []) if c.get("tier") in (None, "core")
    ]
    # Prefer core_cards; fall back to cards filtered
    if not core_cards and reentry.get("cards"):
        core_cards = [c for c in reentry["cards"] if c.get("tier") != "micro_ready"]
    micro_ready = reentry.get("micro_expanded") or [
        c for c in (reentry.get("cards") or []) if c.get("tier") == "micro_ready"
    ]

    def _emit_card(c: dict[str, Any]) -> None:
        zone = c.get("entry_zone") or "—"
        if c.get("rr_error"):
            rr_s = "DATA_ERROR (suppressed absurd R:R)"
        elif c.get("rr") is not None:
            rr_s = f"{c.get('rr')}"
        else:
            rr_s = "—"
        sz = c.get("sizing") or {}
        size_s = "—"
        if sz.get("shares") is not None:
            alloc = sz.get("allocation")
            alloc_s = _fmt_usd(alloc) if isinstance(alloc, (int, float)) else str(alloc or "—")
            size_s = f"{sz.get('shares')} sh · {alloc_s}"
            if sz.get("note"):
                size_s += f" ({_full_sentence(sz.get('note'), max_len=60)})"
        px = c.get("price")
        if isinstance(px, (int, float)):
            px_s = f"${px:.2f}" if px < 1000 else _fmt_usd(px)
        else:
            px_s = str(px or "—")
        lines.append(
            f"• *{c.get('symbol')}* · {c.get('state')} · px {px_s} · "
            f"zone {zone} · R:R {rr_s} · RSI {c.get('rsi') if c.get('rsi') is not None else '—'} · "
            f"size {size_s}"
        )
        lines.append(f"  Stage gate: {_full_sentence(c.get('stage_gate') or '', max_len=320)}")
        lines.append(f"  Desk fit: {_full_sentence(c.get('desk_fit') or '', max_len=400)}")
        why = c.get("why") or []
        if why:
            lines.append(f"  Why: {_full_sentence('; '.join(str(x) for x in why[:2]), max_len=240)}")
        gaps = c.get("confirmation_gaps") or []
        if gaps:
            lines.append(f"  Confirmation gaps: {', '.join(str(g) for g in gaps[:4])}.")
        lines.append(f"  Pin `{c.get('thesis_version') or pin}` · READ_ONLY.")

    if not core_cards and not micro_ready:
        lines.append(
            "No core-relevant READY/NEAR/OVERSOLD candidates after quality filter "
            f"(actionable_raw={reentry.get('actionable_count', 0)}, "
            f"core={core_n}, micro={micro_n})."
        )
    else:
        if core_cards:
            lines.append(
                f"*Core-relevant* (px≥$5 or liquid ADV; not wash-blocked; confirmations evaluated) — {len(core_cards)} shown:"
            )
            for c in core_cards[:10]:
                _emit_card(c)
        else:
            lines.append("No core-relevant names this pass (all actionable were micro/speculative or filtered).")
        if micro_ready:
            lines.append(
                f"*Micro READY + confirmations_complete* (exception expand) — {len(micro_ready)}:"
            )
            for c in micro_ready[:3]:
                _emit_card(c)
    if reentry.get("micro_line"):
        lines.append("• " + _full_sentence(reentry.get("micro_line"), max_len=500))
    watch = reentry.get("watch") or []
    if watch:
        lines.append(
            "Watch-only (WAIT/OVERBOUGHT with plan): "
            + ", ".join(f"{w.get('symbol')}={w.get('state')}" for w in watch[:4])
            + "."
        )
    lines.append(_full_sentence(reentry.get("footer") or (
        f"Candidates from Data Broker reentry_decision_desk; READY is deterministic; {pin} governs stage."
    ), max_len=360))
    lines.append("")
    # cards variable for later rec section — prefer core
    cards = core_cards or micro_ready or (reentry.get("cards") or [])

    # 6 Cross-position
    lines.append("🔗 *6. Cross-position / correlated sleeves*")
    near = [t for t in top if t["weight_pct"] >= float(max_name)]
    watch_band = [t for t in top if float(max_name) * 0.7 <= t["weight_pct"] < float(max_name)]
    if near:
        lines.append(
            "Concentration cluster (book ≥ max_name): "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in near)
            + "."
        )
    else:
        lines.append(f"No book names at or above max_name {max_name}%.")
    if watch_band:
        lines.append(
            "Approaching band: "
            + ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in watch_band[:5])
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

    # 7 Desk recommendations (disposition-aware)
    lines.append(f"✅ *7. Desk recommendations* (under `{pin}`)")
    n = 1
    if cash_pct is not None and cash_pct >= float(cash_band):
        lines.append(
            f"{n}. *HOLD / STAGE cash* — {_fmt_pct(cash_pct)} ≫ band {cash_band}%. "
            f"Cash {stage_label}: {cash_stage.get('recommendation') or 'paper plan only'}. "
            f"Under {pin}, cash is a feature; do not force deploy while quality is {quality}."
        )
        n += 1
    if schd_w is not None and schd_w >= float(max_name):
        prior = active_disposition_phrase(learning, ["SCHD"])
        if prior:
            lines.append(
                f"{n}. *HOLD SCHD (disposition-bound)* — {prior} "
                f"Book {_fmt_pct(schd_w)} vs fire ≈{conc_fire}%. "
                f"Primary action is HOLD / buffer-watch — not trim — while defer is active."
            )
        else:
            lines.append(
                f"{n}. *HOLD SCHD with size review* — book {_fmt_pct(schd_w)} vs fire ≈{conc_fire}%. "
                "No operator defer on file; still prefer thesis-aware hold over forced dispose."
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
        prior_s = active_disposition_phrase(learning, ["SPCX"])
        lines.append(
            f"{n}. *HOLD SPCX (lifecycle)* — "
            + (f"{prior_s} " if prior_s else "")
            + f"deep DD is material as signal but book weight ~{_fmt_pct(spcx.get('book_weight_pct'))} is small. "
            f"Awareness-only under {pin}; no auto-stop."
        )
        n += 1
    # Re-entry stage guidance
    if cards:
        top_c = cards[0]
        lines.append(
            f"{n}. *Re-entry book top* — {top_c.get('symbol')} is {top_c.get('state')} "
            f"under {stage_label}: {_full_sentence(top_c.get('stage_gate') or 'watch only', max_len=200)} "
            "No buy-now language."
        )
        n += 1
    lines.append(
        f"{n}. *ESCALATE to operator* any new single-name book weight ≥{max_name}% or cash regime "
        "change ≥3pp. Ignore account-scoped 40%+ concentration artifacts that disagree with book weights."
    )
    lines.append("All actions remain READ_ONLY_ADVISORY — no orders or stops from this note.")
    lines.append("")

    lines.append("🔬 *7b. Deeper analysis* (what would change the call)")
    lines.append(
        _full_sentence(
            f"Cash — To advance beyond {stage_label} under {pin}: "
            f"(1) total_cash and total_value quality OK (not PARTIAL), "
            f"(2) a named READY candidate with confirmations_complete, "
            f"(3) post-deploy weight < max_single_name {max_name}% and sector posture not worsened unchecked, "
            f"(4) operator explicitly acks a plan_id / stage opt-in. "
            f"Until then, highest-signal is HOLD cash at {_fmt_pct(cash_pct)} "
            f"({_fmt_usd(total_cash)} on a {_fmt_usd(total_value)} book).",
            max_len=700,
        )
    )
    dist = (float(schd_w) - float(conc_fire)) if schd_w is not None else None
    prior_schd = active_disposition_phrase(learning, ["SCHD"])
    lines.append(
        _full_sentence(
            f"SCHD — Book weight {_fmt_pct(schd_w)} vs fire ≈{conc_fire}% "
            f"(distance {_fmt_pct(dist, signed=True) if dist is not None else 'n/a'}). "
            f"{prior_schd or 'No SCHD defer on file.'} "
            f"What changes the hold: (a) operator revisits/rejects the defer, "
            f"(b) book weight sustainably above fire with no buffer thesis, "
            f"(c) dividend/credit thesis break. "
            f"What does not change the hold: routine day moves or account-scoped % that disagree with book weight. "
            f"Primary action while defer active: HOLD — not trim.",
            max_len=700,
        )
    )
    lines.append(
        _full_sentence(
            f"SPCX — Severity vs size: deep drawdown from basis is above the {deep_dd}% posture threshold, "
            f"but portfolio weight is only {_fmt_pct(spcx.get('book_weight_pct'))} "
            f"(~{_fmt_usd(spcx.get('market_value'))}). "
            f"Awareness-only under {pin}: escalate for operator judgment, "
            f"keep hold/stop-above-BE/trim as *options*, never auto-execute. "
            f"What upgrades priority: book weight rising into the max_name band, new catalyst stack, "
            f"or operator request for Hermes research. What keeps it quiet: small sleeve + low portfolio heat "
            f"({_fmt_pct(heat)}).",
            max_len=700,
        )
    )
    lines.append("")

    # 8 Learning log — only entries that biased this note
    lines.append("🧠 *8. Learning log* (entries that biased this note)")
    biased: list[dict[str, Any]] = []
    focus_syms = set()
    for p in focus:
        for s in (p.get("symbols") or []):
            focus_syms.add(str(s).upper())
    focus_syms.update({"SCHD", "SPCX"})
    for L in learning:
        Lsyms = {str(s).upper() for s in (L.get("symbols") or [])}
        if Lsyms & focus_syms or str(L.get("disposition") or "").lower() in ("defer", "reject"):
            biased.append(L)
    if not biased and not learning:
        lines.append("No recent operator dispositions recorded.")
    elif not biased:
        lines.append("Dispositions on file but none matched this note's focus symbols.")
        for L in learning[:3]:
            note = _full_sentence(L.get("note") or "", max_len=120)
            lines.append(
                f"• {L.get('disposition')} · {L.get('situation_type')} · "
                f"{','.join(L.get('symbols') or []) or '—'} · {note or '—'} · pin {L.get('thesis_version') or '—'}"
            )
    else:
        for L in biased[:6]:
            note = _full_sentence(L.get("note") or "", max_len=120)
            lines.append(
                f"• {L.get('disposition')} · {L.get('situation_type')} · "
                f"{','.join(L.get('symbols') or []) or '—'} · {note or '—'} · pin {L.get('thesis_version') or '—'} "
                f"→ applied as hard constraint on matching recs"
            )
    lines.append("")

    # 9 Revisit + ack
    lines.append("🔄 *9. Revisit + ack*")
    plan_ids = [p.get("plan_id") for p in focus if p.get("plan_id")]
    if plan_ids:
        lines.append("Plans: " + " · ".join(f"`{x}`" for x in plan_ids[:6]))
        lines.append("Ack: `/cio ack <plan_id>` or reply `ack` on the Telegram thread.")
    else:
        lines.append("No material plan_ids in focus set.")
    lines.append(
        f"Revisit: 24h, or earlier if cash moves ≥3pp, SCHD book weight ≥{conc_fire}%, "
        "or SPCX makes new lows vs basis, or a re-entry card flips to READY with confirmations complete."
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
    """Return structured payload + rendered note + contrast sample (CLI = API)."""
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

    # Side-by-side disposition demo for SCHD (quality bar C)
    schd_before = (
        "Highest-signal under desk: choose hold_with_thesis — stage/observe rather than force action."
    )
    try:
        try:
            from lib.cio_desk_depth import active_disposition_phrase  # type: ignore
        except Exception:
            from scripts.lib.cio_desk_depth import active_disposition_phrase  # type: ignore
        prior = active_disposition_phrase(data.get("learning") or [], ["SCHD"])
    except Exception:
        prior = None
    schd_after = (
        f"{prior} Primary under {data.get('pin')}: HOLD / size-watch — not trim/dispose — "
        "while defer is active and no stronger rule breach."
        if prior
        else schd_before + " (no SCHD disposition on file)"
    )

    port = data.get("portfolio") or {}
    return {
        "ok": True,
        "as_of": data.get("as_of"),
        "thesis_version": data.get("pin"),
        "version": "desk-note-v1.2.1",
        "portfolio": {
            k: port.get(k)
            for k in (
                "total_value", "total_cash", "cash_pct", "day_change_pct",
                "holdings_count", "heat_pct", "stops_active", "top_weights",
                "data_quality", "schd_weight_pct",
            )
        },
        "cash_stage": data.get("cash_stage"),
        "sector_posture": {
            k: (data.get("sector_posture") or {}).get(k)
            for k in (
                "quality", "tilt_book_pct", "top3", "correlated_sleeves",
                "sector_cap_policy", "tensions",
            )
        },
        "reentry_book": {
            "ok": (data.get("reentry_book") or {}).get("ok"),
            "stage": (data.get("reentry_book") or {}).get("stage"),
            "actionable_count": (data.get("reentry_book") or {}).get("actionable_count"),
            "core_count": (data.get("reentry_book") or {}).get("core_count"),
            "micro_count": (data.get("reentry_book") or {}).get("micro_count"),
            "core_display": (data.get("reentry_book") or {}).get("core_display"),
            "micro_expanded_count": (data.get("reentry_book") or {}).get("micro_expanded_count"),
            "micro_collapsed_count": (data.get("reentry_book") or {}).get("micro_collapsed_count"),
            "cards": (data.get("reentry_book") or {}).get("cards") or [],
            "core_cards": (data.get("reentry_book") or {}).get("core_cards") or [],
            "micro_line": (data.get("reentry_book") or {}).get("micro_line"),
            "footer": (data.get("reentry_book") or {}).get("footer"),
            "error": (data.get("reentry_book") or {}).get("error"),
        },
        "note": note,
        "contrast_card": contrast,
        "schd_disposition_demo": {"before": schd_before, "after": schd_after},
        "material_plan_ids": [p.get("plan_id") for p in (data.get("material_plans") or [])][:12],
        "learning_count": len(data.get("learning") or []),
        "learning": data.get("learning") or [],
        "authority": "READ_ONLY_ADVISORY",
    }


if __name__ == "__main__":
    out = generate_desk_synthesis_v1()
    note = out.get("note") or ""
    print(note)
    print("\n======== CONTRAST ========\n")
    print(out.get("contrast_card"))
    print("\n======== SCHD DISPOSITION ========\n")
    demo = out.get("schd_disposition_demo") or {}
    print("BEFORE:", demo.get("before"))
    print("AFTER:", demo.get("after"))
    print("\n--- portfolio ---")
    print(out.get("portfolio"))
    print("--- cash_stage ---")
    print(out.get("cash_stage"))
    rb = out.get("reentry_book") or {}
    print("--- reentry core/micro ---")
    print("core_count", rb.get("core_count"), "micro_count", rb.get("micro_count"))
    print("core_display", rb.get("core_display"), "micro_expanded", rb.get("micro_expanded_count"))
    for c in rb.get("core_cards") or rb.get("cards") or []:
        print("CORE", c.get("symbol"), c.get("state"), "rr", c.get("rr"), c.get("rr_error"), (c.get("stage_gate") or "")[:60])
    if rb.get("micro_line"):
        print("MICRO_LINE", (rb.get("micro_line") or "")[:200])
    # Persist latest note for operators / Telegram
    try:
        root = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
        for r in _candidate_project_roots():
            if (r / "data" / "cio").exists():
                root = r
                break
        out_path = root / "data" / "cio" / "cio_desk_note_latest.md"
        out_path.write_text(note + "\n", encoding="utf-8")
        print(f"\n[wrote {out_path}]")
    except Exception as e:
        print(f"[persist skipped: {e}]")
