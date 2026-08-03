# Re-Entry data + LLM/critics fixes (2026-08-03)

Operator-facing summary of issues found on Command Center v3 Re-Entry / Watch desks, root causes, fixes, and live status.

## Status: **fixed and live** (as of commits through `da13ba2e`)

| Area | Issue | Fixed? | How |
|------|--------|--------|-----|
| Re-Entry hard error `ENOENT …indicator_snapshot.json.tmp` | Concurrent desk refresh raced on one shared temp file | **Yes** | Unique temp names + soft publish (`lib/data_broker/atomic_json.py`) |
| Quotes “3d old” / resistance “3d old” | Friday close held over weekend; **resistance had no cron** and sat at Jul 31 | **Yes** | Resistance rebuilt 2026-08-03; cron 08:15 + 17:30 weekdays; health monitors + auto-remediate |
| READY = 0 / MISSING PLAN | Exit universe never got entry plans; wash/held/R gates | **Partial** | Health flags `reentry_entry_plan_gap`; plans still mainly watchlist-scoped (by design gap remaining) |
| Desk not on Data Broker | Per-row `get_best_quote` bypassed batch broker read model | **Yes** | Quotes via `market_quote.get_price_batch`; payload `data_broker.enforced: true` |
| DeepSeek “not working” | UI omitted lanes; multi-lane hang; gate silent no-op; v4 empty JSON | **Yes** | See commits below |
| Agents using Pro | `llm_router` / CIO synthesis defaulted to deepseek-v4 | **Yes** | Flash-first policy + timers |

---

## 1. Re-Entry desk hard error (ENOENT)

**Symptom:** Red banner  
`[Errno 2] No such file or directory: …/indicator_snapshot.json.tmp → …/indicator_snapshot.json`

**Cause:** Two concurrent refreshes wrote the same `*.json.tmp` and `Path.replace` raced.

**Fix:** `scripts/lib/data_broker/atomic_json.py` — unique temp (`pid` + random); soft write so cache failure does not 500 the desk. Used by indicator / portfolio / sector snapshots.

**Commit:** `a3e9d4c6`

---

## 2. Stale quotes / resistance / empty READY

### Quotes “3d old”
- Last Alpaca print for many names was **Fri 2026-07-31 20:00** (session close).
- Viewed **Mon morning** before/around open → age reads ~2–3d.
- Intraday quote cron: `*/15 9–16 weekdays`. Not a wiped table.
- After open + ingest, desk showed **~0.05h** age via Data Broker.

### Resistance “3d old”
- `ui_prefs.portfolio.reentry.resistance.v1` last updated **2026-07-31**.
- **No scheduled rebuild** after that; health agent did not watch this key.
- **Fix:** rebuilt live (108 symbols, `generated_at` 2026-08-03); `scripts/refresh_reentry_resistance.py`; cron Mon–Fri **08:15 & 17:30**; health findings `reentry_resistance_cache_stale|missing` + auto-remediation.

**Commit:** `333c0f46`

### MISSING PLAN / READY = 0
Not a random data wipe:
- **MISSING PLAN** = no row in `watchlist_entry_plans` with zone/stop for that exit symbol.
- Entry planner cron targets **watchlist / MAIN / proposals**, not the full 107-exit universe.
- READY also needs: zone, RSI 40–70, fresh quote, resistance reclaimed, wash clear, not currently held, R:R/stop confirmations.
- **SCHG** example: held + wash until 2026-08-16 → correct **Monitor / No Action**.

Health now emits `reentry_entry_plan_gap` when many exits lack plans. Full exit-universe planner batch is still a product follow-up.

---

## 3. Data Broker enforcement (Re-Entry)

**Before:** Desk used Data Broker for indicators/plans/profiles, but quotes were **per-symbol `get_best_quote`**.

**After (`da13ba2e`):**
- Quotes → `lib.data_broker.market_quote.get_price_batch` (`market_quotes` primary).
- Indicators → `indicator_snapshot`
- Plans → `entry_plan`
- Book/heat → `portfolio_snapshot`
- Profiles/catalysts → symbol_profile / catalyst_record
- Resistance → closed-session ui_prefs cache

