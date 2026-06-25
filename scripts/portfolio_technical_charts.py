"""portfolio_technical_charts.py — Technical Analysis Chart Generation
Produces PNG charts for DOCX report and dashboard embedding.

Charts:
1. Portfolio Technical Health Bar — position scores as colored horizontal bars
2. SMA Alignment Matrix — traffic light grid (SMA20/50/200 above/below for each position)
3. RSI Distribution — horizontal bars sorted by RSI, zones highlighted
4. Support Gap Analysis — how far each position is from its key support levels
5. Historical Price + SMA Overlay — 6-month Yahoo Finance prices with SMA lines
"""
from __future__ import annotations
import base64
import io
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

# Lazy import matplotlib to avoid issues on systems without display
def _plt():
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    return plt


def _b64_png(fig) -> str:
    """Convert matplotlib figure to base64 PNG string."""
    plt = _plt()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120,
                facecolor="#0d0d1a", edgecolor="none")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


def _save_png(fig, path: Path) -> Path:
    """Save matplotlib figure to PNG file."""
    plt = _plt()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), bbox_inches="tight", dpi=120,
                facecolor="#0d0d1a", edgecolor="none")
    plt.close(fig)
    return path


# Dark theme constants
DARK_BG   = "#0d0d1a"
CARD_BG   = "#1a1a35"
GRID_COL  = "#2a2a5e"
TEXT_COL  = "#e0e0f0"
MUTED_COL = "#9A9AB0"
GREEN     = "#0F9D58"
RED       = "#DB4437"
YELLOW    = "#F4B400"
BLUE      = "#2979FF"


def _apply_dark(ax, fig, title: str = ""):
    """Apply dark theme to axes."""
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.tick_params(colors=MUTED_COL, labelsize=8)
    ax.xaxis.label.set_color(MUTED_COL)
    ax.yaxis.label.set_color(MUTED_COL)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_COL)
    ax.grid(True, color=GRID_COL, alpha=0.5, linewidth=0.5)
    if title:
        ax.set_title(title, color=TEXT_COL, fontsize=10, pad=8, fontweight="bold")


