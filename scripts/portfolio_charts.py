"""portfolio_charts.py — Trade AI v12 Portfolio Intelligence
Generates charts as PNG files for embedding in DOCX intelligence brief.
Also produces Chart.js data structures for the HTML dashboard.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Matplotlib with non-interactive backend (no display required)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ── Style ──────────────────────────────────────────────────────────────────────
DARK_BG     = "#0D1B2A"
CARD_BG     = "#1A2744"
ACCENT      = "#2979FF"
GREEN       = "#0F9D58"
RED         = "#DB4437"
YELLOW      = "#F4B400"
GRAY        = "#9A9AB0"
WHITE       = "#E0E0F0"

SECTOR_COLORS = {
    "Defense":                "#1565C0",
    "Financials":             "#2E7D32",
    "Healthcare":             "#7B1FA2",
    "Technology":             "#E65100",
    "US Equity":              "#1976D2",
    "US Large Blend":         "#1565C0",
    "US Large Growth":        "#E65100",
    "US Large Value":         "#1B5E20",
    "US Small":               "#37474F",
    "International":          "#00695C",
    "International Equity":   "#00897B",
    "Bonds":                  "#5D4037",
    "Income/Dividend":        "#558B2F",
    "Income ETF/Dividend":    "#689F38",
    "BDC Income":             "#4527A0",
    "Growth ETF":             "#F57F17",
    "ETF/Fund":               "#424242",
    "US Equity Funds":        "#1A237E",
    "Cash":                   "#616161",
    "Other":                  "#9E9E9E",
}

def _fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=DARK_BG, edgecolor="none")
    buf.seek(0)
    data = buf.read()
    plt.close(fig)
    return data

def _fig_to_b64(fig) -> str:
    return base64.b64encode(_fig_to_bytes(fig)).decode()


# ── Chart 1: Sector Allocation Donut ─────────────────────────────────────────

def chart_sector_donut(sector_pct: Dict[str, float], title: str = "Sector Allocation") -> bytes:
    """Donut chart of sector exposure."""
    # Filter small slices
    items = [(s, p) for s, p in sorted(sector_pct.items(), key=lambda x: -x[1]) if p >= 1.0]
    if not items:
        return b""
    labels, values = zip(*items)
    colors = [SECTOR_COLORS.get(l, GRAY) for l in labels]

    fig, ax = plt.subplots(figsize=(7, 5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)

    wedges, texts, autotexts = ax.pie(
        values, labels=None, colors=colors, autopct="%1.1f%%",
        pctdistance=0.78, startangle=90,
        wedgeprops=dict(width=0.55, edgecolor=DARK_BG, linewidth=2),
    )
    for at in autotexts:
        at.set_color(WHITE); at.set_fontsize(8); at.set_fontweight("bold")

    # Legend
    legend_labels = [f"{l} ({v:.1f}%)" for l, v in zip(labels, values)]
    ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
              fontsize=8, frameon=False, labelcolor=WHITE)

    ax.set_title(title, color=WHITE, fontsize=13, fontweight="bold", pad=10)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Chart 2: Account Value Bar Chart ─────────────────────────────────────────

def chart_account_bars(account_summaries: Dict) -> bytes:
    """Horizontal bar chart of account values."""
    items = sorted(account_summaries.items(), key=lambda x: x[1].get("total_value", 0))
    names  = [v.get("display_name", k)[:25] for k, v in items]
    values = [v.get("total_value", 0) for _, v in items]
    gains  = [v.get("total_gain", 0) for _, v in items]
    colors = [GREEN if g >= 0 else RED for g in gains]

    fig, ax = plt.subplots(figsize=(7, 3.5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    bars = ax.barh(names, values, color=colors, edgecolor="none", height=0.55)

    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height()/2,
                f"${val:,.0f}", va="center", ha="left", color=WHITE, fontsize=9)

    ax.set_xlabel("Market Value ($)", color=GRAY, fontsize=9)
    ax.set_title("Portfolio by Account", color=WHITE, fontsize=12, fontweight="bold")
    ax.tick_params(colors=GRAY, labelsize=9)
    ax.spines[:].set_color(CARD_BG)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1000:.0f}K"))
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Chart 3: Top Holdings Exposure ───────────────────────────────────────────

def chart_top_holdings(holdings: List[Dict], top_n: int = 15) -> bytes:
    """Bar chart of top holdings by portfolio percentage."""
    valid = [h for h in holdings if (h.get("market_value") or 0) > 0
             and not h.get("is_loan") and not h.get("is_cash")]
    valid.sort(key=lambda h: -(h.get("market_value") or 0))
    top = valid[:top_n]

    names  = [h.get("symbol","") for h in top]
    pcts   = [h.get("portfolio_pct") or 0 for h in top]
    gains  = [h.get("gain_loss") or 0 for h in top]
    colors = [GREEN if g >= 0 else RED for g in gains]

    fig, ax = plt.subplots(figsize=(8, 5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    bars = ax.bar(names, pcts, color=colors, edgecolor="none", width=0.6)

    # Threshold line
    ax.axhline(15, color=YELLOW, linewidth=1.2, linestyle="--", alpha=0.8, label="15% threshold")
    ax.axhline(10, color=ACCENT, linewidth=0.8, linestyle=":", alpha=0.6, label="10% warning")

    for bar, pct in zip(bars, pcts):
        if pct > 1.5:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    f"{pct:.1f}%", ha="center", va="bottom", color=WHITE, fontsize=8, fontweight="bold")

    ax.set_ylabel("% of Total Portfolio", color=GRAY, fontsize=9)
    ax.set_title("Top Holdings by Portfolio Weight", color=WHITE, fontsize=12, fontweight="bold")
    ax.tick_params(colors=GRAY, labelsize=8)
    ax.tick_params(axis="x", rotation=45)
    ax.spines[:].set_color(CARD_BG)
    ax.legend(fontsize=8, frameon=False, labelcolor=WHITE)
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Chart 4: ETF Look-Through Ticker Exposure ──────────────────────────────────

def chart_etf_exposure(etf_exposure: Dict[str, float], title: str = "True Stock Exposure (via ETF Look-Through)") -> bytes:
    """Show effective ticker exposure including through ETFs."""
    if not etf_exposure:
        return b""
    items = sorted(etf_exposure.items(), key=lambda x: -x[1])[:20]
    names, values = zip(*items)
    total = sum(values)
    pcts = [v / total * 100 if total > 0 else 0 for v in values]
    colors = [GREEN if p >= 5 else ACCENT if p >= 2 else GRAY for p in pcts]

    fig, ax = plt.subplots(figsize=(9, 5.5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    bars = ax.barh(list(reversed(names)), list(reversed(values)), color=list(reversed(colors)),
                   edgecolor="none", height=0.6)

    for bar, val, pct in zip(bars, reversed(list(values)), reversed(list(pcts))):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height()/2,
                f"${val:,.0f}  ({pct:.1f}%)", va="center", ha="left", color=WHITE, fontsize=8)

    ax.set_xlabel("Effective Dollar Exposure", color=GRAY, fontsize=9)
    ax.set_title(title, color=WHITE, fontsize=11, fontweight="bold")
    ax.tick_params(colors=GRAY, labelsize=9)
    ax.spines[:].set_color(CARD_BG)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1000:.0f}K"))
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Chart 5: Gain/Loss by Holding ────────────────────────────────────────────

def chart_gain_loss(holdings: List[Dict], top_n: int = 20) -> bytes:
    """Waterfall-style gain/loss by holding."""
    valid = [h for h in holdings
             if h.get("gain_loss") is not None and not h.get("is_loan")
             and abs(h.get("gain_loss") or 0) > 100]
    valid.sort(key=lambda h: -(h.get("gain_loss") or 0))
    show = (valid[:top_n//2] + valid[-(top_n//2):])
    show.sort(key=lambda h: (h.get("gain_loss") or 0))

    names  = [h.get("symbol","") for h in show]
    gains  = [h.get("gain_loss") or 0 for h in show]
    colors = [GREEN if g >= 0 else RED for g in gains]

    fig, ax = plt.subplots(figsize=(9, 5), facecolor=DARK_BG)
    ax.set_facecolor(DARK_BG)
    bars = ax.barh(names, gains, color=colors, edgecolor="none", height=0.55)
    ax.axvline(0, color=GRAY, linewidth=0.8)

    ax.set_xlabel("Unrealized Gain / Loss ($)", color=GRAY, fontsize=9)
    ax.set_title("Unrealized P&L by Position", color=WHITE, fontsize=12, fontweight="bold")
    ax.tick_params(colors=GRAY, labelsize=8)
    ax.spines[:].set_color(CARD_BG)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x/1000:.0f}K"))
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Chart 6: Rebalancing Required ────────────────────────────────────────────

def chart_rebalancing(drift_analysis: Dict) -> bytes:
    """Show current vs target allocation for each account."""
    fig, axes = plt.subplots(1, len(drift_analysis), figsize=(5 * len(drift_analysis), 4),
                             facecolor=DARK_BG)
    if len(drift_analysis) == 1:
        axes = [axes]

    for ax, (acct_key, analysis) in zip(axes, drift_analysis.items()):
        ax.set_facecolor(DARK_BG)
        rows = [r for r in analysis.get("drift_rows", []) if r.get("target_pct", 0) > 0 or r.get("current_pct", 0) > 0]
        if not rows:
            continue
        labels = [r["bucket"][:12] for r in rows]
        target  = [r["target_pct"] for r in rows]
        current = [r["current_pct"] for r in rows]
        x = np.arange(len(labels))
        w = 0.35
        ax.bar(x - w/2, target,  w, label="Target",  color=ACCENT,  alpha=0.8, edgecolor="none")
        ax.bar(x + w/2, current, w, label="Current", color=YELLOW, alpha=0.8, edgecolor="none")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7, color=WHITE)
        ax.set_ylabel("%", color=GRAY, fontsize=8)
        ax.set_title(analysis.get("account_display","")[:20], color=WHITE, fontsize=9, fontweight="bold")
        ax.legend(fontsize=7, frameon=False, labelcolor=WHITE)
        ax.tick_params(colors=GRAY, labelsize=7)
        ax.spines[:].set_color(CARD_BG)

    fig.suptitle("Current vs Target Allocation by Account", color=WHITE, fontsize=11, fontweight="bold")
    fig.tight_layout()
    return _fig_to_bytes(fig)


# ── Save all charts to disk ───────────────────────────────────────────────────

def generate_all_charts(
    portfolio: Dict,
    analysis: Dict,
    rebalancing: Dict,
    output_dir: Path,
) -> Dict[str, str]:
    """
    Generate all charts as PNG files. Returns dict of name → file path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}

    holdings = portfolio.get("holdings", [])
    account_summaries = portfolio.get("account_summaries", {})
    sector_pct = analysis.get("sector_pct", {})
    drift = rebalancing.get("drift_analysis", {})

    print("  [charts] Generating sector donut...")
    data = chart_sector_donut(sector_pct)
    if data:
        p = output_dir / "chart_sector.png"
        p.write_bytes(data)
        paths["sector_donut"] = str(p)

    print("  [charts] Generating account bars...")
    data = chart_account_bars(account_summaries)
    if data:
        p = output_dir / "chart_accounts.png"
        p.write_bytes(data)
        paths["account_bars"] = str(p)

    print("  [charts] Generating holdings chart...")
    data = chart_top_holdings(holdings)
    if data:
        p = output_dir / "chart_holdings.png"
        p.write_bytes(data)
        paths["top_holdings"] = str(p)

    print("  [charts] Generating gain/loss chart...")
    data = chart_gain_loss(holdings)
    if data:
        p = output_dir / "chart_gainloss.png"
        p.write_bytes(data)
        paths["gain_loss"] = str(p)

    print("  [charts] Generating ETF look-through chart...")
    etf_exp = compute_etf_ticker_exposure(portfolio)
    if etf_exp:
        data = chart_etf_exposure(etf_exp)
        if data:
            p = output_dir / "chart_etf_exposure.png"
            p.write_bytes(data)
            paths["etf_exposure"] = str(p)
        paths["etf_exposure_data"] = etf_exp

    print("  [charts] Generating rebalancing chart...")
    data = chart_rebalancing(drift)
    if data:
        p = output_dir / "chart_rebalancing.png"
        p.write_bytes(data)
        paths["rebalancing"] = str(p)

    print(f"  [charts] {len(paths)} charts generated → {output_dir}")
    return paths


