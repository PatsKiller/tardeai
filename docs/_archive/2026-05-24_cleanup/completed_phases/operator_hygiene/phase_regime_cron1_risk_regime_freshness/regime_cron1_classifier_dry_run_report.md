# REGIME-CRON-1 Classifier Dry Run

## Command
```
.venv/bin/python scripts/market_regime_classifier.py --dry-run --json
```

## Result
```json
{
  "mode": "dry_run",
  "regime_label": "high_volatility",
  "regime_score": 3,
  "confidence": 0.43,
  "volatility_state": "high_vol",
  "trend_state": "bearish",
  "breadth_state": "narrow",
  "stale_data": false,
  "missing_data": [],
  "inputs": {
    "vix_close": "normal",
    "scan_breadth_24h": "narrow",
    "scan_score_avg": "bearish",
    "gap_volatility_proxy": "high_vol",
    "finviz_health": "risk_on",
    "news_sentiment_proxy": "neutral",
    "market_session": "neutral"
  }
}
```

## Assessment
- 7 indicators available (sufficient)
- No missing data
- Classification: high_volatility at 43% confidence
- No trades, orders, or strategy changes
- Safe to proceed with apply