def chart_portfolio_health(positions: Dict, output_path: Optional[Path] = None) -> str:
    """Horizontal bar chart of technical scores per position."""
    if not positions:
        return ""
    plt = _plt()

    # Sort by market value descending, top 20
    items = sorted(positions.items(), key=lambda x: -(x[1].get("market_value",0)))[:20]
    syms   = [x[0] for x in reversed(items)]
    scores = [x[1].get("tech_score", 50) for x in reversed(items)]
    mvs    = [x[1].get("market_value",0) for x in reversed(items)]
    colors = [GREEN if s >= 70 else (YELLOW if s >= 40 else RED) for s in scores]

    fig, ax = plt.subplots(figsize=(8, max(4, len(syms)*0.35)))
    bars = ax.barh(syms, scores, color=colors, alpha=0.85, height=0.6)
    ax.axvline(70, color=GREEN, alpha=0.4, linewidth=1, linestyle="--")
    ax.axvline(40, color=RED,   alpha=0.4, linewidth=1, linestyle="--")
    ax.set_xlim(0, 100)

    # Score labels
    for bar, score, mv in zip(bars, scores, mvs):
        ax.text(score + 1, bar.get_y() + bar.get_height()/2,
                f"{score}  ${mv/1e3:.0f}K", va="center", ha="left",
                color=TEXT_COL, fontsize=7)

    _apply_dark(ax, fig, "Portfolio Technical Health Score (0-100)")
    ax.text(72, -0.8, "Green", color=GREEN, fontsize=7)
    ax.text(42, -0.8, "Yellow", color=YELLOW, fontsize=7)
    ax.text(5, -0.8, "Red", color=RED, fontsize=7)
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def chart_sma_matrix(positions: Dict, output_path: Optional[Path] = None) -> str:
    """Traffic light grid: SMA20/50/200 above/below for each position."""
    if not positions:
        return ""
    plt = _plt()
    import numpy as np

    items = sorted(positions.items(), key=lambda x: -(x[1].get("market_value",0)))[:18]
    syms  = [x[0] for x in items]
    levels = ["SMA20", "SMA50", "SMA200"]

    data = []
    for sym, d in items:
        row = []
        for level in levels:
            above_key = f"above_{level.lower()}"
            val = d.get(above_key)
            row.append(1 if val else (-1 if val is False else 0))
        data.append(row)

    arr = np.array(data)
    fig, ax = plt.subplots(figsize=(6, max(4, len(syms)*0.4)))

    cmap_colors = [RED, "#2a2a5e", GREEN]
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("signals", cmap_colors, N=3)
    ax.imshow(arr, cmap=cmap, aspect="auto", vmin=-1, vmax=1)

    ax.set_xticks(range(len(levels)))
    ax.set_xticklabels(levels, color=TEXT_COL, fontsize=9)
    ax.set_yticks(range(len(syms)))
    ax.set_yticklabels(syms, color=TEXT_COL, fontsize=8)

    for i in range(len(syms)):
        for j in range(len(levels)):
            val = arr[i, j]
            txt = "▲" if val == 1 else ("▼" if val == -1 else "?")
            col = GREEN if val == 1 else (RED if val == -1 else MUTED_COL)
            ax.text(j, i, txt, ha="center", va="center", color=col, fontsize=10, fontweight="bold")

    _apply_dark(ax, fig, "MA Alignment Matrix (▲ = Price Above / ▼ = Price Below)")
    ax.grid(False)
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def chart_rsi_distribution(positions: Dict, output_path: Optional[Path] = None) -> str:
    """Horizontal RSI bars sorted by value with overbought/oversold zones."""
    if not positions:
        return ""
    plt = _plt()

    items_rsi = [(sym, d.get("rsi",50) or 50, d.get("market_value",0))
                 for sym, d in positions.items() if d.get("rsi")]
    if not items_rsi:
        return ""
    items_rsi.sort(key=lambda x: x[1])

    syms   = [x[0] for x in items_rsi]
    rsis   = [x[1] for x in items_rsi]
    colors = [RED if r > 70 else (YELLOW if r > 60 else (GREEN if r < 30 else BLUE))
              for r in rsis]

    fig, ax = plt.subplots(figsize=(7, max(3, len(syms)*0.35)))
    ax.barh(syms, rsis, color=colors, alpha=0.85, height=0.6)
    ax.axvline(70, color=RED,    alpha=0.5, linewidth=1.5, linestyle="--", label="Overbought (70)")
    ax.axvline(30, color=GREEN,  alpha=0.5, linewidth=1.5, linestyle="--", label="Oversold (30)")
    ax.axvline(50, color=MUTED_COL, alpha=0.3, linewidth=1, linestyle=":")
    ax.set_xlim(0, 100)

    for i, (rsi, sym) in enumerate(zip(rsis, syms)):
        ax.text(rsi + 1, i, f"{rsi:.0f}", va="center", color=TEXT_COL, fontsize=7)

    ax.axvspan(70, 100, alpha=0.06, color=RED)
    ax.axvspan(0, 30, alpha=0.06, color=GREEN)

    legend = ax.legend(fontsize=7, facecolor=CARD_BG, labelcolor=TEXT_COL,
                        edgecolor=GRID_COL, loc="lower right")
    _apply_dark(ax, fig, "RSI(14) Distribution — Overbought / Oversold Zones")
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def chart_support_gap(positions: Dict, output_path: Optional[Path] = None) -> str:
    """Distance from current price to SMA200 support (risk proximity)."""
    if not positions:
        return ""
    plt = _plt()

    items = []
    for sym, d in positions.items():
        price  = d.get("price",0) or 0
        sma200 = d.get("sma200")
        mv     = d.get("market_value",0)
        if price and sma200 and mv > 1000:
            gap_pct = (price - sma200) / sma200 * 100
            items.append((sym, gap_pct, mv))

    if not items:
        return ""
    items.sort(key=lambda x: x[1])
    syms = [x[0] for x in items]
    gaps = [x[1] for x in items]
    colors = [RED if g < 0 else (YELLOW if g < 5 else GREEN) for g in gaps]

    fig, ax = plt.subplots(figsize=(7, max(3, len(syms)*0.38)))
    ax.barh(syms, gaps, color=colors, alpha=0.85, height=0.6)
    ax.axvline(0, color=MUTED_COL, linewidth=1.5)
    ax.axvline(5, color=YELLOW, alpha=0.4, linewidth=1, linestyle="--")

    for i, (gap, sym) in enumerate(zip(gaps, syms)):
        label = f"{gap:+.1f}%"
        xpos  = gap + 0.3 if gap >= 0 else gap - 0.3
        ha    = "left" if gap >= 0 else "right"
        ax.text(xpos, i, label, va="center", ha=ha, color=TEXT_COL, fontsize=7)

    ax.axvspan(-50, 0, alpha=0.05, color=RED)
    _apply_dark(ax, fig, "Distance from SMA200 Support (% — negative = below = at risk)")
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def _fetch_yahoo_history(symbol: str, days: int = 180) -> Optional[Dict]:
    """Fetch historical OHLCV from Yahoo Finance."""
    try:
        end   = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days)).timestamp())
        url   = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp  = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                             params={"interval": "1d", "period1": start, "period2": end},
                             timeout=12)
        if not resp.ok:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        ts = result[0].get("timestamp", [])
        quote = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close", [])
        volumes = quote.get("volume", [])
        if not ts or not closes:
            return None
        rows = []
        for t, c, v in zip(ts, closes, volumes or [None] * len(closes)):
            if c is None:
                continue
            rows.append({
                "date": datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                "close": float(c),
                "volume": float(v) if v is not None else None,
            })
        if not rows:
            return None
        return {
            "dates": [r["date"] for r in rows],
            "prices": [r["close"] for r in rows],
            "volumes": [r["volume"] for r in rows],
        }
    except Exception:
        return None


