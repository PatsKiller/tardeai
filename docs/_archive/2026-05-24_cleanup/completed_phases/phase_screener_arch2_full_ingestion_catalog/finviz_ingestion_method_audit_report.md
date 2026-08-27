# FinViz Ingestion Method Audit

## Method: FinViz Elite CSV Export

The system uses `elite.finviz.com/export?` endpoint which returns a complete CSV
containing ALL matching rows. Authentication via cookie from `config/youtube_cookies.txt`
(note: misleadingly named file contains FinViz session cookie).

### Flow

1. `finviz_screener_runner.py` converts screener URL to `/export?` endpoint
2. Downloads entire CSV in single HTTP request (no pagination)
3. Parses CSV for ticker symbols (column 1 = "No.", column 2 = "Ticker")
4. HTML fallback if CSV fails (scrapes `quote.ashx?t=` links)
5. `finviz_ingestion.py` handles enrichment with v=152 custom columns

### Key Facts

| Aspect | Detail |
|--------|--------|
| Endpoint | `elite.finviz.com/export?` |
| Auth | Cookie-based (FinViz Elite subscription) |
| Response | Complete CSV, all rows, single request |
| Pagination | Not needed — CSV is complete |
| Version | v=152 (Elite custom columns) |
| Columns | 0,1,2,3,4,5,6,7,25,61,63,64,65,66,67 |
| Rate limit | 429 → retry 3x with 5s delay |
| Cookie expiry | Detected → Telegram alert |
| Fallback | HTML scraping via regex |

### Previous Bottlenecks (Now Fixed)

| Bottleneck | Old Value | New Value |
|------------|-----------|-----------|
| Row cap per screener | 50 | No cap (5000 emergency) |
| New ticker cap per screener | 10 | 200 |

### Data Loss Points (Fixed)

1. `tickers[:50]` — was discarding 95%+ of results. **FIXED.**
2. `new_tickers[:10]` — was limiting incubator additions. **FIXED (raised to 200).**
