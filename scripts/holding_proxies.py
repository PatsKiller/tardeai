"""holding_proxies.py — public-ETF proxies for non-tradeable holdings (single source of truth).

401k commingled pools / institutional mutual funds have no public ticker, so direct technicals are
impossible. Each entry maps a holding code → (proxy_etf, asset-class label). Proxies approximate the
holding's ASSET CLASS, not the exact fund — every consumer must surface a "(proxy)" label.

Consumers: api_v2 portfolio holdings enrichment (RSI* display) · technicals_gap_backfill (writes
proxy-computed RSI/SMA into ticker_snapshot_daily under the fund code, source='proxy:<ETF>') —
which feeds Open Trades position intelligence and the LLM protection advisor pipeline.
"""

HOLDING_PROXY_MAP = {
    "FID-CONTRA-F":  ("SCHG", "US large-cap growth"),
    "FCNTX":         ("SCHG", "US large-cap growth"),
    "JPM-LGCG":      ("SCHG", "US large-cap growth"),
    "SP500-D":       ("SPY",  "S&P 500"),
    "VANG-FTSE-SOC": ("SPY",  "US large-cap blend (ESG)"),
    "TRP-LVAL":      ("SCHD", "US large-cap value"),
    "AMANX":         ("SCHD", "US large-cap value / dividend"),
    "SS-SMMD":       ("IJH",  "US mid-cap blend"),
    "WM-BLAIR":      ("IWP",  "US mid-cap growth"),
    "AB-DISC-Z":     ("IWN",  "US small-cap value"),
    "FID-DIVINTL":   ("VXUS", "international ex-US equity"),
    "SS-GACEQ":      ("VXUS", "global ex-US equity"),
}
