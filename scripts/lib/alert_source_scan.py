"""Static scan: where does each operator-alert producer get its data?

Operator rule 2026-10-05: the Command Center is the source of truth for every alert; data is
refreshed through its data broker, never fetched by the producer itself. This classifies each file
that sends an operator alert by the data access it contains (pattern match on source text):

  provider  — calls a market-data provider directly (Yahoo/yfinance, Finviz, Alpaca, Schwab
              client, Alpha Vantage, Polygon, Finnhub, raw HTTP to a provider, or the provider
              waterfall get_best_quote outside the broker)
  broker    — reads through lib.data_broker / lib.alert_quotes
  cc_api    — reads the Command Center HTTP API (127.0.0.1:7777)
  cc_store  — reads Command Center stores directly (SQL / state files), no provider call

Used by tests/test_alert_single_source_20261005.py (ratchet) and the inventory doc.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SEND = re.compile(r"\b(send_telegram|deliver_notice|telegram_send|send_operator_alert|deliver_text|tg_send|_send_telegram)\s*\(")
PROVIDER = {
    "yahoo": re.compile(r"\byfinance\b|query[12]\.finance\.yahoo\.com|finance\.yahoo\.com/v\d"),
    "finviz": re.compile(r"elite\.finviz\.com|finviz\.com/(export|screener|quote\.ashx\?[^\"']*&)|\bfinvizfinance\b|finviz_client\.|fetch_finviz"),
    "alpaca": re.compile(r"data\.alpaca\.markets|alpaca_trade_api|alpaca\.data\.|StockHistoricalDataClient"),
    "schwab": re.compile(r"\bschwab_transport\.(get_quotes?|get_price_history|get_option_chain|get_movers)|\bfrom schwab\.client\b|build_client\("),
    "alphavantage": re.compile(r"alphavantage\.co"),
    "polygon": re.compile(r"api\.polygon\.io"),
    "finnhub": re.compile(r"finnhub\.io"),
    "waterfall": re.compile(r"\bget_best_quote\s*\("),
    "moomoo": re.compile(r"\bOpenQuoteContext\b|\bfutu\b|\bmoomoo\b"),
}
BROKER = re.compile(r"lib\.data_broker|data_broker\.|from lib import data_broker|lib\.alert_quotes|alert_quotes import")
CC_API = re.compile(r"127\.0\.0\.1:7777|localhost:7777|/api/v[23]/")
CC_STORE = re.compile(r"\bcur\.execute\(|db_query\(|_db_query\(|\.read_text\(|json\.load\(")

#: The broker's own provider adapters are the refresh path, not a bypass.
BROKER_INTERNAL_PREFIXES = ("scripts/lib/data_broker/", "scripts/lib/writers/")


def producers(root: Path | None = None) -> list[Path]:
    root = root or ROOT
    out = []
    for p in sorted((root / "scripts").rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if "/tests/" in rel or rel.startswith(BROKER_INTERNAL_PREFIXES):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if SEND.search(text):
            out.append(p)
    return out


def classify_text(text: str) -> dict:
    providers = sorted(k for k, rx in PROVIDER.items() if rx.search(text))
    return {
        "providers": providers,
        "broker": bool(BROKER.search(text)),
        "cc_api": bool(CC_API.search(text)),
        "cc_store": bool(CC_STORE.search(text)),
        "class": "provider" if providers else ("broker" if BROKER.search(text) else (
            "cc_api" if CC_API.search(text) else ("cc_store" if CC_STORE.search(text) else "none"))),
    }


def inventory(root: Path | None = None) -> list[dict]:
    root = root or ROOT
    rows = []
    for p in producers(root):
        text = p.read_text(encoding="utf-8", errors="replace")
        rows.append({"file": p.relative_to(root).as_posix(), **classify_text(text)})
    return rows


#: Files that match a provider pattern but are not alert data reads (named in the inventory doc).
NOT_A_DATA_READ = {
    "scripts/api_v2.py": "the Command Center API server itself (hosts the broker endpoints)",
    "scripts/run_cio_hardening_ci.py": "CI runner; 'moomoo' appears in gate names only",
    "scripts/secrets_admin.py": "secret names only (MOOMOO_* keys)",
    "scripts/credential_monitor.py": "credential health probe — tests provider reachability by design",
    "scripts/finviz_health_check.py": "Finviz health probe — tests provider reachability by design",
    "scripts/moomoo/opend_health.py": "OpenD health probe — tests gateway reachability by design",
}

_IMPORT = re.compile(r"^\s*(?:from\s+(?:scripts\.)?(lib\.[\w.]+|[\w]+)\s+import|import\s+(?:scripts\.)?(lib\.[\w.]+|[\w]+))", re.M)


def imported_providers(text: str, root: Path | None = None) -> list[str]:
    """Providers reached one import level down (scripts/<mod>.py or scripts/lib/<mod>.py)."""
    root = root or ROOT
    found: set[str] = set()
    for m in _IMPORT.finditer(text):
        mod = (m.group(1) or m.group(2) or "").replace(".", "/")
        p = root / "scripts" / f"{mod}.py"
        if not p.is_file() or p.as_posix().startswith(str(root / "scripts/lib/data_broker")):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found |= {k for k, rx in PROVIDER.items() if rx.search(t)}
    return sorted(found)
