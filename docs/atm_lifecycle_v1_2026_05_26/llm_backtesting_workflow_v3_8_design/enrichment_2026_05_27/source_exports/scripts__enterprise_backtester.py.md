# Source: scripts/enterprise_backtester.py (25281 bytes)
```python
#!/usr/bin/env python3
"""enterprise_backtester.py — Real price-replay backtesting engine.

Replays actual daily OHLC bars against historical signals and proposals.
No probability simulation. Deterministic results from real price data.

Modes:
  --replay-trades     Replay trades we actually took (journal ground truth comparison)
  --replay-proposals  Replay proposals we generated but didn't trade
  --strategy X        Filter to one strategy
  --exclude-scalps    Skip momentum_scalp unless actually traded (default: on)
  --days N            Max hold period before timeout exit (default: 20)
  --apply             Write results to DB

No live trading. No broker calls. Read-only on market data.
"""
import argparse, json, logging, os, sys, time, uuid, warnings
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [backtester] %(message)s")
log = logging.getLogger(__name__)

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
OHLC_CACHE_PATH = STATE_DIR / "price_ohlc_cache.json"
CLOSE_CACHE_PATH = STATE_DIR / "price_cache.json"

SCALP_STRATEGIES = {"momentum_scalp", "gap_and_go", "social_scalp"}


# ── Data Loaders ────────────────────────────────────────────────────────────

def load_ohlc_cache() -> Dict:
    """Load OHLC cache. Falls back to close-only with degraded confidence."""
    if OHLC_CACHE_PATH.exists():
        return json.loads(OHLC_CACHE_PATH.read_text())
    return {}


def load_close_cache() -> Dict:
    """Load close-only price cache."""
    if CLOSE_CACHE_PATH.exists():
        raw = json.loads(CLOSE_CACHE_PATH.read_text())
        # Remove meta keys
        return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}
    return {}


def fetch_ohlc_for_symbols(symbols: List[str], start: str, end: str) -> Dict:
    """Fetch OHLC from yfinance and cache. Returns {symbol: {date: {o,h,l,c,v}}}."""
    import yfinance as yf
    warnings.simplefilter("ignore")

    ohlc = load_ohlc_cache()
    missing = [s for s in symbols if s not in ohlc or not ohlc[s]]

    if missing:
        log.info(f"Fetching OHLC for {len(missing)} symbols...")
        for sym in missing:
            try:
                hist = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True, threads=False)
                if hist.empty:
                    continue
                # Flatten MultiIndex
                if hasattr(hist.columns, "levels"):
                    hist.columns = [c[0] for c in hist.columns]
                bars = {}
                for idx, row in hist.iterrows():
                    d = str(idx.date()) if hasattr(idx, "date") else str(idx)[:10]
                    bars[d] = {
                        "o": round(float(row.get("Open", row.get("Close", 0))), 4),
                        "h": round(float(row.get("High", row.get("Close", 0))), 4),
                        "l": round(float(row.get("Low", row.get("Close", 0))), 4),
                        "c": round(float(row.get("Close", 0)), 4),
                        "v": int(row.get("Volume", 0)),
                    }
                ohlc[sym] = bars
                time.sleep(0.3)
            except Exception as e:
                log.warning(f"OHLC fetch failed for {sym}: {e}")

        # Persist cache
        OHLC_CACHE_PATH.write_text(json.dumps(ohlc, separators=(",", ":")))
        log.info(f"OHLC cache updated: {len(ohlc)} symbols")

    return ohlc


def get_trades_from_db() -> List[Dict]:
    """Get closed paper trades + real trades for replay."""
    from db_adapter import _get_conn
    import psycopg2.extras
    conn = _get_conn()
```