API returns:

```json
"version": "reentry-decision-desk-v2-data-broker",
"llm_in_path": false,
"data_broker": { "enforced": true, "modules": { ... } }
```

**LLM never sets READY/NEAR/BLOCK** (desk contract unchanged).

---

## 4. DeepSeek / critics / agents (Watch MAIN)

| Issue | Cause | Fix commit |
|-------|--------|------------|
| DeepSeek not in UI strip | Ticket projection only local/grok/chatgpt | `c123badd`, `d5cf0abf` |
| “Queued, nothing happens” | Grok hang; persist only at end of multi-lane job | `950f20e4` per-lane persist + timeouts |
| v4 = UNAVAILABLE | Reasoner empty / non-JSON | `a41a43f7` chat JSON retry |
| AAPL infinite poll | Deterministic NOT RUN — critics correctly blocked, UI lied | `0aea0294` gate + entry-plan CTA |
| v4 looks dead for 90s | Slow job + no live overlay | `afcf6bca` RUNNING overlay + 200s poll |
| Agents on Pro | `llm_router` / CIO default v4 | `eed471bc`, `1f909caf` Flash-first |

**Agents now use:** DeepSeek Flash (`deepseek-chat`) via `llm_router` + `llm_route_policy`.  
**Pro (v4) only:** operator desk button, Paid…, `USE_PRO=1`, premium/meta escalation.

**Flash cadences (live timers):**
- Watchlist critics: weekdays 09:30  
- Portfolio risk-ish: hourly 07–19 weekdays; weekends 10:00  
- LLM intelligence: 07:20 / 12:20 / 16:20 weekdays  

Docs: `config/systemd/flash-cadence/README.md`, `scripts/lib/llm_route_policy.py`.

---

## 5. Health agent coverage (updated)

| Finding | Meaning | Auto-remediation |
|---------|---------|------------------|
| `reentry_indicator_cache_*` | RSI cache for exits | `data_broker_indicator_refresh --operator-desks` |
| `reentry_resistance_cache_*` | Resistance prefs stale/missing | `refresh_reentry_resistance.py` |
| `reentry_entry_plan_gap` | Many exits without zones | Entry planner batch (watchlist-oriented) |
| `market_quotes_stale` | Live quotes stale | `external_market_data_ingest --quotes` |
| `watch_main_entry_zone_gap` / `ticket_not_run` | MAIN no plan/ticket | planner + decision scheduler |

Policy: `config/health_agent_policy.json`.

---

## 6. How to verify live

```bash
# Re-Entry desk provenance + freshness
curl -s 'http://127.0.0.1:7777/api/v2/reentry/decision-desk?symbols=SCHG,AAPL' | \
  python3 -c "import sys,json;d=json.load(sys.stdin)['data'];print(d['version'], d['data_broker'], d['freshness']['resistance_generated_at'])"

# Flash policy
PYTHONPATH=scripts:scripts/lib python -c "from llm_route_policy import resolve_lane; print(resolve_lane(None, process_id='agent'))"

# Flash timers
systemctl --user list-timers | grep flash
```

UI footer for Flash policy SPA: `3.14+mscqldsu` (hard-refresh if older).

---

## Remaining product debt (not “broken wipe”)

1. **Exit-universe entry plans** — still not systematically planned for all 107 exits → many `MISSING PLAN` remain until a dedicated reentry planner scope runs.  
2. **Mon pre-open quotes** — will age Fri→Mon until 09:00 quote cron; expected.  
3. **LLM does not critique Re-Entry READY** — by design; do not expect Flash to fill plans or set READY.

---

## Key commits (newest first)

- `da13ba2e` — Re-Entry Data Broker enforcement + provenance  
- `333c0f46` — Resistance refresh + health for resistance/plan gap  
- `a3e9d4c6` — Atomic snapshot write race  
- `1f909caf` / `eed471bc` — Agents/fleet Flash-first  
- `0aea0294` / `950f20e4` / `a41a43f7` / `d5cf0abf` — Watch DeepSeek critics reliability + UI  
