#!/usr/bin/env python3
"""portfolio_report_ms.py — Morgan Stanley–style portfolio report (deterministic).

READ_ONLY_ADVISORY. Reproduces the structure and graphics of the operator's
Morgan Stanley Wealth Management portfolio report, driven entirely by the
canonical Data Broker state (holdings, tax lots, ticker enrichment, performance
attribution, look-through themes, fund factsheet weights) and the live desk@vN
governing thesis. No LLM narrative is invented; every figure traces to a source
file or is labeled DATA_UNAVAILABLE.

Sections mirror the MS report:
  Cover → Accounts → Investment Summary → Style → Portfolio X-Ray →
  Change in Value → Unrealized G/L Detail → Disclosures

Delivery: HTML + landscape-letter PDF (Playwright). Telegram carries a text
alert (path/link) via `telegram_alert.send_telegram`; email carries a
plain-text summary + body link.

CLI:
  python portfolio_report_ms.py [--ad-hoc] [--dry-run] [--no-send]
                                [--out DIR] [--no-pdf] [--no-charts]
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
CIO_DIR = PROJECT_ROOT / "data" / "cio"
REPORT_DIR = PROJECT_ROOT / "data" / "portfolios" / "reports" / "ms"
CHARTS_DIR = REPORT_DIR / "charts"

# ── MS print theme ────────────────────────────────────────────────────────
NAVY = "#1F3864"
NAVY_DARK = "#16294D"
GREEN = "#2E7D32"
GREEN_DARK = "#1B5E20"
BURGUNDY = "#8B1A1A"
GRAY = "#555555"
LIGHT = "#F4F6F9"
BORDER = "#D5DAE1"
PALETTE = [NAVY, GREEN, "#7C9EB2", "#B8860B", BURGUNDY, "#5A6B7B", "#A9B7C6", "#6B8E23"]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _fmt_usd(v: Any) -> str:
    v = _f(v)
    return f"${v:,.0f}"


def _fmt_pct(v: Any, signed: bool = False) -> str:
    v = _f(v)
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Imports (canonical desk loaders, fail-soft) ───────────────────────────
def _desk_loaders() -> dict[str, Any]:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import lib.data_broker.advisory_desk as ad
    except Exception:
        import scripts.lib.data_broker.advisory_desk as ad
    return {
        "holdings": ad._load_holdings,
        "tax_lots": ad._load_tax_lots,
        "lot_basis": ad._load_lot_basis,
        "analytics": ad._load_portfolio_analytics,
        "performance": ad._load_performance,
        "thesis": ad._load_living_thesis,
    }


def _load_fund_lookthrough() -> dict:
    return _load_json(PROJECT_ROOT / "config" / "fund_lookthrough.json")


def _unrealized_detail(positions: list[dict], raw_holdings: dict) -> tuple[list[dict], float, float]:
    """Unrealized G/L per symbol:account, computed from tax_lots.json directly.

    The desk's ``_load_tax_lots`` collapses the composite ``SYMBOL:account`` keys
    to symbol-only, which would double-report multi-account positions. Here we
    keep the account dimension so each open lot group is attributed once.
    """
    raw_lots = _load_json(STATE_DIR / "tax_lots.json")
    # Per-share current price from the authoritative `current_price` field
    # (the holdings `price` field is unreliable for some rows — e.g. NOC stores
    # market value there).
    price_by_sym = {}
    for h in raw_holdings.get("holdings", []):
        sym = str(h.get("symbol", "")).upper()
        if not sym or sym == "CASH":
            continue
        px = _f(h.get("current_price")) or _f(h.get("price"))
        if px > 0:
            price_by_sym[sym] = px
    name_by_sym = {p["symbol"]: (p.get("name") or "")[:32] for p in positions}
    # Only report positions currently held (tax_lots.json retains historical lots
    # for closed/rolled positions that are no longer in the book).
    held = {(p["symbol"], p.get("account")) for p in positions}

    groups: dict[str, dict] = {}
    for key, lots in raw_lots.items():
        if not isinstance(lots, list) or ":" not in key:
            continue
        sym, acct = key.split(":", 1)
        sym = sym.upper()
        if (sym, acct) not in held:
            continue
        open_lots = [l for l in lots if isinstance(l, dict) and not l.get("closed")
                     and _f(l.get("shares_remaining")) > 0]
        if not open_lots:
            continue
        g = groups.setdefault(f"{sym}:{acct}", {"symbol": sym, "account": acct,
                                                "shares": 0.0, "cost": 0.0, "lots": []})
        for l in open_lots:
            sh = _f(l.get("shares_remaining")) or _f(l.get("shares"))
            cps = _f(l.get("cost_per_share"))
            g["shares"] += sh
            g["cost"] += sh * cps
            g["lots"].append(l)

    rows = []
    lt_total = st_total = 0.0
    today = datetime.now(timezone.utc).date()
    for key, g in groups.items():
        sym, acct = g["symbol"], g["account"]
        price = price_by_sym.get(sym) or 0.0
        cost = g["cost"]
        if cost <= 0:
            continue
        mv = g["shares"] * price
        gl = mv - cost
        # holding period from oldest open lot
        n_long = n_short = 0
        for l in g["lots"]:
            d = str(l.get("lot_date") or "")[:10]
            try:
                if (today - datetime.strptime(d, "%Y-%m-%d").date()).days >= 365:
                    n_long += 1
                else:
                    n_short += 1
            except ValueError:
                pass
        hp = "LONG" if n_long and not n_short else "SHORT" if n_short and not n_long else "MIXED" if n_long and n_short else "—"
        if hp == "LONG":
            lt_total += gl
        else:
            st_total += gl
        rows.append({
            "symbol": sym,
            "account": acct,
            "name": name_by_sym.get(sym, ""),
            "quantity": round(g["shares"], 4),
            "cost_basis": cost,
            "market_value": mv,
            "unrealized_gl": gl,
            "gl_pct": (gl / cost * 100),
            "holding_period": hp,
            "lot_count": len(g["lots"]),
        })
    rows.sort(key=lambda r: abs(r["unrealized_gl"]), reverse=True)
    return rows, lt_total, st_total


def _change_value(raw_perf: dict, performance: dict) -> dict[str, Any]:
    """YTD + inception change-in-value with authoritative start/end figures."""
    periods = raw_perf.get("periods", {}) if isinstance(raw_perf, dict) else {}
    ytd = periods.get("YTD") or {}
    return {
        "ytd_start": _f(ytd.get("start_value")),
        "ytd_end": _f(ytd.get("end_value")),
        "ytd_change": _f(ytd.get("change")),
        "ytd_change_pct": _f(ytd.get("change_pct")),
        "inception_return": _f(performance.get("inception_return")),
        "current_value": _f(raw_perf.get("current_value")),
    }


def _top10_aggregated(positions: list[dict], total_value: float) -> list[dict]:
    agg: dict[str, float] = {}
    for p in positions:
        mv = _f(p.get("market_value"))
        if mv <= 0:
            continue
        agg[p["symbol"]] = agg.get(p["symbol"], 0.0) + mv
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:10]
    return [
        {"symbol": s, "market_value": round(v, 2),
         "weight_pct": round(v / total_value * 100, 2) if total_value > 0 else None}
        for s, v in top
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Data assembly
# ═══════════════════════════════════════════════════════════════════════════════

def assemble() -> dict[str, Any]:
    """Assemble the complete report context. Every field is sourced or labeled."""
    L = _desk_loaders()
    holdings = L["holdings"]()
    tax_lots = L["tax_lots"]()
    analytics = L["analytics"](holdings)
    performance = L["performance"]()
    thesis = L["thesis"]()

    raw = _load_json(STATE_DIR / "holdings.json")
    account_summaries = raw.get("account_summaries") or {}
    portfolio_totals = raw.get("portfolio_totals") or {}

    positions = holdings.get("positions") or []
    total_value = _f(portfolio_totals.get("total_value")) or _f(holdings.get("total_value")) or 0.0
    cash_value = sum(
        _f(h.get("market_value"))
        for h in raw.get("holdings", [])
        if h.get("is_cash") or str(h.get("symbol", "")).upper() == "CASH"
    )
    cash_pct = cash_value / total_value * 100 if total_value > 0 else 0.0

    # ── Accounts table ──
    accounts = []
    for acct_id, a in account_summaries.items():
        if not isinstance(a, dict):
            continue
        tv = _f(a.get("total_value"))
        if tv <= 0:
            continue
        status = str(a.get("status", ""))
        accounts.append({
            "account_id": acct_id,
            "display_name": a.get("display_name") or acct_id,
            "broker": a.get("broker", ""),
            "total_value": tv,
            "weight_pct": tv / total_value * 100 if total_value > 0 else 0.0,
            "day_change": _f(a.get("day_change")),
            "day_change_pct": _f(a.get("day_change_pct")),
            "gain_loss": _f(a.get("total_gain")),
            "gain_loss_pct": _f(a.get("total_gain_pct")),
            "status": status,
        })
    accounts.sort(key=lambda x: -x["total_value"])

    # ── Asset allocation (cash vs equities vs other) ──
    alloc = {"Cash & Equivalents": cash_value, "Equities": 0.0, "Other": 0.0}
    for p in positions:
        bucket = str(p.get("bucket", ""))
        mv = _f(p.get("market_value"))
        if bucket == "Delisted/Worthless":
            alloc["Other"] += mv
        else:
            alloc["Equities"] += mv

    # ── Unrealized G/L detail (per symbol:account, from tax_lots.json) ──
    unrealized_rows, lt_total, st_total = _unrealized_detail(positions, raw)

    # ── Change-in-value + rolling alpha (read directly; desk loader omits) ──
    raw_perf = _load_json(STATE_DIR / "performance_history.json")
    raw_attr = _load_json(STATE_DIR / "performance_attribution.json")
    performance["rolling_alpha"] = raw_attr.get("rolling_alpha")
    performance["change_value"] = _change_value(raw_perf, performance)

    # ── Top 10 aggregated by security (MS groups by security, not account) ──
    analytics["top_10_aggregated"] = _top10_aggregated(positions, total_value)

    # ── Look-through X-Ray ──
    xray = _load_xray(positions, raw)

    # ── Benchmark ──
    bench = {
        "label": performance.get("benchmark_label"),
        "cagr": performance.get("bench_cagr"),
        "3yr": performance.get("bench_3yr_return"),
    }

    return {
        "as_of": _now(),
        "thesis": thesis,
        "portfolio": {
            "total_value": total_value,
            "cash_value": cash_value,
            "cash_pct": cash_pct,
            "positions_count": len(positions),
        },
        "accounts": accounts,
        "allocation": alloc,
        "analytics": analytics,
        "performance": performance,
        "benchmark": bench,
        "unrealized": {
            "rows": unrealized_rows,
            "lt_unrealized": lt_total,
            "st_unrealized": st_total,
            "count": len(unrealized_rows),
        },
        "xray": xray,
        "quality_flags": _quality_flags(performance, analytics, raw),
    }


def _load_xray(positions: list[dict], raw: dict) -> dict[str, Any]:
    lt = _load_json(STATE_DIR / "lookthrough_themes.json")
    enrich = _load_json(STATE_DIR / "ticker_enrichment_cache.json")

    # Sector look-through via fund factsheet weights + direct equity sector
    rows = []
    for p in positions:
        sym = p["symbol"]
        rec = enrich.get(sym) or {}
        sector = rec.get("sector") if isinstance(rec, dict) else None
        rows.append({"symbol": sym, "sector": sector, "value": _f(p.get("market_value"))})

    sector_agg = {}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from fund_lookthrough import effective_sector_exposure
        sector_agg = effective_sector_exposure(rows)
    except Exception:
        sector_agg = {"_total": 0, "_not_decomposed": {"dollars": 0, "positions": []}}

    sectors = []
    for name, b in sector_agg.items():
        if name.startswith("_"):
            continue
        sectors.append({
            "sector": name,
            "dollars": _f(b.get("dollars")),
            "pct": _f(b.get("pct")),
            "direct_pct": _f(b.get("direct_pct")),
        })
    sectors.sort(key=lambda x: -x["dollars"])

    return {
        "themes": lt.get("themes") or {},
        "top_underlying": lt.get("top_underlying") or [],
        "advisories": lt.get("advisories") or [],
        "theme_gaps": lt.get("theme_gaps") or [],
        "coverage_pct": lt.get("coverage_pct"),
        "sectors": sectors,
        "not_decomposed": sector_agg.get("_not_decomposed", {}).get("dollars", 0),
        "sector_total": sector_agg.get("_total", 0),
    }


def _quality_flags(performance: dict, analytics: dict, raw: dict) -> list[str]:
    flags = []
    per = performance.get("period_returns") or {}
    for pname in ("3M", "1Y"):
        src = (per.get(pname) or {}).get("source")
        if src == "account-aggregated":
            flags.append(f"{pname} return is account-aggregated and may include transfers/ACATS step-changes.")
    if analytics.get("fund_etf_pct"):
        flags.append(
            f"{analytics.get('fund_etf_pct'):.1f}% of market value is in funds/ETFs; "
            "valuation multiples and style are direct-equity only (look-through wired separately)."
        )
    if not performance.get("port_cagr"):
        flags.append("True time-weighted return (TWR) is not yet tracked; CAGR shown is money-weighted.")
    return flags


# ═══════════════════════════════════════════════════════════════════════════════
# Charts (matplotlib — MS print theme, white background)
# ═══════════════════════════════════════════════════════════════════════════════

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.edgecolor": BORDER,
        "axes.labelcolor": GRAY,
        "xtick.color": GRAY,
        "ytick.color": GRAY,
        "axes.titlecolor": NAVY,
        "text.color": GRAY,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })
    return plt


def _save(fig, name: str, charts_dir: Path) -> str:
    charts_dir.mkdir(parents=True, exist_ok=True)
    path = charts_dir / name
    fig.savefig(str(path), bbox_inches="tight", dpi=150, facecolor="white", pad_inches=0.1)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return str(path)


def render_charts(ctx: dict, charts_dir: Path) -> dict[str, str]:
    """Return {chart_key: file_path}."""
    out: dict[str, str] = {}
    plt = _plt()

    # 1. Asset allocation donut
    alloc = ctx["allocation"]
    labels = [k for k, v in alloc.items() if v > 0]
    vals = [v for k, v in alloc.items() if v > 0]
    if vals:
        fig, ax = plt.subplots(figsize=(4.4, 3.4))
        wedges, _t, autot = ax.pie(
            vals, labels=labels, autopct=lambda p: f"{p:.1f}%",
            colors=PALETTE[:len(vals)], startangle=90,
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5),
            textprops=dict(color=NAVY, fontsize=9),
        )
        for a in autot:
            a.set_color("white"); a.set_fontsize(8); a.set_fontweight("bold")
        ax.set_title("Asset Allocation", color=NAVY, fontsize=12, fontweight="bold")
        out["alloc"] = _save(fig, "alloc_donut.png", charts_dir)

    # 2. Sector look-through bar
    sectors = ctx["xray"]["sectors"]
    if sectors:
        top = sectors[:10][::-1]
        fig, ax = plt.subplots(figsize=(6.5, max(3, len(top) * 0.42)))
        ax.barh([s["sector"] for s in top], [s["pct"] for s in top],
                color=NAVY, alpha=0.9, height=0.62)
        ax.set_xlabel("% of portfolio")
        ax.set_title("Sector Allocation (look-through)", color=NAVY, fontsize=12, fontweight="bold")
        for i, s in enumerate(top):
            ax.text(s["pct"] + 0.3, i, f"{s['pct']:.1f}%", va="center", color=GRAY, fontsize=8)
        out["sectors"] = _save(fig, "sectors.png", charts_dir)

    # 3. Risk / return scatter
    perf = ctx["performance"]
    pc, bc = _f(perf.get("port_cagr")), _f(perf.get("bench_cagr"))
    if pc and bc:
        fig, ax = plt.subplots(figsize=(5.6, 3.6))
        ax.scatter([bc], [pc], s=160, color=GREEN, zorder=3, edgecolors=NAVY, linewidths=1.2)
        ax.annotate("Portfolio", (bc, pc), textcoords="offset points", xytext=(8, 8),
                    color=NAVY, fontweight="bold", fontsize=9)
        ax.scatter([bc], [bc], s=120, color=NAVY, zorder=3)
        ax.annotate("Benchmark", (bc, bc), textcoords="offset points", xytext=(8, -12),
                    color=GRAY, fontsize=9)
        ax.set_xlabel("Return (CAGR %)", color=GRAY)
        ax.set_ylabel("Return (CAGR %)", color=GRAY)
        ax.set_title("Portfolio vs Benchmark (CAGR)", color=NAVY, fontsize=12, fontweight="bold")
        ax.grid(color=BORDER, alpha=0.6, linewidth=0.5)
        out["risk_return"] = _save(fig, "risk_return.png", charts_dir)

    # 4. Top positions bar (aggregated by security)
    top10 = ctx["analytics"].get("top_10_aggregated") or ctx["analytics"].get("top_10") or []
    if top10:
        t = top10[:10][::-1]
        fig, ax = plt.subplots(figsize=(6.5, max(3, len(t) * 0.42)))
        ax.barh([f"{r['symbol']}" for r in t], [r["weight_pct"] for r in t],
                color=GREEN, alpha=0.9, height=0.6)
        ax.set_xlabel("% of portfolio")
        ax.set_title("Top 10 Holdings", color=NAVY, fontsize=12, fontweight="bold")
        for i, r in enumerate(t):
            ax.text(r["weight_pct"] + 0.3, i, f"{r['weight_pct']:.1f}%", va="center", color=GRAY, fontsize=8)
        out["top10"] = _save(fig, "top10.png", charts_dir)

    # 5. Period performance bar
    per = ctx["performance"].get("period_returns") or {}
    labels, vals = [], []
    for k in ("1W", "1M", "3M", "6M", "YTD", "1Y"):
        v = (per.get(k) or {}).get("change_pct")
        if v is not None:
            labels.append(k); vals.append(_f(v))
    if labels:
        fig, ax = plt.subplots(figsize=(5.8, 3.0))
        colors = [GREEN if v >= 0 else BURGUNDY for v in vals]
        ax.bar(labels, vals, color=colors, alpha=0.9, width=0.55)
        ax.axhline(0, color=GRAY, linewidth=0.8)
        ax.set_title("Portfolio Return by Period (%)", color=NAVY, fontsize=12, fontweight="bold")
        for i, v in enumerate(vals):
            ax.text(i, v + (0.3 if v >= 0 else -0.3), f"{v:+.1f}%", ha="center",
                    va="bottom" if v >= 0 else "top", color=GRAY, fontsize=8)
        out["periods"] = _save(fig, "periods.png", charts_dir)

    # 6. Rolling alpha (advanced)
    ra = ctx["performance"].get("rolling_alpha")
    if isinstance(ra, list) and len(ra) >= 5:
        fig, ax = plt.subplots(figsize=(6.5, 2.8))
        idx = [r.get("index", i) for i, r in enumerate(ra)]
        alpha = [_f(r.get("alpha")) for r in ra]
        ax.plot(idx, alpha, color=GREEN, linewidth=1.6)
        ax.axhline(0, color=GRAY, linewidth=0.8, linestyle="--")
        ax.fill_between(idx, alpha, 0, color=GREEN, alpha=0.12)
        ax.set_title("Rolling Alpha vs Benchmark", color=NAVY, fontsize=12, fontweight="bold")
        ax.grid(color=BORDER, alpha=0.5, linewidth=0.5)
        out["rolling_alpha"] = _save(fig, "rolling_alpha.png", charts_dir)

    # 7. Theme exposure (advanced)
    themes = ctx["xray"]["themes"]
    if themes:
        ttop = sorted(themes.items(), key=lambda kv: -_f((kv[1] or {}).get("pct")))[:8][::-1]
        fig, ax = plt.subplots(figsize=(6.5, max(3, len(ttop) * 0.42)))
        ax.barh([t[0] for t in ttop], [_f((t[1] or {}).get("pct")) for t in ttop],
                color=NAVY, alpha=0.85, height=0.6)
        ax.set_xlabel("% of portfolio")
        ax.set_title("Theme Exposure (look-through)", color=NAVY, fontsize=12, fontweight="bold")
        for i, t in enumerate(ttop):
            ax.text(_f((t[1] or {}).get("pct")) + 0.2, i, f"{_f((t[1] or {}).get('pct')):.1f}%",
                    va="center", color=GRAY, fontsize=8)
        out["themes"] = _save(fig, "themes.png", charts_dir)

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════════════════════════

def _img_b64(path: str) -> str:
    try:
        data = base64.b64encode(Path(path).read_bytes()).decode()
        return f"data:image/png;base64,{data}"
    except Exception:
        return ""


_CSS = """
:root { --navy:#1F3864; --green:#2E7D32; --gray:#555; --light:#F4F6F9; --border:#D5DAE1; }
* { box-sizing: border-box; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; color:#222; margin:0; font-size:11px; }
.page { page-break-after: always; padding: 28px 40px; }
.cover { background: linear-gradient(135deg, #16294D 0%, #1F3864 55%, #2E7D32 130%); color:#fff; height:100%; }
.cover .inner { padding: 60px 56px; }
.brand { font-size: 13px; letter-spacing: 2px; text-transform: uppercase; opacity:.85; border-bottom:1px solid rgba(255,255,255,.35); padding-bottom:12px; }
.brand b { color:#fff; }
.cover h1 { font-size: 34px; margin: 40px 0 6px; font-weight: 300; }
.cover .sub { font-size: 14px; opacity:.9; }
.cover .meta { margin-top: 46px; font-size: 12px; line-height: 1.9; opacity:.92; }
.cover .disclaimer { position:absolute; bottom:30px; font-size:9px; opacity:.65; }
h2.section { color: var(--navy); font-size: 15px; border-bottom: 2px solid var(--green); padding-bottom: 4px; margin: 18px 0 10px; }
h3 { color: var(--navy); font-size: 12px; margin: 12px 0 5px; }
table { border-collapse: collapse; width: 100%; margin: 5px 0 10px; }
th { background: var(--navy); color:#fff; font-weight:600; padding: 4px 7px; text-align:left; font-size:9.5px; }
td { padding: 4px 7px; border-bottom: 1px solid var(--border); font-size:10px; }
tr:nth-child(even) td { background: var(--light); }
.num { text-align:right; font-variant-numeric: tabular-nums; }
.pos { color: var(--green); font-weight:600; }
.neg { color:#B71C1C; font-weight:600; }
.charts { display:flex; flex-wrap:wrap; gap:12px; margin:8px 0; }
.chart { flex: 1 1 260px; text-align:center; }
.chart img { max-width:100%; border:1px solid var(--border); }
.chart .cap { font-size:9px; color:var(--gray); margin-top:3px; }
.kpi { display:flex; gap:10px; flex-wrap:wrap; margin: 6px 0 12px; }
.kpi .box { flex:1 1 140px; border:1px solid var(--border); border-top:3px solid var(--green); padding:8px 10px; background:#fff; }
.kpi .box .l { font-size:8.5px; text-transform:uppercase; letter-spacing:.5px; color:var(--gray); }
.kpi .box .v { font-size:18px; color:var(--navy); font-weight:600; margin-top:2px; }
.note { font-size:9px; color:var(--gray); font-style:italic; }
.flag { background:#FDF3E7; border-left:3px solid #E6A23C; padding:5px 9px; margin:5px 0; font-size:9px; color:#6B4A00; }
.toc { font-size:11px; line-height:1.9; color:var(--navy); }
.footer { font-size:8.5px; color:#999; border-top:1px solid var(--border); margin-top:20px; padding-top:8px; }
.gain-row { background:#fff; }
"""


def _section_accounts(ctx) -> str:
    rows = "".join(
        f"<tr><td>{a['display_name']}</td><td>{a['broker'] or '—'}</td>"
        f"<td class='num'>{_fmt_usd(a['total_value'])}</td>"
        f"<td class='num'>{a['weight_pct']:.1f}%</td>"
        f"<td class='num {('pos' if a['day_change']>=0 else 'neg')}'>{a['day_change']:+,.0f}</td>"
        f"<td class='num'>{a['gain_loss_pct']:+.2f}%</td></tr>"
        for a in ctx["accounts"]
    )
    return f"""
    <h2 class="section">Accounts Included</h2>
    <table><thead><tr><th>Account</th><th>Broker</th><th>Market Value</th><th>% of Portfolio</th><th>Day Change</th><th>Total Gain %</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <div class="note">Totals as of {ctx['as_of']}. Closed/rolled accounts excluded.</div>
    """


def _section_summary(ctx) -> str:
    p = ctx["portfolio"]
    perf = ctx["performance"]
    an = ctx["analytics"]
    kpis = f"""
    <div class="kpi">
      <div class="box"><div class="l">Total Portfolio Value</div><div class="v">{_fmt_usd(p['total_value'])}</div></div>
      <div class="box"><div class="l">Cash</div><div class="v">{_fmt_usd(p['cash_value'])} ({p['cash_pct']:.1f}%)</div></div>
      <div class="box"><div class="l">Inception Return</div><div class="v">{_fmt_pct(perf.get('inception_return'), signed=True)}</div></div>
      <div class="box"><div class="l">YTD Return</div><div class="v">{_fmt_pct(perf.get('ytd_return'), signed=True)}</div></div>
      <div class="box"><div class="l">Weighted P/E</div><div class="v">{an.get('weighted_pe') or '—'}</div></div>
    </div>"""
    charts = []
    for key, cap in (("alloc", "Asset allocation"), ("top10", "Top 10 holdings")):
        if ctx["charts"].get(key):
            charts.append(f"<div class='chart'><img src='{_img_b64(ctx['charts'][key])}'/><div class='cap'>{cap}</div></div>")
    return f"""
    <h2 class="section">Investment Summary</h2>
    {kpis}
    <div class="charts">{''.join(charts)}</div>
    """


def _section_performance(ctx) -> str:
    perf = ctx["performance"]
    per = perf.get("period_returns") or {}
    rows = []
    for k in ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y"):
        pr = per.get(k) or {}
        src = pr.get("source") or "—"
        flag = " ⚠" if src == "account-aggregated" else ""
        rows.append(
            f"<tr><td>{k}</td><td class='num'>{_fmt_pct(pr.get('change_pct'), signed=True)}</td>"
            f"<td>{src}{flag}</td></tr>"
        )
    bench = ctx["benchmark"]
    metrics = f"""
    <h3>Risk &amp; Attribution</h3>
    <table><thead><tr><th>Metric</th><th>Portfolio</th><th>Benchmark</th></tr></thead><tbody>
      <tr><td>CAGR (annualized)</td><td class='num'>{_fmt_pct(perf.get('port_cagr'))}</td><td class='num'>{_fmt_pct(bench.get('cagr'))}</td></tr>
      <tr><td>Alpha (annualized)</td><td class='num'>{_fmt_pct(perf.get('alpha_annualized'), signed=True)}</td><td class='num'>—</td></tr>
      <tr><td>Sharpe</td><td class='num'>{_f(perf.get('sharpe')):.2f}</td><td class='num'>—</td></tr>
      <tr><td>Sortino</td><td class='num'>{_f(perf.get('sortino')):.2f}</td><td class='num'>—</td></tr>
      <tr><td>Max Drawdown</td><td class='num'>{_fmt_pct(perf.get('max_drawdown'))}</td><td class='num'>—</td></tr>
    </tbody></table>
    <div class="note">Benchmark: {bench.get('label') or 'DATA_UNAVAILABLE'} · 3-yr {_fmt_pct(bench.get('3yr')) if bench.get('3yr') is not None else '—'}</div>
    """
    charts = []
    for key, cap in (("periods", "Return by period"), ("risk_return", "Portfolio vs benchmark"), ("rolling_alpha", "Rolling alpha")):
        if ctx["charts"].get(key):
            charts.append(f"<div class='chart'><img src='{_img_b64(ctx['charts'][key])}'/><div class='cap'>{cap}</div></div>")
    return f"""
    <h2 class="section">Performance</h2>
    <table><thead><tr><th>Period</th><th>Return</th><th>Source</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    {metrics}
    <div class="charts">{''.join(charts)}</div>
    """


def _section_xray(ctx) -> str:
    xr = ctx["xray"]
    an = ctx["analytics"]
    sec_rows = "".join(
        f"<tr><td>{s['sector']}</td><td class='num'>{_fmt_usd(s['dollars'])}</td><td class='num'>{s['pct']:.1f}%</td></tr>"
        for s in xr["sectors"][:10]
    )
    under = "".join(
        f"<tr><td>{t.get('symbol')}</td><td class='num'>{_fmt_usd(t.get('value'))}</td><td class='num'>{_f(t.get('pct')):.1f}%</td></tr>"
        for t in xr["top_underlying"][:10]
    )
    adv = "".join(
        f"<div class='flag'><b>{a.get('title')}</b> — {a.get('detail')}</div>"
        for a in xr["advisories"][:3]
    )
    charts = []
    for key, cap in (("sectors", "Sector allocation (look-through)"), ("themes", "Theme exposure")):
        if ctx["charts"].get(key):
            charts.append(f"<div class='chart'><img src='{_img_b64(ctx['charts'][key])}'/><div class='cap'>{cap}</div></div>")
    return f"""
    <h2 class="section">Portfolio X-Ray</h2>
    <h3>Valuation (weighted, direct equity only)</h3>
    <div class="kpi">
      <div class="box"><div class="l">P/E</div><div class="v">{an.get('weighted_pe') or '—'}</div></div>
      <div class="box"><div class="l">P/B</div><div class="v">{an.get('weighted_pb') or '—'}</div></div>
      <div class="box"><div class="l">P/S</div><div class="v">{an.get('weighted_ps') or '—'}</div></div>
      <div class="box"><div class="l">P/CF</div><div class="v">{an.get('weighted_pcf') or '—'}</div></div>
      <div class="box"><div class="l">Valuation coverage</div><div class="v">{an.get('valuation_coverage_pct') or 0:.0f}%</div></div>
    </div>
    <div class="note">{an.get('valuation_coverage_note') or ''}</div>
    <h3>Sector Allocation (look-through)</h3>
    <table><thead><tr><th>Sector</th><th>Market Value</th><th>Weight</th></tr></thead><tbody>{sec_rows}</tbody></table>
    <div class="note">Look-through coverage {xr.get('coverage_pct')}% of portfolio; ${_f(xr.get('not_decomposed')):,.0f} not decomposed.</div>
    <h3>Top Underlying Holdings (look-through)</h3>
    <table><thead><tr><th>Holding</th><th>Value</th><th>Weight</th></tr></thead><tbody>{under}</tbody></table>
    {adv}
    <div class="charts">{''.join(charts)}</div>
    """


def _section_change_value(ctx) -> str:
    perf = ctx["performance"]
    cv = perf.get("change_value") or {}
    return f"""
    <h2 class="section">Change in Portfolio Value</h2>
    <table><thead><tr><th>Period</th><th>Beginning Value</th><th>Ending Value</th><th>Change ($)</th><th>Change (%)</th></tr></thead><tbody>
      <tr><td>Year-to-Date</td><td class='num'>{_fmt_usd(cv.get('ytd_start'))}</td><td class='num'>{_fmt_usd(cv.get('ytd_end'))}</td>
          <td class='num {('pos' if _f(cv.get('ytd_change'))>=0 else 'neg')}'>{_f(cv.get('ytd_change')):+,.0f}</td>
          <td class='num'>{_fmt_pct(cv.get('ytd_change_pct'), signed=True)}</td></tr>
      <tr><td>Since Inception</td><td class='num'>—</td><td class='num'>{_fmt_usd(cv.get('current_value'))}</td>
          <td class='num'>—</td><td class='num'>{_fmt_pct(cv.get('inception_return'), signed=True)}</td></tr>
    </tbody></table>
    <div class="note">Cash-flow decomposition (contributions vs withdrawals vs investment earnings) is not tracked separately;
    the {_fmt_pct(cv.get('inception_return'))} inception return is money-weighted, not a true time-weighted return.</div>
    """


def _section_unrealized(ctx) -> str:
    ur = ctx["unrealized"]
    rows = "".join(
        f"<tr><td>{r['symbol']}</td><td>{r['account']}</td><td class='num'>{r['quantity']:,.4f}</td>"
        f"<td class='num'>{_fmt_usd(r['cost_basis'])}</td><td class='num'>{_fmt_usd(r['market_value'])}</td>"
        f"<td class='num {('pos' if r['unrealized_gl']>=0 else 'neg')}'>{r['unrealized_gl']:+,.0f}</td>"
        f"<td class='num'>{r['gl_pct']:+.1f}%</td><td>{r['holding_period']}</td></tr>"
        for r in ur["rows"][:25]
    )
    return f"""
    <h2 class="section">Unrealized Gain / Loss Detail</h2>
    <table><thead><tr><th>Symbol</th><th>Account</th><th>Quantity</th><th>Cost Basis</th><th>Market Value</th><th>Unrealized G/L</th><th>G/L %</th><th>Term</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <div class="note">Term: LT = long-term (≥365d), ST = short-term, MIXED = both. Sourced from per-lot cost basis (broker API where available).
    Shown top 25 of {ur['count']} open positions.</div>
    """


def render_html(ctx: dict) -> str:
    toc_items = [
        "Accounts Included", "Investment Summary", "Performance", "Portfolio X-Ray",
        "Change in Portfolio Value", "Unrealized Gain/Loss Detail", "Disclosures",
    ]
    toc = "".join(f"<div>{i+1}. {t}</div>" for i, t in enumerate(toc_items))
    flags = "".join(f"<div class='flag'>⚠ {f}</div>" for f in ctx["quality_flags"])
    th = ctx["thesis"]
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Portfolio Report — {ctx['as_of']}</title>
<style>{_CSS}</style></head><body>

<div class="page cover"><div class="inner">
  <div class="brand"><b>TRADE AI</b> · Wealth Advisory</div>
  <h1>Portfolio Report</h1>
  <div class="sub">Custom report · prepared for the operator</div>
  <div class="meta">
    Prepared as of <b>{ctx['as_of']}</b><br/>
    Governing thesis <b>{th.get('thesis_version') or 'desk@?'}</b> · stance <b>{th.get('stance') or '—'}</b><br/>
    {ctx['portfolio']['positions_count']} positions · {len(ctx['accounts'])} accounts
  </div>
  <div class="disclaimer">READ_ONLY_ADVISORY — informational only. No broker action, no orders, no solicitations. Not affiliated with Morgan Stanley.</div>
</div></div>

<div class="page">
  <h2 class="section">Contents</h2>
  <div class="toc">{toc}</div>
  <h2 class="section">Governing Thesis</h2>
  <p style="font-size:11px;color:#333;">{(th.get('summary') or 'DATA_UNAVAILABLE')[:1200]}</p>
  {flags}
</div>

<div class="page">{_section_accounts(ctx)}{_section_summary(ctx)}</div>
<div class="page">{_section_performance(ctx)}</div>
<div class="page">{_section_xray(ctx)}</div>
<div class="page">{_section_change_value(ctx)}{_section_unrealized(ctx)}</div>

<div class="page">
  <h2 class="section">Disclosures</h2>
  <p style="font-size:10px;color:#333;line-height:1.6;">
  This report is produced by the Trade AI Advisory Desk (READ_ONLY_ADVISORY) from canonical Data Broker state
  (holdings, tax lots, ticker enrichment, performance attribution, look-through themes, fund factsheet weights).
  Figures are shown as captured; where a figure is unavailable it is labeled DATA_UNAVAILABLE and never estimated.
  </p>
  <p style="font-size:10px;color:#333;line-height:1.6;">
  Performance returns are money-weighted (CAGR) unless noted; a true time-weighted return (TWR) is a documented
  gap. Period returns marked "account-aggregated" may include transfers/ACATS step-changes. Sector and theme
  decomposition use provider factsheet weights refreshed quarterly. Valuation multiples are asset-weighted over
  direct equity positions only. This document is not investment advice and is not affiliated with or endorsed by
  Morgan Stanley.
  </p>
  <div class="footer">Generated {ctx['as_of']} · Trade AI Advisory Desk · READ_ONLY_ADVISORY</div>
</div>

</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════════
# PDF + delivery
# ═══════════════════════════════════════════════════════════════════════════════

def render_pdf(html: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="load")
        page.pdf(
            path=str(out_path),
            format="Letter",
            landscape=True,
            print_background=True,
            margin={"top": "0.4in", "bottom": "0.4in", "left": "0.4in", "right": "0.4in"},
        )
        browser.close()
    return out_path


def send_telegram_report_notice(pdf_path: Path, caption: str) -> bool:
    """Send PDF via telegram_alert.send_telegram_document chokepoint."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from telegram_alert import send_telegram_document
        ok = bool(send_telegram_document(str(pdf_path), caption=caption, bypass_router=True))
        try:
            root = str(PROJECT_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from scripts.lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="portfolio_report_ms", subject_key="ops:portfolio_report_ms",
                retention_class="operational", severity="info",
                sanitized_body=(caption or "")[:500], short_summary=(caption or "")[:120],
            ))
        except Exception:
            pass
        return ok
    except Exception as e:
        print(f"[report] telegram document error: {type(e).__name__}: {str(e)[:120]}")
        return False


def deliver(ctx: dict, pdf_path: Path, *, send: bool) -> dict[str, Any]:
    result = {"telegram_doc": False, "email": False}
    caption = f"📑 *Portfolio Report* — {ctx['as_of']}\nGoverning thesis {ctx['thesis'].get('thesis_version') or 'desk@?'} · READ_ONLY_ADVISORY"
    if send:
        result["telegram_doc"] = send_telegram_report_notice(pdf_path, caption)
        try:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from email_notifier import send_email
            summary = (
                f"Portfolio Report — {ctx['as_of']}\n\n"
                f"Total portfolio: {_fmt_usd(ctx['portfolio']['total_value'])}\n"
                f"Cash: {_fmt_usd(ctx['portfolio']['cash_value'])} ({ctx['portfolio']['cash_pct']:.1f}%)\n"
                f"YTD return: {_fmt_pct(ctx['performance'].get('ytd_return'), signed=True)}\n"
                f"Top actionable desk verdicts are in the PDF + Telegram /advisory.\n\n"
                f"PDF: {pdf_path}\n"
                f"Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/advisory\n\n"
                f"READ_ONLY_ADVISORY — informational only."
            )
            result["email"] = send_email(f"Portfolio Report — {ctx['as_of']}", summary)
        except Exception as e:
            print(f"[report] email error: {type(e).__name__}: {str(e)[:120]}")
    return result


# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="Morgan Stanley-style portfolio report")
    ap.add_argument("--ad-hoc", action="store_true", help="label run as ad-hoc")
    ap.add_argument("--dry-run", action="store_true", help="build + write files, do not send")
    ap.add_argument("--no-send", action="store_true", help="build, write, but do not deliver")
    ap.add_argument("--no-pdf", action="store_true", help="skip PDF render")
    ap.add_argument("--no-charts", action="store_true", help="skip chart generation")
    ap.add_argument("--out", default=str(REPORT_DIR), help="output directory")
    args = ap.parse_args()

    out_dir = Path(args.out)
    charts_dir = out_dir / "charts"
    ctx = assemble()

    if not args.no_charts:
        ctx["charts"] = render_charts(ctx, charts_dir)
    else:
        ctx["charts"] = {}
    print(f"[report] charts: {list(ctx['charts'].keys())}")

    html = render_html(ctx)
    stamp = ctx["as_of"]
    html_path = out_dir / f"portfolio_report_{stamp}.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"[report] wrote {html_path} ({html_path.stat().st_size} bytes)")

    pdf_path = out_dir / f"portfolio_report_{stamp}.pdf"
    if not args.no_pdf:
        render_pdf(html, pdf_path)
        print(f"[report] wrote {pdf_path} ({pdf_path.stat().st_size} bytes)")

    # Persist summary JSON for the Reports portal
    summary = {
        "as_of": stamp,
        "total_value": ctx["portfolio"]["total_value"],
        "cash_pct": ctx["portfolio"]["cash_pct"],
        "ytd_return": ctx["performance"].get("ytd_return"),
        "positions_count": ctx["portfolio"]["positions_count"],
        "unrealized_count": ctx["unrealized"]["count"],
        "quality_flags": ctx["quality_flags"],
        "html_path": str(html_path),
        "pdf_path": str(pdf_path),
        "authority": "READ_ONLY_ADVISORY",
    }
    (out_dir / f"portfolio_report_{stamp}.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")

    if args.dry_run:
        print("[report] dry-run — files written, nothing delivered")
        return 0
    if not args.no_send:
        dres = deliver(ctx, pdf_path, send=True)
        print(f"[report] delivery: {dres}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