def _calc_sma(prices: List[float], period: int) -> List[Optional[float]]:
    """Calculate simple moving average."""
    result = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i-period+1:i+1]) / period
    return result


def chart_volume_rvol(symbol: str, rvol: Optional[float] = None,
                      output_path: Optional[Path] = None) -> str:
    """Volume bars with 20-day average overlay; annotates relative volume."""
    plt = _plt()
    hist = _fetch_yahoo_history(symbol, 120)
    if not hist or len(hist.get("volumes") or []) < 10:
        return ""

    n = min(60, len(hist["volumes"]))
    volumes = [v or 0 for v in hist["volumes"][-n:]]
    dates = hist["dates"][-n:]
    avg20 = []
    for i in range(len(volumes)):
        window = volumes[max(0, i - 19): i + 1]
        avg20.append(sum(window) / len(window) if window else 0)

    calc_rvol = None
    if volumes[-1] and avg20[-1]:
        calc_rvol = round(volumes[-1] / avg20[-1], 2)
    display_rvol = rvol if rvol is not None else calc_rvol

    x = range(len(volumes))
    tick_idx = [i for i in range(0, len(dates), max(1, len(dates) // 5))]
    tick_labels = [dates[i][5:] for i in tick_idx]

    fig, ax = plt.subplots(figsize=(9, 3.2))
    colors = [BLUE if v >= avg20[i] else MUTED_COL for i, v in enumerate(volumes)]
    ax.bar(x, volumes, color=colors, alpha=0.75, width=0.85, label="Volume")
    ax.plot(x, avg20, color=YELLOW, linewidth=1.4, label="20d avg")
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_labels)
    title = f"{symbol} — Volume & RVOL"
    if display_rvol is not None:
        title += f" (RVOL {display_rvol:.2f}x)"
    _apply_dark(ax, fig, title)
    ax.legend(fontsize=7, facecolor=CARD_BG, labelcolor=TEXT_COL, edgecolor=GRID_COL, loc="upper left")
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def chart_price_history(symbol: str, current_price: float,
                         sma200: Optional[float], sma50: Optional[float],
                         sma20: Optional[float],
                         output_path: Optional[Path] = None) -> str:
    """6-month price chart with SMA20/50/200 overlay."""
    plt = _plt()

    hist = _fetch_yahoo_history(symbol, 200)
    if not hist or len(hist["prices"]) < 20:
        return ""

    prices = hist["prices"]
    if current_price <= 0 and prices:
        current_price = float(prices[-1])
    dates  = hist["dates"]
    sma20_line  = _calc_sma(prices, 20)
    sma50_line  = _calc_sma(prices, 50)
    sma200_line = _calc_sma(prices, min(200, len(prices)))

    # Use only last 130 trading days (~6 months)
    n = min(130, len(prices))
    prices = prices[-n:]
    dates  = dates[-n:]
    sma20_line  = sma20_line[-n:]
    sma50_line  = sma50_line[-n:]
    sma200_line = sma200_line[-n:]

    x = range(len(prices))
    date_ticks = [i for i in range(0, len(dates), max(1, len(dates)//6))]
    date_labels = [dates[i][5:] for i in date_ticks]  # MM-DD

    fig, ax = plt.subplots(figsize=(9, 3.5))

    # Price area
    ax.fill_between(x, prices, alpha=0.15, color=BLUE)
    ax.plot(x, prices, color=TEXT_COL, linewidth=1.5, label=symbol, zorder=5)

    # SMA lines
    sma20_vals  = [v for v in sma20_line if v is not None]
    sma50_vals  = [v for v in sma50_line if v is not None]
    sma200_vals = [v for v in sma200_line if v is not None]
    sma20_x     = [i for i, v in enumerate(sma20_line) if v is not None]
    sma50_x     = [i for i, v in enumerate(sma50_line) if v is not None]
    sma200_x    = [i for i, v in enumerate(sma200_line) if v is not None]

    if sma20_vals:  ax.plot(sma20_x,  sma20_vals,  color=GREEN,  linewidth=1.2, linestyle="-",  alpha=0.9, label="SMA20")
    if sma50_vals:  ax.plot(sma50_x,  sma50_vals,  color=YELLOW, linewidth=1.2, linestyle="-",  alpha=0.9, label="SMA50")
    if sma200_vals: ax.plot(sma200_x, sma200_vals, color=RED,    linewidth=1.5, linestyle="--", alpha=0.9, label="SMA200")

    # Current price line
    ax.axhline(current_price, color=BLUE, linewidth=0.8, linestyle=":", alpha=0.7)

    ax.set_xticks(date_ticks)
    ax.set_xticklabels(date_labels, rotation=0)
    legend = ax.legend(fontsize=7, facecolor=CARD_BG, labelcolor=TEXT_COL,
                        edgecolor=GRID_COL, loc="upper left", ncol=4)
    _apply_dark(ax, fig, f"{symbol} — 6-Month Price History with SMA Overlay")
    fig.tight_layout()

    if output_path:
        _save_png(fig, output_path)
        return str(output_path)
    return _b64_png(fig)


def generate_all_technical_charts(technical: Dict, charts_dir: Path) -> Dict[str, Path]:
    """Generate all technical charts, save to charts_dir, return path dict."""
    if not technical or not technical.get("positions"):
        return {}

    positions = technical.get("positions", {})
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths = {}

    print("  [tech-charts] Generating portfolio health chart...")
    p = chart_portfolio_health(positions, charts_dir / "tech_health.png")
    if p: paths["health"] = Path(p)

    print("  [tech-charts] Generating SMA matrix chart...")
    p = chart_sma_matrix(positions, charts_dir / "tech_sma_matrix.png")
    if p: paths["sma_matrix"] = Path(p)

    print("  [tech-charts] Generating RSI distribution chart...")
    p = chart_rsi_distribution(positions, charts_dir / "tech_rsi.png")
    if p: paths["rsi"] = Path(p)

    print("  [tech-charts] Generating support gap chart...")
    p = chart_support_gap(positions, charts_dir / "tech_support_gap.png")
    if p: paths["support_gap"] = Path(p)

    # Historical price charts for top 6 positions by market value
    top6 = sorted(positions.items(), key=lambda x: -(x[1].get("market_value",0)))[:6]
    print(f"  [tech-charts] Generating price history charts for {len(top6)} positions...")
    for sym, d in top6:
        price = d.get("price",0) or 0
        if not price:
            continue
        chart_path = charts_dir / f"price_{sym.lower()}.png"
        p = chart_price_history(
            sym, price,
            d.get("sma200"), d.get("sma50"), d.get("sma20"),
            chart_path
        )
        if p:
            paths[f"price_{sym}"] = Path(p)
        time.sleep(0.2)  # Rate limit Yahoo Finance

    print(f"  [tech-charts] ✅ {len(paths)} technical charts generated")
    return paths
