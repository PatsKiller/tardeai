# Task 11 — Phase 4 Verification Report
## Smart Cache Invalidation

**Date:** 2026-04-20
**Verifier:** Claude Opus 4.6
**Files changed:** `scripts/portfolio_orchestrator.py`, `scripts/portfolio_ai_analyst.py`, `scripts/portfolio_server.py`

---

## 1. Code Block Evidence

### Holdings hash in freshness manifest (portfolio_orchestrator.py)
```python
        import time as _time, hashlib as _hl
        # Holdings hash: deterministic signature of portfolio composition
        _h_tuples = sorted(
            (h.get("symbol",""), h.get("account",""), round(h.get("shares",0) or 0, 4))
            for h in portfolio.get("holdings", [])
            if (h.get("market_value") or 0) > 100
        )
        _holdings_hash = _hl.md5(str(_h_tuples).encode()).hexdigest()[:12]
        _freshness = {
            ...
            "holdings_hash": _holdings_hash,
            ...
        }
```

### AI section cache with holdings_hash (portfolio_ai_analyst.py)

**`_save_cache` now stores holdings_hash:**
```python
def _save_cache(state_dir: Path, key: str, text: str):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    h_hash = _current_holdings_hash(state_dir)
    (Path(state_dir) / f"ai_{key}.json").write_text(
        json.dumps({"key":key,"text":text,"ts":datetime.now().isoformat(),
                    "holdings_hash":h_hash},indent=2))
```

**`_should_refresh` checks holdings_hash:**
```python
def _should_refresh(state_dir: Path, key: str, max_days: int = 30) -> bool:
    f = Path(state_dir) / f"ai_{key}.json"
    if not f.exists(): return True
    try:
        d = json.loads(f.read_text())
        # Time-based: refresh if older than max_days
        age = (datetime.now() - datetime.fromisoformat(d.get("ts","2000-01-01"))).days
        if age >= max_days:
            return True
        # Holdings-change-based: refresh if portfolio composition changed
        cached_hash = d.get("holdings_hash", "")
        if cached_hash and cached_hash != _current_holdings_hash(state_dir):
            return True
        return False
    except: return True
```

### Personal write invalidation (portfolio_server.py)
```python
        # Invalidate AI caches that depend on personal situation (Phase 4)
        try:
            _sd = PROJECT_ROOT / "data" / "portfolios" / "state"
            for _stale in ["ai_roth_conversion.json", "ai_analysis_cache.json"]:
                _sf = _sd / _stale
                if _sf.exists():
                    _sf.unlink()
            print(f"  [personal] Invalidated AI caches (Roth + analysis)")
        except Exception:
            pass
```

---

## 2. Freshness Manifest with Holdings Hash

### Command
```
$ .venv/bin/python3 scripts/portfolio_orchestrator.py --project-root . --run-label test --run-type daily
  [freshness] ✅ Manifest written (20260420-131733, hash=ea4ff1a05707)
```

### _freshness.json contents
```json
{
  "run_id": "20260420-131733",
  "completed_at": "2026-04-20T13:17:33.342924",
  "holdings_as_of": "2026-04-20",
  "holdings_repriced": "2026-04-20 13:13:18 ET",
  "holdings_hash": "ea4ff1a05707",
  "steps_completed": 10,
  "pipeline_duration_seconds": 273.3,
  "run_type": "daily",
  "status": "fresh"
}
```

---

## 3. Holdings-Change Invalidation Logic

### Test: matching hash → no refresh needed
```python
# Cache saved with current hash "ea4ff1a05707"
_should_refresh(state_dir, 'test_cache_validation', 30)  → False
```

### Test: different hash → refresh needed
```python
# Cache with old hash "old_hash_123" vs current "ea4ff1a05707"
_should_refresh(state_dir, 'test_stale', 30)  → True
```

### Backward compatibility: no hash in old cache → no forced refresh
```python
# Existing caches from April 19 have holdings_hash=MISSING
# Logic: if cached_hash is empty (""), skip hash check → falls through to age check only
_should_refresh(state_dir, 'deep_holdings', 30)  → False  (age=1 day, no hash to compare)
```

**Once caches are re-generated (with hash), future composition changes will trigger invalidation.**

---

## 4. Personal Write Invalidation

### Before write
```
-rw-rw-r-- 1 johnclaw johnclaw 27827 Apr 20 00:03 ai_analysis_cache.json
-rw-rw-r-- 1 johnclaw johnclaw  4407 Apr 19 13:45 ai_roth_conversion.json
```

### Trigger
```
$ curl -X POST http://127.0.0.1:7777/api/personal/write \
  -H "Content-Type: application/json" \
  -d '{"updates": {"roth_conversion_ytd_2026": 35000}}'
→ changes: 1
```

### After write
```
ls: cannot access 'ai_roth_conversion.json': No such file or directory
ls: cannot access 'ai_analysis_cache.json': No such file or directory
```

**Both files deleted. Next pipeline run will regenerate with fresh personal data.**

---

## 5. Explicit Statements

### Caches now invalidated by holdings changes (via holdings_hash):
- `ai_deep_holdings.json`
- `ai_dividend_strategy.json`
- `ai_bond_strategy.json`
- `ai_ira_opportunities.json`
- `ai_v_strategy.json`
- `ai_defense_analysis.json`
- `ai_roth_conversion.json`

(Takes effect after next cache re-generation writes the hash)

### Caches now invalidated by personal writes:
- `ai_roth_conversion.json` (deleted immediately)
- `ai_analysis_cache.json` (deleted immediately → forces full re-generation next run)

### Expensive caches unchanged in this pass:
- `price_cache.json` (2.5M, Yahoo rate-limited) — unchanged
- `ticker_enrichment_cache.json` (Finviz Elite rate-limited) — unchanged
- `finviz_quote_cache.json` (live market data) — unchanged

### Stale-risk scenarios remaining for future work:
- Mid-day reprice→stops/signals divergence (tradeai-reprice.timer at 09:00)
- Dead tickers lingering in finviz_quote_cache after position sold
- Old caches without holdings_hash won't auto-invalidate until re-generated
- Cross-cache consistency (pipeline crash leaves partial state)

---

## 6. Acceptance Criteria

| Criterion | Result |
|-----------|--------|
| `_freshness.json` now includes holdings_hash | **PASS** — `ea4ff1a05707` |
| AI section caches store holdings_hash metadata | **PASS** — `_save_cache` includes it |
| AI section cache refresh logic invalidates on holdings change | **PASS** — different hash → `True` |
| Personal write invalidates Roth/personal advice caches | **PASS** — both files deleted |
| Implementation stayed minimal and backward compatible | **PASS** — old caches without hash still work (age-only check) |
