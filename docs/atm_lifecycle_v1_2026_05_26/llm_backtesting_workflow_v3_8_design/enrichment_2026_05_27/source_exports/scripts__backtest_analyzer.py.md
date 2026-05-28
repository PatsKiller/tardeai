# Source: scripts/backtest_analyzer.py (17944 bytes)
```python
#!/usr/bin/env python3
"""backtest_analyzer.py — LLM-powered trade analysis + strategy pattern backtesting.

Three capabilities:
1. Entry/exit quality grading with LLM analysis (was entry early/late?)
2. Finviz chart context for visual pattern recognition
3. Strategy pattern backtesting against incubator symbols

No live trading. Read-only.
"""
import json, logging, os, sys, time, uuid, warnings
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [analyzer] %(message)s")
log = logging.getLogger(__name__)

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
OHLC_CACHE_PATH = STATE_DIR / "price_ohlc_cache.json"


# ── Finviz Chart ────────────────────────────────────────────────────────────

def get_finviz_chart_url(symbol: str, timeframe: str = "d") -> str:
    """Get Finviz chart URL. timeframe: d=daily, w=weekly, m=monthly."""
    return f"https://charts2.finviz.com/chart.ashx?t={symbol}&ty=c&ta=1&p={timeframe}&s=l"


def get_finviz_chart_urls(symbol: str) -> Dict[str, str]:
    """Get daily + weekly chart URLs for a symbol."""
    return {
        "daily": get_finviz_chart_url(symbol, "d"),
        "weekly": get_finviz_chart_url(symbol, "w"),
    }


# ── Technical Context Builder ───────────────────────────────────────────────

def build_technical_context(symbol: str, entry_date: str, entry_price: float,
                            ohlc: Dict) -> Dict:
    """Build technical context at the time of entry using OHLC data."""
    bars = ohlc.get(symbol, {})
    if not bars:
        return {"available": False, "reason": "no OHLC data"}

    dates = sorted(bars.keys())
    # Find entry position
    entry_idx = None
    for i, d in enumerate(dates):
        if d >= entry_date:
            entry_idx = i
            break
    if entry_idx is None or entry_idx < 20:
        return {"available": False, "reason": "insufficient history before entry"}

    # Pre-entry bars (20 days before)
    pre_bars = [(dates[j], bars[dates[j]]) for j in range(max(0, entry_idx - 20), entry_idx)]
    closes = [b["c"] for _, b in pre_bars]
    highs = [b["h"] for _, b in pre_bars]
    lows = [b["l"] for _, b in pre_bars]

    if len(closes) < 14:
        return {"available": False, "reason": "insufficient bars for indicators"}

    # RSI-14
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [abs(min(d, 0)) for d in deltas]
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = round(100 - (100 / (1 + rs)), 1)

    # SMA 20 distance
    sma20 = sum(closes[-20:]) / min(20, len(closes))
    sma20_dist = round((entry_price - sma20) / sma20 * 100, 2)

    # ATR-14
    atr_vals = []
    for i in range(1, min(15, len(pre_bars))):
        h = pre_bars[i][1]["h"]
        l = pre_bars[i][1]["l"]
        pc = pre_bars[i-1][1]["c"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        atr_vals.append(tr)
    atr = round(sum(atr_vals) / len(atr_vals), 4) if atr_vals else 0
    atr_pct = round(atr / entry_price * 100, 2) if entry_price > 0 else 0

    # Recent high/low (20 days)
    high_20d = max(highs) if highs else entry_price
    low_20d = min(lows) if lows else entry_price
    range_position = round((entry_price - low_20d) / (high_20d - low_20d) * 100, 1) if high_20d != low_20d else 50

```