# ── ETF Look-Through Ticker Exposure ─────────────────────────────────────────

ETF_TOP_HOLDINGS_PCT = {
    "SCHG":  {"AAPL":12.1,"MSFT":11.4,"NVDA":10.2,"AMZN":8.3,"META":5.8,"TSLA":4.4,"GOOGL":4.9,"AVGO":3.2,"COST":2.1},
    "SCHD":  {"AVGO":4.2,"HD":4.1,"CVX":4.0,"KO":3.9,"MCD":3.5,"PEP":3.4,"VZ":3.2,"CSCO":3.1,"LMT":2.8,"ABBV":2.7},
    "ARKG":  {"CRSP":9.1,"BEAM":8.3,"VCYT":7.2,"PACB":6.4,"FATE":5.8,"TWST":5.1,"RXRX":4.9},
    "ARKQ":  {"TSLA":13.2,"TER":9.1,"JOBY":8.4,"DKNG":7.2,"TSM":6.8,"PATH":5.4,"KTOS":4.1},
    "DIV":   {"T":4.8,"F":4.2,"OMP":3.9,"SBR":3.7,"MPLX":3.4,"EPD":3.2,"MO":3.1},
    "BND":   {"US_TREASURY":45.0,"FNMA":12.0,"GNMA":8.0,"CORP_IG":20.0},
    "XLB":   {"LIN":22.8,"ECL":9.2,"APD":7.1,"SHW":6.8,"FCX":5.4,"NEM":5.1},
    "XLI":   {"CAT":5.8,"GE":5.6,"RTX":5.4,"HON":5.1,"UPS":4.8,"DE":4.6,"LMT":4.2,"NOC":3.8},
    "FCNTX": {"AAPL":13.8,"MSFT":11.2,"AMZN":9.4,"NVDA":8.1,"META":5.9,"GOOGL":5.4,"UNH":3.2,"AVGO":2.8},
    "AMANX": {"MSFT":10.2,"QCOM":6.4,"JCI":5.1,"TXN":4.8,"AMGN":4.6,"INTC":3.9,"MSI":3.4},
    # 401k funds (approximate look-through)
    "FID-CONTRA-F":  {"AAPL":14.1,"MSFT":11.8,"AMZN":9.2,"NVDA":7.8,"META":5.6},
    "SP500-D":       {"AAPL":7.2,"MSFT":6.8,"NVDA":5.9,"AMZN":5.1,"META":3.8,"GOOGL":4.2},
    "VANG-FTSE-SOC": {"MSFT":5.1,"AAPL":4.8,"NVDA":3.9,"AMZN":3.6,"JNJ":2.8},
    "JPM-LGCG":      {"NVDA":8.2,"MSFT":7.4,"AAPL":6.8,"AMZN":5.9,"META":4.2},
    "TRP-LVAL":      {"BRK.B":4.8,"JPM":4.2,"HD":3.9,"XOM":3.6,"UNH":3.2},
}


def compute_etf_ticker_exposure(portfolio: Dict) -> Dict[str, float]:
    """
    Compute effective dollar exposure to individual stocks through ETFs and funds.
    Returns ticker → estimated dollar exposure.
    """
    holdings = portfolio.get("holdings", [])
    totals: Dict[str, float] = {}

    for h in holdings:
        sym = h.get("symbol", "").upper()
        mv = h.get("market_value") or 0
        if mv <= 0 or h.get("is_loan") or h.get("is_cash"):
            continue

        if sym in ETF_TOP_HOLDINGS_PCT:
            # ETF/Fund: distribute exposure to underlying tickers
            for ticker, pct in ETF_TOP_HOLDINGS_PCT[sym].items():
                totals[ticker] = totals.get(ticker, 0) + mv * pct / 100
        elif not h.get("is_etf") and not h.get("is_fund"):
            # Direct holding
            totals[sym] = totals.get(sym, 0) + mv

    # Sort by exposure amount
    return dict(sorted(totals.items(), key=lambda x: -x[1]))
