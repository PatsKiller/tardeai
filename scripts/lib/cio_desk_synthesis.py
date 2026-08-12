"""CIO desk synthesis v1.3.0 — institutional book memo under live desk@vN.

READ_ONLY_ADVISORY. One thesis-governed portfolio advisory memo (not siloed
S-cards): cash × concentration × drawdown in a single argument, with evidence
spine, Hermes research agenda, and operator dispositions as hard constraints.

v1.3.0: 9-section institutional bar; shared evidence spine (catalyst/technicals/
Hermes); integrated narrative; Telegram memo spine; CLI/API parity.
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
            neg = [u for u in upls if u < 0]
            if neg and spcx_meta.get("dd_from_basis_pct") is None:
                # Prefer most underwater lot as drawdown signal when basis missing
                spcx_meta["dd_from_basis_pct"] = abs(min(neg))

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

    # Shared multi-domain evidence spine (catalyst / technicals / hermes)
    spine: dict[str, Any] = {}
    try:
        try:
            from lib.cio_evidence_spine import build_evidence_spine  # type: ignore
        except Exception:
            from scripts.lib.cio_evidence_spine import build_evidence_spine  # type: ignore
        spine = build_evidence_spine(
            snapshot=snap,
            thesis=thesis,
            pin=pin,
            material_plans=materials,
            learning=learning,
            focus_symbols=["SCHD", "SPCX"] + [s for s, _ in top[:6]],
            include_broker_enrich=True,
        )
        # Prefer spine name meta for SPCX DD
        nm = (spine.get("name_meta") or {}).get("SPCX") or {}
        if nm.get("dd_from_basis_pct") is not None:
            spcx_meta["dd_from_basis_pct"] = nm.get("dd_from_basis_pct")
        if nm.get("basis") is not None:
            spcx_meta["basis"] = nm.get("basis")
        if nm.get("last") is not None:
            spcx_meta["last"] = nm.get("last")
        if nm.get("market_value") is not None:
            spcx_meta["market_value"] = nm.get("market_value")
    except Exception as e:
        spine = {"gaps": [f"spine:{type(e).__name__}"], "domains_present": []}

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
        "evidence_spine": spine,
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
    """Render institutional book memo v1.3.0 (complete sentences, integrated narrative)."""
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
    spine = d.get("evidence_spine") or {}

    stance = th.get("stance") or "unknown"
    rps = th.get("risk_posture_structured") or thr
    cash_band = float(thr.get("cash_band_min_pct") or rps.get("cash_band_min_pct") or 20)
    max_name = float(thr.get("max_single_name_weight_pct") or rps.get("max_single_name_weight_pct") or 12)
    conc_fire = float(thr.get("concentration_fire_pct") or rps.get("concentration_fire_pct") or 16.5)
    deep_dd = float(thr.get("deep_dd_threshold_pct") or rps.get("deep_dd_threshold_pct") or 25)

    cash_pct = port.get("cash_pct")
    total_value = port.get("total_value")
    total_cash = port.get("total_cash")
    heat = port.get("heat_pct")
    day = port.get("day_change_pct")
    top = port.get("top_weights") or []
    schd_w = port.get("schd_weight_pct")
    spcx = port.get("spcx") or {}
    quality = port.get("data_quality") or "OK"
    stage_label = cash_stage.get("label") or "STAGE_?"
    cash_gap = (cash_pct - cash_band) if cash_pct is not None else None

    try:
        try:
            from lib.cio_desk_depth import active_disposition_phrase  # type: ignore
        except Exception:
            from scripts.lib.cio_desk_depth import active_disposition_phrase  # type: ignore
    except Exception:
        def active_disposition_phrase(learning, symbols):  # type: ignore
            return None

    try:
        try:
            from lib.cio_evidence_spine import evidence_map_lines  # type: ignore
        except Exception:
            from scripts.lib.cio_evidence_spine import evidence_map_lines  # type: ignore
    except Exception:
        def evidence_map_lines(spine):  # type: ignore
            return ["Evidence map DATA_UNAVAILABLE."]

    schd_prior = active_disposition_phrase(learning, ["SCHD"])
    spcx_prior = active_disposition_phrase(learning, ["SPCX"])
    name_meta = spine.get("name_meta") or {}
    schd_meta = name_meta.get("SCHD") or {}
    spcx_meta = {**(name_meta.get("SPCX") or {}), **spcx}
    cat_by = spine.get("catalyst_by_symbol") or {}
    tech_by = spine.get("technicals_by_symbol") or {}

    # Focus plans (book-real, not test/dead)
    focus: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in materials:
        st = str(p.get("situation_type") or "")
        syms = [str(s).upper() for s in (p.get("symbols") or [])]
        if "TEST" in "".join(syms) or "SPACEX_TEST" in syms:
            continue
        if st.startswith("S6") and syms == ["CASH"]:
            continue
        if st not in (
            "S5_CASH_DEPLOYMENT",
            "S6_CONCENTRATION_OR_DISPOSITION",
            "S1_POSITION_LIFECYCLE",
            "S8_DEFENSIVE_REGIME",
        ):
            continue
        # Drop account-scoped concentration artifacts that disagree with book weights
        if st.startswith("S6") and syms:
            book_w = None
            for t in top:
                if t.get("symbol") in syms:
                    book_w = float(t.get("weight_pct") or 0)
                    break
            fire = " ".join(str(x) for x in (p.get("fire_reasons") or []))
            claimed = None
            for tok in fire.replace(",", " ").split():
                if tok.startswith("weight_") and "pct" in tok:
                    try:
                        claimed = float(tok.replace("weight_", "").replace("pct", ""))
                    except Exception:
                        pass
            if claimed is not None and claimed >= 25 and (book_w is None or book_w < max_name * 0.5):
                continue
        key = f"{st}:{','.join(syms)}"
        if key in seen:
            continue
        seen.add(key)
        focus.append(p)
        if len(focus) >= 6:
            break

    lines: list[str] = []
    as_of = str(d.get("as_of") or "")[:19]
    if telegram:
        lines.append(f"🏦 *CIO book memo v1.3* · READ_ONLY · `{pin}`")
        lines.append(f"stance *{stance}* · cash {stage_label} · as_of {as_of}Z")
    else:
        lines.append(f"# CIO book memo v1.3.0 · {pin}")
        lines.append(f"stance: {stance} · cash {stage_label} · as_of {as_of}")
    lines.append("────────────────")

    # ── 1. Executive thesis ──────────────────────────────────────────────
    lines.append("🎯 *1. Executive thesis*")
    thesis_sum = _full_sentence(th.get("summary") or "", max_len=900)
    if not thesis_sum:
        thesis_sum = (
            f"Living pin `{pin}` stands on {stance}: preserve capital and optionality; "
            "size only when multi-domain evidence and cash quality support it."
        )
    lines.append(thesis_sum)
    exec_bits = [
        f"Under `{pin}` ({stance}), the book is not forced to deploy: cash at "
        f"{_fmt_pct(cash_pct)} vs a {cash_band:.0f}% band is intentional dry powder "
        f"({stage_label}), not a mandate to fill."
    ]
    if schd_w is not None:
        exec_bits.append(
            f"SCHD at {_fmt_pct(schd_w)} sits near concentration fire ≈{conc_fire:.1f}% "
            f"({'operator defer active: wait for price buffer' if schd_prior else 'size-watch without defer on file'}); "
            "primary path is HOLD / buffer-watch, not dispose-for-optics."
        )
    if spcx_meta.get("dd_from_basis_pct") is not None or spcx_meta.get("book_weight_pct") is not None:
        exec_bits.append(
            f"SPCX is a lifecycle awareness sleeve "
            f"(weight {_fmt_pct(spcx_meta.get('book_weight_pct') or spcx_meta.get('weight_pct'))}, "
            f"DD from basis {_fmt_pct(spcx_meta.get('dd_from_basis_pct'))}) — material as signal, "
            "small as portfolio risk; no auto-stop."
        )
    exec_bits.append(
        f"Heat {_fmt_pct(heat)} and stops_active "
        f"{port.get('stops_active') if port.get('stops_active') is not None else '—'} "
        "support observe. Non-action is first-class under defensive_observe. "
        "All of this is READ_ONLY_ADVISORY — no orders or stops from desk or chat."
    )
    lines.append(_full_sentence(" ".join(exec_bits), max_len=1600))
    principles = th.get("principles") or []
    if principles:
        lines.append(
            "Governing principles: "
            + " ".join(f"({i+1}) {_full_sentence(p, max_len=160)}" for i, p in enumerate(principles[:5]))
        )
    lines.append(
        f"Risk posture: max single-name {max_name:.0f}% · cash band min {cash_band:.0f}% · "
        f"deep DD {deep_dd:.0f}% · concentration fire ≈{conc_fire:.1f}%."
    )
    lines.append("")

    # ── 2. Portfolio state ───────────────────────────────────────────────
    lines.append("📊 *2. Portfolio state*")
    lines.append(
        f"Book {_fmt_usd(total_value)} · day {_fmt_pct(day, signed=True)} · "
        f"holdings {port.get('holdings_count') or '—'} · data_quality={quality}."
    )
    lines.append(
        f"Cash {_fmt_usd(total_cash)} ({_fmt_pct(cash_pct)}) vs band {cash_band:.0f}% "
        + (f"(gap {_fmt_pct(cash_gap, signed=True)})." if cash_gap is not None else ".")
    )
    lines.append(
        f"Heat {_fmt_pct(heat)} · stops_active "
        f"{port.get('stops_active') if port.get('stops_active') is not None else 'DATA_UNAVAILABLE'}."
    )
    lines.append(
        f"Cash stage *{stage_label}* — {cash_stage.get('name') or ''}. "
        f"{_full_sentence(cash_stage.get('recommendation') or '', max_len=280)} "
        f"({_full_sentence(cash_stage.get('reason') or '', max_len=200)})"
    )
    lines.append("")

    # ── 3. Allocation & concentration ────────────────────────────────────
    lines.append("📐 *3. Allocation & concentration*")
    if top:
        top_s = ", ".join(f"{t['symbol']} {t['weight_pct']:.1f}%" for t in top[:10])
        lines.append(f"Top weights (book-aggregated): {top_s}.")
    heavy = [t for t in top if t["weight_pct"] >= 12.0]
    if heavy:
        lines.append(
            "Names ≥12%: "
            + ", ".join(
                f"{t['symbol']} {t['weight_pct']:.1f}% "
                f"(fire distance {_fmt_pct(t['weight_pct'] - conc_fire, signed=True)})"
                for t in heavy
            )
            + "."
        )
    else:
        lines.append(f"No book names at or above 12% (max_name {max_name:.0f}%).")
    if schd_w is not None:
        lines.append(
            f"SCHD book {_fmt_pct(schd_w)} vs fire ≈{conc_fire:.1f}% "
            f"(distance {_fmt_pct((schd_w - conc_fire), signed=True)})."
        )
    if sector_posture:
        tb = sector_posture.get("tilt_book_pct") or {}
        lines.append(
            f"Sector tilt: defensive ≈{tb.get('DEFENSIVE', 0):.1f}% · "
            f"offensive/cyclical ≈{tb.get('OFFENSIVE', 0):.1f}% · "
            f"unclassified ≈{tb.get('UNCLASSIFIED', 0):.1f}% "
            f"(quality={sector_posture.get('quality') or '—'})."
        )
        top3 = sector_posture.get("top3") or []
        if top3:
            lines.append(
                "Largest sectors: "
                + ", ".join(f"{x['sector']} {x['weight_pct']}%" for x in top3[:4])
                + "."
            )
    else:
        lines.append("Sector posture DATA_UNAVAILABLE.")
    lines.append("")

    # ── 4. Material situations — ONE integrated narrative ────────────────
    lines.append("📍 *4. Material situations (integrated)*")
    story = []
    story.append(
        f"The live book story under `{pin}` is not three separate cards — it is one posture: "
        f"cash {_fmt_pct(cash_pct)} creates optionality while quality={quality} and {stage_label} "
        f"block force-deploy; concentration risk is dominated by SCHD at {_fmt_pct(schd_w)}; "
        f"and SPCX deep drawdown is an awareness sleeve at "
        f"{_fmt_pct(spcx_meta.get('book_weight_pct') or spcx_meta.get('weight_pct'))} weight."
    )
    if cash_pct is not None and cash_pct >= cash_band:
        story.append(
            f"Cash sits {_fmt_pct(cash_gap, signed=True) if cash_gap is not None else 'above'} "
            f"the {cash_band:.0f}% band ({_fmt_usd(total_cash)} on {_fmt_usd(total_value)}). "
            f"Under defensive_observe that is intentional dry powder: the desk holds/stages "
            f"rather than chasing band optics. Interaction: high cash *reduces* pressure to "
            f"trim winners solely for rebalance theater — size review still applies near fire."
        )
    if schd_w is not None:
        if schd_prior:
            story.append(
                f"SCHD concentration is real (book {_fmt_pct(schd_w)} near fire ≈{conc_fire:.1f}%), "
                f"but the operator already deferred with '{schd_prior}'. "
                f"That disposition is a hard constraint: primary path is HOLD / wait for price buffer, "
                f"not trim-into-weakness, unless weight sustainably breaches fire without buffer thesis "
                f"or the operator revisits the defer. Cash abundance does not authorize auto-trim of SCHD."
            )
        else:
            story.append(
                f"SCHD book {_fmt_pct(schd_w)} vs fire ≈{conc_fire:.1f}% warrants size-watch under "
                f"{pin}; no SCHD defer on file this pass — still prefer thesis-aware hold over force dispose."
            )
    if spcx_meta.get("dd_from_basis_pct") is not None or any(
        "SPCX" in [str(s).upper() for s in (p.get("symbols") or [])] for p in focus
    ):
        story.append(
            f"SPCX lifecycle: last={spcx_meta.get('last') if spcx_meta.get('last') is not None else 'DATA_UNAVAILABLE'}, "
            f"basis={spcx_meta.get('basis') if spcx_meta.get('basis') is not None else 'DATA_UNAVAILABLE'}, "
            f"DD from basis {_fmt_pct(spcx_meta.get('dd_from_basis_pct'))} "
            f"(deep-DD threshold {deep_dd:.0f}%). "
            f"Because weight is only "
            f"{_fmt_pct(spcx_meta.get('book_weight_pct') or spcx_meta.get('weight_pct'))}, "
            f"severity is awareness-only: escalate for judgment, keep hold / stop-above-BE / trim as "
            f"*options*, never auto-execute. Interaction with cash: small sleeve + low heat "
            f"({_fmt_pct(heat)}) means SPCX does not compete with SCHD size policy for operator attention."
        )
    # Catalyst / technicals one-liners for focus names
    for sym in ("SCHD", "SPCX"):
        cat = cat_by.get(sym) or {}
        tech = tech_by.get(sym) or {}
        ne = cat.get("next_event") if isinstance(cat.get("next_event"), dict) else None
        cat_s = (
            f"next {ne.get('kind')} {ne.get('session_date')} ({ne.get('severity')})"
            if ne and ne.get("session_date")
            else (cat.get("quality") or cat.get("quality_state") or "DATA_UNAVAILABLE")
        )
        tech_s = (
            f"RSI={tech.get('rsi')}"
            if tech.get("rsi") is not None
            else (tech.get("quality") or "DATA_UNAVAILABLE")
        )
        story.append(f"{sym} micro-context: catalyst {cat_s}; technicals {tech_s}.")
    lines.append(_full_sentence(" ".join(story), max_len=2400))
    if focus:
        lines.append("Open material plan anchors (context, not siloed essays):")
        for p in focus[:5]:
            st = (p.get("situation_type") or "").replace("_", " ")
            syms = ",".join(p.get("symbols") or []) or "book"
            fire = ", ".join(str(x) for x in (p.get("fire_reasons") or [])[:3])
            lines.append(f"• {st} · {syms} · fire={fire or '—'} · `{p.get('plan_id')}`")
    else:
        lines.append("No open material plans after desk filters (book memo still governs from live state).")
    lines.append("")

    # ── 5. What we are doing and why ─────────────────────────────────────
    lines.append(f"✅ *5. What we are doing and why* (under `{pin}`)")
    n = 1
    if cash_pct is not None and cash_pct >= cash_band:
        lines.append(
            f"{n}. *HOLD / STAGE cash* (high conviction) — {_fmt_pct(cash_pct)} ≫ band {cash_band:.0f}%. "
            f"{stage_label}: {_full_sentence(cash_stage.get('recommendation') or 'paper plan only', max_len=200)}. "
            f"Non-action is first-class: we are *choosing* optionality while data_quality={quality}."
        )
        n += 1
    if schd_w is not None and schd_w >= max_name * 0.7:
        if schd_prior:
            lines.append(
                f"{n}. *HOLD SCHD — disposition-bound* (high conviction on non-trim) — {schd_prior}. "
                f"Book {_fmt_pct(schd_w)} vs fire ≈{conc_fire:.1f}%. "
                f"Primary: HOLD / wait for price buffer. Override only with explicit new evidence language "
                f"(sustained ≥ fire without buffer thesis, or operator revisits defer)."
            )
        else:
            lines.append(
                f"{n}. *HOLD SCHD with size-watch* (medium conviction) — book {_fmt_pct(schd_w)} "
                f"vs fire ≈{conc_fire:.1f}%. Prefer thesis-aware hold over force dispose."
            )
        n += 1
    if any("SPCX" in [str(s).upper() for s in (p.get("symbols") or [])] for p in focus) or spcx_meta.get(
        "dd_from_basis_pct"
    ):
        lines.append(
            f"{n}. *HOLD SPCX lifecycle / awareness* (medium conviction on observe) — "
            + (f"{spcx_prior}. " if spcx_prior else "")
            + f"DD {_fmt_pct(spcx_meta.get('dd_from_basis_pct'))} is material as path signal; "
            f"weight {_fmt_pct(spcx_meta.get('book_weight_pct') or spcx_meta.get('weight_pct'))} keeps "
            f"portfolio impact small. Options (hold / stop-above-BE once reclaimed / trim) stay operator-owned."
        )
        n += 1
    # Re-entry brief
    core_cards = reentry.get("core_cards") or [
        c for c in (reentry.get("cards") or []) if c.get("tier") in (None, "core")
    ]
    conf_ready = [
        c
        for c in core_cards
        if c.get("confirmations_complete")
        and c.get("state") in ("READY TO REVIEW", "NEAR ENTRY")
        and isinstance(c.get("rr"), (int, float))
        and float(c.get("rr")) >= 1.5
    ]
    if conf_ready and int(cash_stage.get("stage") or 0) >= 1:
        c0 = conf_ready[0]
        lines.append(
            f"{n}. *Re-entry watch (not buy-now)* — {c0.get('symbol')} {c0.get('state')} "
            f"R:R {c0.get('rr')} under {stage_label}: "
            f"{_full_sentence(c0.get('stage_gate') or 'watch only', max_len=160)}. "
            "No buy-now language."
        )
    else:
        lines.append(
            f"{n}. *Re-entry book* — No STAGE-eligible core name with R:R≥1.5 and complete "
            f"confirmations under {stage_label} (core_full={reentry.get('core_full')}, "
            f"sub_rr={reentry.get('sub_rr')}). Watch-only; no buy-now language."
        )
    n += 1
    lines.append(
        f"{n}. *ESCALATE to operator* if cash moves ≥3pp, SCHD book weight ≥{conc_fire:.1f}%, "
        f"SPCX makes new lows vs basis, or a re-entry card flips READY with confirmations complete."
    )
    lines.append("All recommendations remain READ_ONLY_ADVISORY — no orders or stops from this memo.")
    lines.append("")

    # ── 6. What would change the call ────────────────────────────────────
    lines.append("🔬 *6. What would change the call*")
    lines.append(
        _full_sentence(
            f"Cash — Advance beyond {stage_label} only if: (1) total_cash/total_value quality OK "
            f"(not PARTIAL), (2) a named READY candidate with confirmations_complete and R:R≥1.5, "
            f"(3) post-deploy weight < max_name {max_name:.0f}% and sector posture not worsened unchecked, "
            f"(4) operator acks a plan_id / stage opt-in. Until then HOLD cash at {_fmt_pct(cash_pct)} "
            f"({_fmt_usd(total_cash)} on {_fmt_usd(total_value)}).",
            max_len=900,
        )
    )
    lines.append(
        _full_sentence(
            f"SCHD — What changes HOLD: (a) operator revisits/rejects the defer, "
            f"(b) book weight sustainably ≥ fire ≈{conc_fire:.1f}% with no buffer thesis, "
            f"(c) dividend/credit thesis break. What does *not*: routine day moves or account-scoped % "
            f"that disagree with book weight. Active disposition: "
            f"{schd_prior or 'none on file'}.",
            max_len=900,
        )
    )
    lines.append(
        _full_sentence(
            f"SPCX — What upgrades priority: book weight rising into max_name band, high-severity catalyst "
            f"≤5 sessions, or operator Hermes request. What keeps quiet: small sleeve + heat "
            f"{_fmt_pct(heat)}. DD threshold {deep_dd:.0f}% is already in view as awareness.",
            max_len=700,
        )
    )
    lines.append(
        "Quality flip — any domain that was OK → DATA_UNAVAILABLE on cash totals freezes stage advance."
    )
    lines.append("")

    # ── 7. Research agenda (Hermes) ──────────────────────────────────────
    lines.append("🔬 *7. Research agenda*")
    agenda: list[str] = []
    hermes_by = spine.get("hermes_by_plan") or {}
    open_jobs = []
    for pid, h in hermes_by.items():
        ref = (h or {}).get("ref") or {}
        for oid in ref.get("open_research_ids") or []:
            open_jobs.append(f"{oid} (plan {pid})")
        if ref.get("quality_state") == "OK" and ref.get("summary"):
            agenda.append(
                f"Ingested: plan `{pid}` result `{ref.get('result_id')}` — "
                f"{_full_sentence(ref.get('summary'), max_len=200)}"
            )
    if schd_w is not None and schd_w >= max_name:
        agenda.append(
            "Commission / keep warm: SCHD catalyst_map + invalidation levels under hold_with_thesis "
            "while defer is active (does calendar force size-review language?)."
        )
    if spcx_meta.get("dd_from_basis_pct") is not None and float(spcx_meta.get("dd_from_basis_pct") or 0) >= deep_dd * 0.8:
        agenda.append(
            "Commission / keep warm: SPCX multi-domain thesis check — what would upgrade awareness-only "
            "to size-review; cite calendar + technicals without inventing targets."
        )
    if cash_pct is not None and cash_pct >= cash_band + 10:
        agenda.append(
            "S5 research gap: deployment candidates with multi-domain support *without* force-fill; "
            "regime fit for first stage slice only when quality OK."
        )
    if not agenda:
        agenda.append("No urgent Hermes commissions; maintain observe. Gaps listed in evidence map.")
    for a in agenda[:6]:
        lines.append(f"• {_full_sentence(a, max_len=320)}")
    if open_jobs:
        lines.append("Open Hermes jobs: " + ", ".join(open_jobs[:6]) + ".")
    lines.append(
        "Fingerprint de-dupe + TTL reuse apply; Telegram only on material change — not on pure re-ask."
    )
    lines.append("")

    # ── 8. Operator loop ─────────────────────────────────────────────────
    lines.append("👤 *8. Operator loop*")
    if schd_prior or spcx_prior:
        if schd_prior:
            lines.append(f"• Active disposition SCHD: {schd_prior} (hard constraint on recs).")
        if spcx_prior:
            lines.append(f"• Active disposition SPCX: {spcx_prior}.")
    else:
        lines.append("• No SCHD/SPCX dispositions matched this pass (check learning store for others).")
    biased = []
    focus_syms = {"SCHD", "SPCX"}
    for p in focus:
        for s in p.get("symbols") or []:
            focus_syms.add(str(s).upper())
    for L in learning:
        Lsyms = {str(s).upper() for s in (L.get("symbols") or [])}
        if Lsyms & focus_syms or str(L.get("disposition") or "").lower() in ("defer", "reject"):
            biased.append(L)
    for L in biased[:5]:
        lines.append(
            f"• {L.get('disposition')} · {','.join(L.get('symbols') or []) or '—'} · "
            f"{_full_sentence(L.get('note') or '', max_len=100)} · "
            f"plan `{L.get('plan_id') or '—'}` · pin {L.get('thesis_version') or '—'}"
        )
    plan_ids = [p.get("plan_id") for p in focus if p.get("plan_id")]
    if plan_ids:
        lines.append("Plans: " + " · ".join(f"`{x}`" for x in plan_ids[:8]))
        lines.append("Ack path: `/cio ack <plan_id>` or reply `ack` on Telegram CIO thread.")
    else:
        lines.append("No material plan_ids in focus set this pass.")
    lines.append(
        f"Revisit: 24h, or earlier on cash ±3pp, SCHD ≥{conc_fire:.1f}%, SPCX new lows vs basis, "
        "or READY re-entry with confirmations complete."
    )
    lines.append(f"Thesis: `/cio thesis` ({pin})")
    lines.append("")

    # ── 9. Evidence map ──────────────────────────────────────────────────
    lines.append("📎 *9. Evidence map*")
    for row in evidence_map_lines(spine)[:16]:
        lines.append(f"• {row}")
    if not spine:
        lines.append("• evidence_spine missing — portfolio/cash/risk from collect_desk_inputs only.")
    lines.append("Material numbers above are grounded in Data Broker / thesis / learning or labeled DATA_UNAVAILABLE.")
    lines.append("No orders/stops from chat · READ_ONLY_ADVISORY")
    return "\n".join(lines)


def render_memo_spine_telegram(data: Optional[dict[str, Any]] = None) -> str:
    """Short Telegram default: exec thesis + 3 material points + recs + links."""
    d = data or collect_desk_inputs()
    pin = d.get("pin") or "desk@?"
    th = d.get("thesis") or {}
    thr = d.get("thresholds") or {}
    port = d.get("portfolio") or {}
    learning = d.get("learning") or []
    cash_stage = d.get("cash_stage") or {}
    stance = th.get("stance") or "defensive_observe"
    cash_band = float(thr.get("cash_band_min_pct") or 20)
    conc_fire = float(thr.get("concentration_fire_pct") or 16.5)
    cash_pct = port.get("cash_pct")
    schd_w = port.get("schd_weight_pct")
    spcx = port.get("spcx") or {}
    try:
        try:
            from lib.cio_desk_depth import active_disposition_phrase  # type: ignore
        except Exception:
            from scripts.lib.cio_desk_depth import active_disposition_phrase  # type: ignore
    except Exception:
        def active_disposition_phrase(learning, symbols):  # type: ignore
            return None
    schd_prior = active_disposition_phrase(learning, ["SCHD"])
    lines = [
        f"🏦 *CIO memo spine* · `{pin}` · {stance} · READ_ONLY",
        _full_sentence(th.get("summary") or f"{pin} governs observe/stage.", max_len=320),
        "────────────────",
        f"1) Cash {_fmt_pct(cash_pct)} vs band {cash_band:.0f}% · "
        f"{cash_stage.get('label') or 'STAGE_?'} · {_fmt_usd(port.get('total_cash'))} / {_fmt_usd(port.get('total_value'))}",
        f"2) SCHD {_fmt_pct(schd_w)} vs fire ≈{conc_fire:.1f}% · "
        + (f"{schd_prior}" if schd_prior else "size-watch"),
        f"3) SPCX weight {_fmt_pct(spcx.get('book_weight_pct'))} · "
        f"DD {_fmt_pct(spcx.get('dd_from_basis_pct'))} · awareness-only",
        "────────────────",
        f"*Recs:* HOLD/STAGE cash · HOLD SCHD"
        + (" (defer bound)" if schd_prior else "")
        + " · HOLD SPCX observe · no buy-now.",
        "Full memo: `/v3/cio` desk note · plans via `/cio plans`",
        "No orders/stops · READ_ONLY_ADVISORY",
    ]
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
    """Return structured payload + rendered institutional memo (CLI = API)."""
    data = collect_desk_inputs()
    note = render_desk_note(data, telegram=False)
    note_tg = render_desk_note(data, telegram=True)
    spine_tg = render_memo_spine_telegram(data)
    sample = None
    for p in data.get("material_plans") or []:
        if p.get("plan_id") == "plan_79fe9e72f2d4":
            sample = p
            break
    if sample is None and data.get("material_plans"):
        sample = data["material_plans"][0]
    contrast = render_situation_card_contrast(sample) if sample else "(no plan)"

    # Side-by-side: legacy thin cards vs integrated memo spine
    thin_cards = []
    for p in (data.get("material_plans") or [])[:3]:
        st = str(p.get("situation_type") or "")
        if st.startswith(("S5", "S6", "S1")):
            thin_cards.append(render_situation_card_contrast(p))
    before_after = {
        "legacy_s_cards": "\n\n".join(thin_cards) if thin_cards else "(no S5/S6/S1 open)",
        "memo_spine": spine_tg,
    }

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
        f"{prior} Primary under {data.get('pin')}: HOLD / wait for price buffer — not trim/dispose — "
        "while defer is active and no stronger rule breach."
        if prior
        else schd_before + " (no SCHD disposition on file)"
    )

    port = data.get("portfolio") or {}
    spine = data.get("evidence_spine") or {}
    return {
        "ok": True,
        "as_of": data.get("as_of"),
        "thesis_version": data.get("pin"),
        "version": "desk-note-v1.3.0",
        "portfolio": {
            k: port.get(k)
            for k in (
                "total_value", "total_cash", "cash_pct", "day_change_pct",
                "holdings_count", "heat_pct", "stops_active", "top_weights",
                "data_quality", "schd_weight_pct", "spcx",
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
            "core_full": (data.get("reentry_book") or {}).get("core_full"),
            "sub_rr": (data.get("reentry_book") or {}).get("sub_rr"),
            "micro_count": (data.get("reentry_book") or {}).get("micro_count"),
            "dropped_bad_rr": (data.get("reentry_book") or {}).get("dropped_bad_rr"),
            "core_count": (data.get("reentry_book") or {}).get("core_count"),
            "has_stage_eligible_core": (data.get("reentry_book") or {}).get("has_stage_eligible_core"),
            "cards": (data.get("reentry_book") or {}).get("cards") or [],
            "core_cards": (data.get("reentry_book") or {}).get("core_cards") or [],
            "error": (data.get("reentry_book") or {}).get("error"),
        },
        "evidence_spine": {
            "domains_present": spine.get("domains_present"),
            "gaps": spine.get("gaps"),
            "focus_symbols": spine.get("focus_symbols"),
            "name_meta": spine.get("name_meta"),
            "catalyst_summary": {
                s: {
                    "quality": (p or {}).get("quality") or (p or {}).get("quality_state"),
                    "max_severity": (p or {}).get("max_severity"),
                    "next": (p or {}).get("next_event"),
                }
                for s, p in (spine.get("catalyst_by_symbol") or {}).items()
            },
            "technicals_summary": {
                s: {"rsi": t.get("rsi"), "quality": t.get("quality")}
                for s, t in (spine.get("technicals_by_symbol") or {}).items()
            },
        },
        "note": note,
        "note_telegram": note_tg,
        "memo_spine_telegram": spine_tg,
        "contrast_card": contrast,
        "before_after": before_after,
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
    print("\n======== TELEGRAM SPINE ========\n")
    print(out.get("memo_spine_telegram"))
    print("\n======== BEFORE (legacy S-cards) ========\n")
    ba = out.get("before_after") or {}
    print(ba.get("legacy_s_cards") or "(none)")
    print("\n======== AFTER (memo spine) ========\n")
    print(ba.get("memo_spine") or "")
    print("\n======== SCHD DISPOSITION ========\n")
    demo = out.get("schd_disposition_demo") or {}
    print("BEFORE:", demo.get("before"))
    print("AFTER:", demo.get("after"))
    print("\n--- portfolio ---")
    print(out.get("portfolio"))
    print("--- cash_stage ---")
    print(out.get("cash_stage"))
    print("--- evidence spine domains ---")
    print((out.get("evidence_spine") or {}).get("domains_present"))
    print("--- catalyst ---")
    print((out.get("evidence_spine") or {}).get("catalyst_summary"))
    print("--- technicals ---")
    print((out.get("evidence_spine") or {}).get("technicals_summary"))
    rb = out.get("reentry_book") or {}
    print("--- reentry counts ---")
    print(
        "core_full", rb.get("core_full"),
        "sub_rr", rb.get("sub_rr"),
        "micro", rb.get("micro_count"),
        "dropped_bad_rr", rb.get("dropped_bad_rr"),
    )
    for c in rb.get("core_cards") or []:
        print("CORE_FULL", c.get("symbol"), c.get("state"), "rr", c.get("rr"), (c.get("stage_gate") or "")[:50])
        assert c.get("rr") is None or float(c.get("rr")) >= 1.5, c
    # Persist latest full memo + spine
    try:
        root = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
        for r in _candidate_project_roots():
            if (r / "data" / "cio").exists():
                root = r
                break
        out_path = root / "data" / "cio" / "cio_desk_note_latest.md"
        spine_path = root / "data" / "cio" / "cio_desk_memo_spine_latest.md"
        out_path.write_text(note + "\n", encoding="utf-8")
        spine_path.write_text((out.get("memo_spine_telegram") or "") + "\n", encoding="utf-8")
        print(f"\n[wrote {out_path}]")
        print(f"[wrote {spine_path}]")
    except Exception as e:
        print(f"[persist skipped: {e}]")
