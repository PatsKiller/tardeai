"""report_visuals.py — matplotlib visuals for analyst reports (digest + symbol)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_CHARTS = PROJECT_ROOT / "data" / "portfolios" / "reports" / "analyst" / "charts"

DARK_BG = "#0d0d1a"
CARD_BG = "#1a1a35"
GRID_COL = "#2a2a5e"
TEXT_COL = "#e0e0f0"
MUTED_COL = "#9A9AB0"
GREEN = "#0F9D58"
RED = "#DB4437"
YELLOW = "#F4B400"
BLUE = "#2979FF"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _save(fig, path: Path) -> str:
    plt = _plt()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sharper, crisper export — high DPI for polished report graphics.
    fig.savefig(str(path), bbox_inches="tight", dpi=170, facecolor=DARK_BG,
                edgecolor="none", pad_inches=0.15)
    plt.close(fig)
    return chart_url(path)


def chart_url(path: Path | str) -> str:
    p = Path(path)
    try:
        rel = p.relative_to(PROJECT_ROOT)
        return "/" + str(rel).replace("\\", "/")
    except ValueError:
        return str(p)


def chart_health_gauge(score: float, status: str = "", stem: str = "health") -> dict:
    """Semi-circular health score gauge 0-100."""
    plt = _plt()
    import matplotlib.patches as mpatches

    s = max(0, min(100, float(score or 0)))
    color = GREEN if s >= 75 else (YELLOW if s >= 50 else RED)
    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-0.2, 1.2)
    ax.axis("off")

    arc_bg = mpatches.Arc((0, 0), 2, 2, angle=0, theta1=0, theta2=180, linewidth=14, color=GRID_COL)
    arc_fg = mpatches.Arc((0, 0), 2, 2, angle=0, theta1=180 - s * 1.8, theta2=180, linewidth=14, color=color)
    ax.add_patch(arc_bg)
    ax.add_patch(arc_fg)
    ax.text(0, 0.35, f"{s:.0f}", ha="center", va="center", fontsize=28, fontweight="bold", color=TEXT_COL)
    ax.text(0, 0.05, "Health Score", ha="center", fontsize=9, color=MUTED_COL)
    if status:
        ax.text(0, -0.12, status.upper(), ha="center", fontsize=10, fontweight="bold", color=color)

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_health_{ts}.png"
    url = _save(fig, path)
    return {"type": "health_gauge", "chart_path": url, "score": s, "status": status}


def chart_proposal_pipeline(counts: list[dict], stem: str = "digest") -> dict:
    """Horizontal bar chart of proposal status counts."""
    if not counts:
        return {}
    plt = _plt()
    labels = [str(c.get("status", "?"))[:12] for c in counts]
    vals = [int(c.get("cnt") or 0) for c in counts]
    colors = [RED if "REJECT" in l or "EXPIR" in l else (YELLOW if "PEND" in l else GREEN) for l in labels]

    fig, ax = plt.subplots(figsize=(6, max(2.5, len(labels) * 0.45)))
    y = range(len(labels))
    ax.barh(list(y), vals, color=colors, alpha=0.85, height=0.55)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9, color=TEXT_COL)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title("Proposal Pipeline", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.02, i, str(v), va="center", color=TEXT_COL, fontsize=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_proposals_{ts}.png"
    url = _save(fig, path)
    return {"type": "proposal_pipeline", "chart_path": url}


def chart_portfolio_movers(holdings: list[dict], stem: str = "digest", limit: int = 10) -> dict:
    """Day change % bar chart for largest portfolio movers."""
    rows = [
        h for h in holdings
        if not h.get("is_cash") and _f(h.get("day_change_pct")) != 0
    ]
    rows.sort(key=lambda x: abs(_f(x.get("day_change_pct"))), reverse=True)
    rows = rows[:limit]
    if not rows:
        return {}

    plt = _plt()
    syms = [str(r.get("symbol", "")) for r in reversed(rows)]
    pcts = [_f(r.get("day_change_pct")) for r in reversed(rows)]
    colors = [GREEN if p >= 0 else RED for p in pcts]

    fig, ax = plt.subplots(figsize=(6.5, max(3, len(syms) * 0.38)))
    ax.barh(syms, pcts, color=colors, alpha=0.85, height=0.6)
    ax.axvline(0, color=MUTED_COL, linewidth=1)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title("Portfolio Day Movers (%)", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_movers_{ts}.png"
    url = _save(fig, path)
    return {"type": "portfolio_movers", "chart_path": url}


def chart_rsi_gauge(rsi: float, symbol: str = "") -> dict:
    """RSI 0-100 gauge with overbought/oversold zones."""
    plt = _plt()
    import matplotlib.patches as mpatches

    r = max(0, min(100, float(rsi or 50)))
    if r >= 70:
        color = RED
        zone = "Overbought"
    elif r <= 30:
        color = GREEN
        zone = "Oversold"
    else:
        color = BLUE
        zone = "Neutral"

    fig, ax = plt.subplots(figsize=(3.2, 2.2))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.barh(0.4, 100, height=0.25, color=GRID_COL, alpha=0.5)
    ax.barh(0.4, r, height=0.25, color=color, alpha=0.9)
    ax.axvline(30, color=GREEN, alpha=0.4, linewidth=1, linestyle="--")
    ax.axvline(70, color=RED, alpha=0.4, linewidth=1, linestyle="--")
    ax.text(50, 0.78, f"RSI {r:.1f}", ha="center", fontsize=14, fontweight="bold", color=TEXT_COL)
    ax.text(50, 0.12, zone, ha="center", fontsize=9, color=color)
    if symbol:
        ax.text(50, 0.92, symbol, ha="center", fontsize=8, color=MUTED_COL)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{symbol or 'sym'}_rsi_{ts}.png"
    url = _save(fig, path)
    return {"type": "rsi_gauge", "chart_path": url, "rsi": r, "zone": zone, "symbol": symbol}


def chart_report_lineage(
    symbol: str,
    points: list[dict],
    current_price: float | None = None,
) -> dict:
    """Line chart of price at each report generation (continuity timeline)."""
    if len(points) < 2:
        return {}
    plt = _plt()
    dates = [p.get("date", "") for p in points]
    prices = [_f(p.get("price")) for p in points]
    if current_price and current_price > 0:
        dates = dates + ["now"]
        prices = prices + [_f(current_price)]

    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    ax.plot(range(len(prices)), prices, color=BLUE, linewidth=2, marker="o", markersize=5)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(dates, rotation=35, ha="right", fontsize=7, color=MUTED_COL)
    ax.tick_params(axis="y", colors=MUTED_COL, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title(f"{symbol} — Report Continuity (price at each build)", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    ax.set_ylabel("Price ($)", color=MUTED_COL, fontsize=8)
    for i, p in enumerate(points):
        rec = str(p.get("recommendation") or "")[:4]
        if rec:
            ax.annotate(rec, (i, prices[i]), textcoords="offset points", xytext=(0, 8),
                        ha="center", fontsize=7, color=YELLOW)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{symbol}_continuity_{ts}.png"
    url = _save(fig, path)
    return {"type": "report_continuity", "chart_path": url, "symbol": symbol, "points": len(points)}


def chart_peer_movers(rows: list[dict], *, stem: str = "sector", title: str = "Peer Day Movers (%)", limit: int = 12) -> dict:
    """Horizontal bar chart of symbol day-change % (sector/theme peers)."""
    data = [
        {"symbol": str(r.get("symbol", "")), "pct": _f(r.get("day_change_pct"))}
        for r in rows
        if r.get("symbol")
    ]
    data.sort(key=lambda x: abs(x["pct"]), reverse=True)
    data = data[:limit]
    if not data:
        return {}

    plt = _plt()
    syms = [d["symbol"] for d in reversed(data)]
    pcts = [d["pct"] for d in reversed(data)]
    colors = [GREEN if p >= 0 else RED for p in pcts]

    fig, ax = plt.subplots(figsize=(6.8, max(3, len(syms) * 0.42)))
    bars = ax.barh(syms, pcts, color=colors, alpha=0.92, height=0.62,
                   edgecolor=TEXT_COL, linewidth=0.4)
    ax.axvline(0, color=MUTED_COL, linewidth=1.2)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title(title, color=TEXT_COL, fontsize=11, fontweight="bold", pad=9)
    pad = (max(abs(p) for p in pcts) or 1) * 0.04
    for p, sym in zip(pcts, syms):
        ax.text(p + (pad if p >= 0 else -pad), sym, f"{p:+.2f}%",
                va="center", ha="left" if p >= 0 else "right",
                color=TEXT_COL, fontsize=8, fontweight="bold")
    ax.margins(x=0.18)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_peer_movers_{ts}.png"
    url = _save(fig, path)
    return {"type": "peer_movers", "chart_path": url}


def chart_analyst_targets(symbol: str, pro: dict, price: float) -> dict:
    """Analyst price-target range (low/mean/high) with current price + consensus rating."""
    pro = pro or {}
    t_low = _f(pro.get("target_low_price"))
    t_mean = _f(pro.get("target_mean_price"))
    t_high = _f(pro.get("target_high_price"))
    if t_mean <= 0 or t_low <= 0 or t_high <= 0:
        return {}
    plt = _plt()
    lo = min(t_low, price) * 0.97
    hi = max(t_high, price) * 1.03
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 1)
    ax.axis("off")
    # target range band
    ax.plot([t_low, t_high], [0.5, 0.5], color=BLUE, linewidth=7, alpha=0.45, solid_capstyle="round", zorder=1)
    for val, label, col in [(t_low, "Low", MUTED_COL), (t_mean, "Mean", GREEN), (t_high, "High", BLUE)]:
        ax.scatter([val], [0.5], s=120, color=col, zorder=3, edgecolors=TEXT_COL, linewidths=0.6)
        ax.text(val, 0.74, f"{label}\n${val:,.0f}", ha="center", fontsize=8.5, color=col, fontweight="bold")
    if price > 0:
        ax.axvline(price, color=YELLOW, linewidth=2.2, alpha=0.95, zorder=2)
        ax.text(price, 0.20, f"Price\n${price:,.2f}", ha="center", fontsize=8.5, color=YELLOW, fontweight="bold")
    n = int(_f(pro.get("number_of_analyst_opinions")))
    up = _f(pro.get("upside_to_mean_target_pct"))
    rk = str(pro.get("recommendation_key") or "").replace("_", " ").title()
    ax.set_title(f"{symbol} — Wall-Street Price Targets ({n} analysts · {rk})",
                 color=TEXT_COL, fontsize=11, fontweight="bold", pad=10)
    ax.text(0.5, 0.04, f"Mean upside {up:+.1f}%", transform=ax.transAxes, ha="center",
            fontsize=9, color=GREEN if up >= 0 else RED, fontweight="bold")
    fig.tight_layout()
    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{symbol or 'sym'}_targets_{ts}.png"
    return {"type": "analyst_targets", "chart_path": _save(fig, path),
            "caption": f"{n} analysts · mean ${t_mean:,.0f} ({up:+.1f}%)", "symbol": symbol}


def chart_rating_distribution(symbol: str, dist: dict) -> dict:
    """Buy / Hold / Sell analyst rating split."""
    if not dist or not dist.get("n"):
        return {}
    plt = _plt()
    labels = ["Buy", "Hold", "Sell"]
    vals = [int(dist.get("buy") or 0), int(dist.get("hold") or 0), int(dist.get("sell") or 0)]
    colors = [GREEN, YELLOW, RED]
    fig, ax = plt.subplots(figsize=(4.8, 2.6))
    bars = ax.bar(labels, vals, color=colors, alpha=0.92, width=0.6, edgecolor=TEXT_COL, linewidth=0.4)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title(f"{symbol} — Implied Rating Split (from mean · n={dist['n']})", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    for i, v in enumerate(vals):
        ax.text(i, v + max(vals) * 0.03, str(v), ha="center", color=TEXT_COL, fontsize=10, fontweight="bold")
    fig.tight_layout()
    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{symbol or 'sym'}_ratingdist_{ts}.png"
    return {"type": "rating_distribution", "chart_path": _save(fig, path), "symbol": symbol}


def chart_coverage_bars(labels: list[str], values: list[int], *, stem: str = "sector", title: str = "Coverage") -> dict:
    """Simple vertical bar chart for peer/watchlist/holding counts."""
    if not labels or not values:
        return {}
    plt = _plt()
    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    colors = [BLUE, GREEN, YELLOW, MUTED_COL][: len(labels)]
    ax.bar(labels, values, color=colors, alpha=0.85, width=0.55)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title(title, color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    for i, v in enumerate(values):
        ax.text(i, v + max(values) * 0.03, str(v), ha="center", color=TEXT_COL, fontsize=9)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_coverage_{ts}.png"
    url = _save(fig, path)
    return {"type": "coverage_bars", "chart_path": url}


def chart_decision_safety(counts: dict, *, stem: str = "intel") -> dict:
    """Stacked horizontal bar for safe / pending / unsafe decision counts."""
    mapping = [
        ("safe", "Safe", GREEN),
        ("pending", "Pending", YELLOW),
        ("unsafe", "Unsafe", RED),
    ]
    labels, vals, colors = [], [], []
    for key, label, col in mapping:
        v = int(counts.get(key) or 0)
        if v > 0:
            labels.append(label)
            vals.append(v)
            colors.append(col)
    if not vals:
        return {}

    plt = _plt()
    fig, ax = plt.subplots(figsize=(5.5, 2.4))
    y = range(len(labels))
    ax.barh(list(y), vals, color=colors, alpha=0.88, height=0.55)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9, color=TEXT_COL)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title("Decision Safety Mix", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.02, i, str(v), va="center", color=TEXT_COL, fontsize=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_safety_{ts}.png"
    url = _save(fig, path)
    return {"type": "decision_safety", "chart_path": url}


def chart_ensemble_scores(rows: list[dict], *, stem: str = "intel", limit: int = 8) -> dict:
    """Layer 4 ensemble scores by subject (0-10 scale)."""
    data = []
    for r in rows[:limit]:
        sym = str(r.get("subject") or r.get("symbol") or "")[:8]
        score = _f(r.get("final_score"))
        if 0 < score <= 1:
            score *= 10
        if sym and score:
            data.append({"symbol": sym, "score": score})
    if not data:
        return {}

    plt = _plt()
    syms = [d["symbol"] for d in reversed(data)]
    scores = [d["score"] for d in reversed(data)]
    colors = [GREEN if s >= 7 else (YELLOW if s >= 5 else RED) for s in scores]

    fig, ax = plt.subplots(figsize=(6, max(2.8, len(syms) * 0.4)))
    ax.barh(syms, scores, color=colors, alpha=0.85, height=0.55)
    ax.set_xlim(0, 10)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title("Layer 4 Ensemble Scores (/10)", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_ensemble_{ts}.png"
    url = _save(fig, path)
    return {"type": "ensemble_scores", "chart_path": url}


def chart_sector_allocation(sectors: list[dict], *, stem: str = "sectors", title: str = "Portfolio Weight by Sector (%)") -> dict:
    """Horizontal bar chart of sector portfolio weights."""
    rows = [
        {"sector": str(s.get("sector", "?"))[:28], "pct": _f(s.get("weight_pct"))}
        for s in sectors
        if _f(s.get("weight_pct")) > 0
    ]
    rows.sort(key=lambda x: x["pct"], reverse=True)
    rows = rows[:14]
    if not rows:
        return {}

    plt = _plt()
    labels = [r["sector"] for r in reversed(rows)]
    vals = [r["pct"] for r in reversed(rows)]
    fig, ax = plt.subplots(figsize=(6.5, max(3, len(labels) * 0.38)))
    ax.barh(labels, vals, color=BLUE, alpha=0.85, height=0.6)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title(title, color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_sectors_{ts}.png"
    url = _save(fig, path)
    return {"type": "sector_allocation", "chart_path": url}


def chart_period_performance(periods: dict, stem: str = "weekly") -> dict:
    """Bar chart of portfolio period returns (1W, 1M, 3M, YTD)."""
    labels, vals = [], []
    for key in ("1W", "1M", "3M", "YTD"):
        row = periods.get(key) if isinstance(periods, dict) else None
        if not isinstance(row, dict):
            continue
        pct = row.get("change_pct")
        if pct is None:
            continue
        labels.append(key)
        vals.append(_f(pct))
    if not labels:
        return {}

    plt = _plt()
    colors = [GREEN if v >= 0 else RED for v in vals]
    fig, ax = plt.subplots(figsize=(5.5, 2.8))
    ax.bar(labels, vals, color=colors, alpha=0.85, width=0.55)
    ax.axhline(0, color=MUTED_COL, linewidth=1)
    ax.set_facecolor(CARD_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.set_title("Portfolio Period Returns (%)", color=TEXT_COL, fontsize=10, fontweight="bold", pad=8)
    for i, v in enumerate(vals):
        ax.text(i, v + (0.15 if v >= 0 else -0.15), f"{v:+.1f}%", ha="center",
                va="bottom" if v >= 0 else "top", color=TEXT_COL, fontsize=8)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{stem}_periods_{ts}.png"
    url = _save(fig, path)
    return {"type": "period_performance", "chart_path": url}


def chart_thesis_validity_range(
    *,
    symbol: str = "",
    entry: float,
    stop: float,
    target: float,
    price: float,
    valid_low: float | None = None,
    valid_high: float | None = None,
    zone_status: str = "",
    drift_pct: float | None = None,
) -> dict:
    """Thesis validity range — stop/entry band/target with current price marker and drift gap."""
    if not entry or not stop or not target or not price:
        return {}
    plt = _plt()
    import matplotlib.patches as mpatches

    lo = min(stop, entry, target, price, valid_low or entry) * 0.985
    hi = max(stop, entry, target, price, valid_high or entry) * 1.015
    span = hi - lo or 1.0

    zone = str(zone_status or "").lower()
    if zone in ("invalid", "at_risk"):
        band_color = RED
    elif zone in ("approaching", "stressed", "warning"):
        band_color = YELLOW
    else:
        band_color = GREEN

    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.axhspan(0.38, 0.62, color=GRID_COL, alpha=0.35, zorder=0)
    ax.plot([stop, target], [0.5, 0.5], color=MUTED_COL, linewidth=3, alpha=0.5, zorder=1)

    vlo = valid_low if valid_low and valid_low > 0 else entry * 0.97
    vhi = valid_high if valid_high and valid_high > 0 else entry * 1.03
    ax.axvspan(vlo, vhi, ymin=0.32, ymax=0.68, color=band_color, alpha=0.28, zorder=2)
    ax.text((vlo + vhi) / 2, 0.72, "Valid entry band", ha="center", fontsize=8, color=band_color, fontweight="bold")

    markers = [
        (stop, "Stop", RED),
        (entry, "Entry", YELLOW),
        (price, "Price", BLUE),
        (target, "Target", GREEN),
    ]
    for val, label, col in markers:
        if val and lo <= val <= hi:
            ax.axvline(val, color=col, linewidth=2, alpha=0.9, zorder=3)
            ax.scatter([val], [0.5], s=70, color=col, zorder=4, edgecolors=TEXT_COL, linewidths=0.5)
            ax.text(val, 0.22, f"{label}\n${val:,.2f}", ha="center", fontsize=7.5, color=col, fontweight="bold")

    drift_txt = f"Drift {drift_pct:+.1f}%" if drift_pct is not None else ""
    status_txt = zone_status.replace("_", " ").title() if zone_status else "—"
    title = f"{symbol} — Thesis Validity" if symbol else "Thesis Validity"
    ax.set_title(title, color=TEXT_COL, fontsize=11, fontweight="bold", pad=10)
    ax.text(0.5, 0.06, f"Zone: {status_txt}" + (f" · {drift_txt}" if drift_txt else ""),
            transform=ax.transAxes, ha="center", fontsize=9, color=band_color, fontweight="bold")
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    stem = symbol or "sym"
    path = REPORT_CHARTS / f"{stem}_thesis_validity_{ts}.png"
    url = _save(fig, path)
    return {
        "type": "thesis_validity_bar",
        "chart_path": url,
        "caption": f"{status_txt}" + (f" · {drift_txt}" if drift_txt else ""),
        "symbol": symbol,
    }


def chart_risk_reward(entry: float, stop: float, target: float, price: float, symbol: str = "") -> dict:
    """Risk/reward ladder visualization."""
    if not entry or not stop or not target:
        return {}
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6, 2.2))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.set_xlim(min(stop, target, price) * 0.98, max(stop, target, price, entry) * 1.02)
    ax.set_ylim(0, 1)
    ax.axis("off")

    for val, label, col in [
        (stop, "Stop", RED),
        (entry, "Entry", YELLOW),
        (price, "Price", BLUE),
        (target, "Target", GREEN),
    ]:
        if val:
            ax.axvline(val, color=col, linewidth=2, alpha=0.85)
            ax.text(val, 0.55, f"{label}\n${val:,.2f}", ha="center", fontsize=8, color=col, fontweight="bold")

    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk else 0
    ax.text(0.5, 0.15, f"R:R {rr}:1", transform=ax.transAxes, ha="center", fontsize=10, color=TEXT_COL)
    ax.set_title(f"{symbol} Risk / Reward" if symbol else "Risk / Reward", color=TEXT_COL, fontsize=10, pad=6)
    fig.tight_layout()

    ts = datetime.now().strftime("%Y%m%d")
    path = REPORT_CHARTS / f"{symbol or 'sym'}_rr_{ts}.png"
    url = _save(fig, path)
    return {"type": "risk_reward", "chart_path": url, "planned_rr": rr}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default