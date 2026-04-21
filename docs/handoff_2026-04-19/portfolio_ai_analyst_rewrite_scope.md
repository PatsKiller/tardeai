# portfolio_ai_analyst.py — Rewrite Scope

**Status:** File audited April 17 2026 evening. Tonight's Ollama fix solved duplicate content but revealed deeper structural issues: hardcoded stale numbers in prompts, dead code, no cross-run aggregation, and model-tier routing that doesn't yet exist.

**Goal:** Make the file accurate, self-updating when portfolio changes, and properly tiered across Ollama (weekly) / Sonnet (monthly) / Opus (flagship monthly).

**Total effort:** 11-17 hours for Phases 0-5 (reliability baseline). Phase 6 (MPT/Black-Litterman/Monte Carlo) adds 15-20 hours. Phase 7 (ETF intelligence + AI integration) adds 10-14 hours. Each phase is independently verifiable. Stop at any phase without breaking the system.

---

## Background: What's wrong with the current file

Read the file at `scripts/portfolio_ai_analyst.py` (766 lines). Specific issues found:

### Issue 1: Hardcoded numbers in prompts

These values are baked into prompt text and go stale the moment portfolio changes:

**`_portfolio_context()` function (lines 260-335):**
- Line 269-272: Income sources hardcoded ($3,800/mo SSDI, $20K Schedule C)
- Line 275-278: Filing/itemization numbers hardcoded
- Line 280-282: Mortgage balance and date
- Line 290-301: Tax math table with specific 2026 numbers
- Line 304-307: Account values hardcoded ($501,155 / $531,268 / $40,422 / $71,773) — these are stale snapshots, live values are different
- Line 305: Contains two mixed-meaning numbers: "V=49.6% of this account" (stale concentration number — real value is ~28% of that account, and total portfolio V is actually only 15.9%) AND "+702% unrealized gain" (historical gain on position since purchase, not a concentration). Ollama reads these two unrelated numbers, gets confused about which is which, and produces hallucinations like "491% gain" or "V concentration 49%." Both the data staleness AND the semantic confusion (concentration vs. gain) need fixing.
- **Important clarification for the rewrite:** V position is 15.9% of total portfolio (12.5% Rollover + 3.4% Roth). The Signals engine reports this correctly. The +702% figure, if it exists at all, is a historical gain on purchase price — NOT a current portfolio metric. Prompts must clearly distinguish "concentration %" from "unrealized gain %" to prevent the mix-up.

**`_roth_conversion_analysis()` (lines 365-424):**
- Line 362-364: Account value defaults hardcoded
- Line 368-371: Income picture repeated
- Line 375-379: Tax math repeated

**`_v_strategy()` (lines 533-590):**
- Line 544-553: V business facts (Visa volume, margins, price target)
- Line 556-562: Rotation options hardcoded

**`_defense_analysis()` (lines 608-648):**
- Line 614-617: Strategy description hardcoded
- Line 618-619: Specific holdings with specific dollar values

**Impact:** When portfolio value shifts from $1,201K to $1,206K, the AI output still cites $1,201K because it's baked into the prompt string. When V concentration drops to 14%, the prompt still says "49.6%" and the AI dutifully writes analysis of a 49% position that no longer exists.

### Issue 2: Duplicate __main__ block

Lines 733-748 and 750-765 are identical. Second block is dead code from a copy-paste accident. Harmless but shows file has been edited without cleanup.

### Issue 3: Dead code in `_exec_summary`

Lines 428-439 are unreachable — they come after a `return` statement at line 356. Leftover from a refactor.

### Issue 4: No weekly-to-monthly aggregation

Monthly runs do not read prior weekly reports. They run fresh each time, generating analysis from current state with no awareness of what changed during the month. A monthly report should synthesize what happened across 4 weekly reports.

### Issue 5: Only two model tiers

Current routing: Ollama (weekly) OR Sonnet (monthly). No Opus tier for monthly flagship content. Haiku is referenced for Exec Summary but the file uses `HAIKU = "claude-haiku-4-5-20251001"` which is fine.

### Issue 6: qwen3:1.7b is too small for financial reasoning

Even with clean prompts, 1.7B parameters hallucinates specific numbers confidently. This is why you saw "491% gain" and "Visa 49%" in today's output despite the Ollama fix. A bigger model (qwen3:8b or qwen3:14b) on GPU will reduce this but not eliminate it.

### Issue 7: Cache invalidation is time-based only

`_should_refresh(state_dir, key, max_days=30)` only regenerates if 30 days have passed. No mechanism to invalidate when portfolio composition changes significantly (new position added, large rebalance executed, big drawdown).

### Issue 8: No single source of truth, no freshness verification

The portfolio data the AI analyzes lives across multiple JSON files (`holdings.json`, `ai_analysis_cache.json`, `risk_management.json`, `rebalance_suggestions.json`, etc.) that are updated by different pipelines at different times. No mechanism currently:

- Verifies all state files were generated from the same portfolio snapshot
- Checks how old the underlying holdings data is before running AI analysis
- Cross-validates account totals against known broker balances
- Refuses to run analysis on stale or inconsistent data

**Real-world failure mode:** Monday's pipeline runs holdings refresh but fails on signals generation. Thursday you manually run the signals script, which reads Monday's holdings + Thursday's live prices. Friday the monthly report runs against this mix. Output cites stale positions with current prices — looks plausible, is subtly wrong.

**What's needed:** A "freshness gate" that runs before any AI analysis and either (a) triggers a fresh data pull, or (b) refuses to run and alerts you that data needs refreshing. This is the foundation for everything else in the rewrite.

---

## Phase 0: Data freshness gate and single source of truth

**Effort:** 3-5 hours  
**Risk:** Low (adds checks, doesn't change existing logic)  
**Acceptance:** Running `portfolio_ai_analyst.py` against stale data produces a clear warning or refusal, not quietly-wrong output. A `refresh_portfolio_data.sh` script exists that pulls fresh holdings from all sources in one command.

### Why this comes first

Phases 1-6 all assume the underlying portfolio data is correct and current. If `holdings.json` is from Monday and you run AI analysis on Friday, the output will cite Monday positions with confidence. The "hardcoded numbers" problem in Phase 1 is actually TWO problems layered: (1) hardcoded literals in prompts, and (2) even the "live" JSON inputs may themselves be stale.

You need to fix freshness first, THEN remove hardcoded numbers. Doing it in reverse produces a system that dutifully reads its stale inputs and confidently outputs the wrong answer.

### Substeps

**0.1 Inventory all state files and their update cadence.** Create an audit table:

| State file | Produced by | Expected freshness | Consumed by |
|---|---|---|---|
| `data/portfolios/state/holdings.json` | `portfolio_daily.py` (daily pipeline) | Same-day | All AI analysis, signals, reports |
| `data/portfolios/state/ai_analysis_cache.json` | `portfolio_ai_analyst.py` | Weekly (weekly sections) / monthly (full) | Monthly report, CC AI tab |
| `data/portfolios/state/risk_management.json` | `portfolio_risk.py` | Same-day | Signals engine, Risk tab |
| `data/portfolios/state/rebalance_suggestions.json` | `portfolio_rebalance.py` | Weekly | AI analyst, Rebalance tab |
| `data/portfolios/state/action_signals.json` | `portfolio_signals.py` | Daily (after holdings refresh) | Monthly report, CC AI tab |
| `data/portfolios/state/earnings_dates.json` | `earnings_date_enrichment.py` | Weekly | Signals Rule 11 |

Audit what exists, what refreshes when, and what uses what. Document gaps.

**0.2 Create `scripts/refresh_portfolio_data.sh` (or .py).** Single entry point that pulls fresh data in the right order:

```bash
#!/bin/bash
# Run this before any AI analysis to ensure fresh data
set -e  # exit on any failure

echo "[refresh] Starting portfolio data refresh..."
cd ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
source .venv/bin/activate

# Step 1: Pull latest holdings from brokers (if automated) or from CSV imports
echo "[refresh] Step 1: Holdings refresh..."
python3 scripts/portfolio_daily.py --refresh-holdings || { echo "FAIL: holdings refresh"; exit 1; }

# Step 2: Update prices for all tickers
echo "[refresh] Step 2: Price cache..."
python3 scripts/price_cache.py --refresh || { echo "FAIL: price cache"; exit 1; }

# Step 3: Recompute portfolio totals, gains, concentrations
echo "[refresh] Step 3: Portfolio math..."
python3 scripts/portfolio_totals.py || { echo "FAIL: totals"; exit 1; }

# Step 4: Risk management (stops, heat, escalation)
echo "[refresh] Step 4: Risk..."
python3 scripts/portfolio_risk.py || { echo "FAIL: risk"; exit 1; }

# Step 5: Rebalance suggestions
echo "[refresh] Step 5: Rebalance..."
python3 scripts/portfolio_rebalance.py || { echo "FAIL: rebalance"; exit 1; }

# Step 6: Earnings dates (weekly cadence acceptable)
echo "[refresh] Step 6: Earnings..."
python3 scripts/earnings_date_enrichment.py || { echo "WARN: earnings refresh failed (non-fatal)"; }

# Step 7: Action signals (depends on all above)
echo "[refresh] Step 7: Signals..."
python3 scripts/portfolio_signals.py || { echo "FAIL: signals"; exit 1; }

# Step 8: Write a manifest proving everything refreshed together
python3 -c "
import json
from datetime import datetime
manifest = {
    'refreshed_at': datetime.now().isoformat(),
    'snapshot_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
    'files_refreshed': [
        'holdings.json', 'price_cache.json', 'portfolio_totals.json',
        'risk_management.json', 'rebalance_suggestions.json',
        'earnings_dates.json', 'action_signals.json'
    ]
}
with open('data/portfolios/state/refresh_manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)
print(f'[refresh] Done. Snapshot: {manifest[\"snapshot_id\"]}')
"

echo "[refresh] ✅ All data refreshed successfully"
```

Make executable: `chmod +x scripts/refresh_portfolio_data.sh`

**0.3 Create freshness-check function in portfolio_ai_analyst.py:**

```python
def _check_data_freshness(state_dir: Path, max_age_hours: int = 24) -> Dict:
    """
    Verify all required state files exist and are fresh enough for AI analysis.
    Returns dict with status and details.
    """
    required = {
        'holdings.json': max_age_hours,
        'ai_analysis_cache.json': max_age_hours * 7,  # weekly OK
        'risk_management.json': max_age_hours,
        'rebalance_suggestions.json': max_age_hours * 7,  # weekly OK
        'action_signals.json': max_age_hours,
    }
    
    manifest_path = state_dir / 'refresh_manifest.json'
    snapshot_id = None
    if manifest_path.exists():
        try:
            snapshot_id = json.loads(manifest_path.read_text()).get('snapshot_id')
        except:
            pass
    
    issues = []
    for filename, max_age_h in required.items():
        fp = state_dir / filename
        if not fp.exists():
            issues.append(f"MISSING: {filename}")
            continue
        age_h = (datetime.now() - datetime.fromtimestamp(fp.stat().st_mtime)).total_seconds() / 3600
        if age_h > max_age_h:
            issues.append(f"STALE: {filename} is {age_h:.1f}h old (max {max_age_h}h)")
    
    return {
        "fresh": len(issues) == 0,
        "snapshot_id": snapshot_id,
        "issues": issues,
        "checked_at": datetime.now().isoformat()
    }
```

**0.4 Add freshness gate to `run_ai_analysis`:**

```python
def run_ai_analysis(portfolio, analysis, rebalancing, state_dir, force_refresh=False, run_type="daily", root=".", allow_stale=False):
    # Check data freshness BEFORE any AI work
    freshness = _check_data_freshness(state_dir, max_age_hours=24)
    if not freshness["fresh"]:
        if not allow_stale:
            raise RuntimeError(
                f"Refusing to run AI analysis on stale/missing data.\n"
                f"Issues:\n  " + "\n  ".join(freshness["issues"]) + 
                f"\n\nRun: ./scripts/refresh_portfolio_data.sh\n"
                f"Or pass allow_stale=True to proceed anyway (output may be wrong)."
            )
        else:
            # Proceeding with warning — inject staleness warning into prompts
            print(f"  [ai] ⚠️ WARNING: Running on stale data. Issues: {freshness['issues']}")
            # Pass freshness status to prompt builders so AI can caveat appropriately
    ...
```

**0.5 Pass freshness status into prompts.** When running on stale data (if allow_stale=True), prepend to every prompt:

```
⚠️ DATA FRESHNESS WARNING: The following analysis is based on portfolio data that is X hours old.
Recent price moves, trades, or corporate actions may not be reflected.
Flag uncertainty in your output and recommend the user refresh data before acting on recommendations.
```

This lets the AI know it's working with stale inputs and caveat accordingly, rather than confidently asserting wrong things.

**0.6 Add "Last Refreshed" display to CC dashboard.** Read `refresh_manifest.json`, show at top of CC:

```
Last refreshed: 2026-04-18 09:15:32 EST (3h ago) • Snapshot: 20260418_091532
```

Color-code: green if <24h, amber 24-48h, red >48h. One click button labeled "Refresh Now" triggers `refresh_portfolio_data.sh` via API endpoint.

**0.7 Schedule automatic weekly refresh.** Add systemd timer (or cron) to run `refresh_portfolio_data.sh` every Monday at 6:00 AM:

```systemd
# ~/.config/systemd/user/portfolio-refresh.timer
[Unit]
Description=Weekly portfolio data refresh

[Timer]
OnCalendar=Mon 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```systemd
# ~/.config/systemd/user/portfolio-refresh.service
[Unit]
Description=Refresh portfolio data from all sources

[Service]
Type=oneshot
ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/scripts/refresh_portfolio_data.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

Enable: `systemctl --user enable portfolio-refresh.timer && systemctl --user start portfolio-refresh.timer`

### Files created/modified

- **NEW**: `scripts/refresh_portfolio_data.sh` — single-command refresh entry point
- **NEW**: `data/portfolios/state/refresh_manifest.json` — written after each successful refresh
- **NEW**: `~/.config/systemd/user/portfolio-refresh.timer` and `.service` — scheduled weekly refresh
- **MODIFIED**: `scripts/portfolio_ai_analyst.py` — add `_check_data_freshness()`, gate in `run_ai_analysis()`, freshness warning in prompts
- **MODIFIED**: `reports/command_center.html` — display "Last refreshed" bar at top

### Deploy gate

Three acceptance tests:

**Test 1: Normal refresh flow works.** Run `./scripts/refresh_portfolio_data.sh`, verify all steps succeed, `refresh_manifest.json` gets written with current timestamp. Then run `python3 scripts/portfolio_ai_analyst.py` — should execute without complaint.

**Test 2: Stale data is detected.** Manually set file mtime on `holdings.json` back 3 days: `touch -d "3 days ago" data/portfolios/state/holdings.json`. Run `python3 scripts/portfolio_ai_analyst.py` — should refuse with clear error message naming the stale file.

**Test 3: Weekly timer fires.** Check systemd timer status: `systemctl --user list-timers portfolio-refresh.timer`. Verify it's scheduled for next Monday 6:00 AM. After it fires (can manually trigger with `systemctl --user start portfolio-refresh.service`), verify `refresh_manifest.json` updates.

### Critical design decision: broker API vs. manual import

A real question for Phase 0: **how does the holdings data actually refresh?**

Three options:

**Option A: Manual CSV/PDF import.** You download statements from Schwab/Fidelity, drop into `/data/imports/`, pipeline parses. This is probably your current flow. Pro: simple, no API credentials. Con: requires you to remember weekly.

**Option B: Schwab/Fidelity API integration.** Schwab has an OAuth API (schwabdeveloper.com), Fidelity is harder. Pro: truly automated. Con: setup is real work, OAuth tokens expire, rate limits.

**Option C: Plaid/Yodlee aggregator.** Third-party service. Pro: covers multiple brokers uniformly. Con: monthly fee, introduces dependency, data can lag.

For Phase 0, **start with Option A automated via a pipeline that checks for new CSVs in /data/imports/ and triggers refresh if found.** Option B can come later as a separate project.

### Sub-phase 0.8: Auto-regenerate manual beta lookup list

**Why this matters:** Today's hard-coded Morningstar URL list went stale the moment it was generated. As positions are added, removed, or rebalanced, the URL list in `/tmp/morningstar_beta_lookup.txt` no longer reflects what's actually in the portfolio. Every rebalance should trigger a regeneration so the list shows which funds currently need beta lookups (and which existing overrides have gone stale).

**Implementation as part of `refresh_portfolio_data.sh`:**

```python
# New script: scripts/regenerate_beta_lookup.py
# Called from refresh_portfolio_data.sh as a post-holdings step

def regenerate_beta_lookup_list(holdings_path, overrides_path, finviz_coverage_path, output_path):
    """Regenerate /tmp/morningstar_beta_lookup.txt based on current holdings.
    
    Produces entries for:
    - New positions without Finviz beta coverage
    - Existing manual beta overrides older than 12 months (reverify)
    - Removes entries for positions no longer held
    """
    current_holdings = json.load(open(holdings_path))
    current_overrides = json.load(open(overrides_path))
    finviz_covered = set(json.load(open(finviz_coverage_path))["covered_tickers"])
    
    needed_lookups = []
    
    for holding in current_holdings["holdings"]:
        ticker = holding["symbol"]
        if ticker in finviz_covered:
            continue  # Finviz has beta, skip
        
        override_entry = current_overrides.get("overrides", {}).get(ticker)
        if override_entry and override_entry.get("beta") is not None:
            # Has manual beta - check age
            date_added = override_entry.get("date_added")
            if date_added:
                age_days = (datetime.now() - datetime.fromisoformat(date_added)).days
                if age_days > 365:
                    needed_lookups.append((ticker, "STALE", age_days))
            # Not stale, skip
        else:
            needed_lookups.append((ticker, "NEW", None))
    
    # Write the text file with URLs
    with open(output_path, 'w') as f:
        f.write("MORNINGSTAR BETA LOOKUP GUIDE\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write("=============================\n")
        for ticker, status, age in needed_lookups:
            # Determine if stock or fund
            url_path = "stocks/xnys" if _is_stock(ticker) else "funds/xnas"
            # Resolve Morningstar ticker from local code
            ms_ticker = _resolve_morningstar_ticker(ticker)
            f.write(f"{ticker:15} [{status}] → https://www.morningstar.com/{url_path}/{ms_ticker}/risk\n")

def _is_stock(ticker):
    """Heuristic: ticker looks like NYSE stock vs. mutual fund."""
    # Real implementation checks against a known list or queries Finviz
    ...

def _resolve_morningstar_ticker(local_ticker):
    """Map local portfolio ticker (FID-CONTRA-F) to Morningstar ticker (FCNKX)."""
    # Lookup table in config or inferred
    ...
```

**Acceptance for Sub-phase 0.8:**
- After any portfolio change (CSV import, rebalance), run `./scripts/refresh_portfolio_data.sh`
- The regenerated `/tmp/morningstar_beta_lookup.txt` shows only tickers currently held AND needing lookup
- Entries are tagged `[NEW]` (never looked up) or `[STALE]` (>365 days old)
- Tickers no longer in portfolio are absent from the list
- URLs point to `.../risk` not `.../portfolio` (today's bug)

**Also addresses known bug from April 17 list:**
- LHX and RTX were mislabeled as funds. The regeneration logic infers correctly from a ticker class lookup instead of blanket-defaulting to `/funds/xnas/`.
- SRNE being delisted is handled because it wouldn't show in current holdings.

---

## Phase 1: Remove hardcoded numbers from prompts

**Effort:** 2-3 hours  
**Risk:** Low (no logic change, just swap literals for dict references)  
**Acceptance:** Grep the rewritten file for literal dollar amounts and percentages — should return near zero (only constants like SSDI rates that are real-world fixed numbers).

### Substeps

**1.1 Build comprehensive portfolio context from dict only.** Replace every hardcoded literal in `_portfolio_context()` with a pull from the portfolio dict, analysis dict, or rebalancing dict passed in.

**1.2 Extract personal/tax constants to a separate config file.** Things that are genuinely constant (John's age, filing status, mortgage rate, SSDI amount) should live in `config/personal_situation.yaml` and be loaded once. Everything else (tax math, income totals) should be computed from those constants plus the current year.

Proposed structure for `config/personal_situation.yaml`:
```yaml
owner:
  name: "John W. Whiting"
  dob: "1967-08-21"
  filing_status: "MFS"  # Married Filing Separately

income:
  ssdi_annual: 45600
  schedule_c_gross_estimate: 20000
  se_tax_deduction_estimate: 1413
  private_disability_active_until_age: 68.5

housing:
  mortgage_annual_interest: 16011
  property_tax: 7670
  mortgage_balance: 408347
  mortgage_rate: 0.04
  mortgage_matures: "2042-09"
  location: "Bronxwood, NYC"

tax:
  federal_itemized_2026: 21011
  ny_itemized_2026: 23681
  mfs_22_bracket_ceiling_2026: 94300
  already_converted_2026: 35000
  golden_window_open: "2036-02-19"
  golden_window_close: "2040-08-20"
  rmd_age: 73
```

**1.3 Rewrite each section function to pull numbers dynamically.** For each `_section_function()`, audit the prompt string and replace every `$...` or `X%` with an f-string interpolation from the portfolio/analysis/config dicts.

**1.4 Acceptance test.** Create a fake portfolio dict with different numbers from today (e.g., total = $1,400,000, V pct = 10%). Run each section. Output should cite $1,400,000 and 10% — not $1,206,069 and 15.9%.

### Files modified
- `scripts/portfolio_ai_analyst.py` — replace hardcoded literals with dict references
- `config/personal_situation.yaml` — new file, holds real constants
- Add helper function `_load_personal_situation()` near `_load_fidelity_constraint()`

### Deploy gate
Run `python3 scripts/portfolio_ai_analyst.py --project-root . --run-type weekly` with today's portfolio. Diff output against today's CC AI tab. Numbers should match, not be off by hardcoded-staleness amounts.

---

## Phase 2: Three-tier model routing

**Effort:** 1 hour  
**Risk:** Low  
**Acceptance:** Weekly uses Ollama, monthly sections use Sonnet, monthly flagship uses Opus, all verified in logs.

### Substeps

**2.1 Add Opus model constant at top of file:**
```python
OPUS = os.getenv("CLAUDE_FLAGSHIP_MODEL", "claude-opus-4-7")
```

**2.2 Extend `_ai()` to accept a tier parameter:**
```python
def _ai(prompt: str, model: str = None, max_tokens: int = 1500, tier: str = "standard") -> str:
    """Route based on run type and tier.
    Tiers: 'flagship' = Opus, 'standard' = Sonnet, 'cheap' = Haiku, 'local' = Ollama
    """
    if _USE_OLLAMA and tier != "flagship":
        # Weekly runs use Ollama even for standard tier; flagship always uses Opus
        return _ollama(prompt, max_tokens=min(max_tokens, 600))
    if tier == "flagship":
        return _claude(prompt, model=OPUS, max_tokens=max_tokens)
    if tier == "cheap":
        return _claude(prompt, model=HAIKU, max_tokens=max_tokens)
    return _claude(prompt, model=model or SONNET, max_tokens=max_tokens)
```

**2.3 Mark each section with appropriate tier:**
- `_exec_summary` → `tier="cheap"` (Haiku — quick daily)
- `_deep_holdings_analysis` → `tier="flagship"` monthly, `tier="local"` weekly
- `_dividend_strategy` → `tier="standard"` monthly, `tier="local"` weekly
- `_bond_strategy` → `tier="standard"` monthly, `tier="local"` weekly
- `_ira_opportunities` → `tier="standard"`
- `_v_strategy` → `tier="flagship"` (important, single-position decision)
- `_defense_analysis` → `tier="flagship"` (thesis-critical)
- `_roth_conversion_analysis` → `tier="flagship"` (tax/timing decisions — Opus)

**2.4 Add monthly synthesis section (NEW):** A top-level "Monthly Executive Brief" that runs ONLY in monthly mode, uses Opus, and synthesizes findings across all other sections. This goes in Commander's Summary slot on the monthly report.

### Files modified
- `scripts/portfolio_ai_analyst.py`
- Verify model names against https://docs.claude.com (model strings change)

### Deploy gate
Run monthly in dry-run. Log lines should show: Haiku for exec summary, Sonnet for standard sections, Opus for flagship sections. Screenshot the log output.

---

## Phase 3: Weekly-to-monthly aggregation

**Effort:** 2-3 hours  
**Risk:** Medium (new data flow)  
**Acceptance:** Monthly run reads last 4 weekly reports, cites what changed week-over-week.

### Substeps

**3.1 Store weekly reports with predictable path.** Check whether weekly reports already save to `data/portfolios/reports/weekly/weekly_YYYY-MM-DD.html`. If yes, good. If not, add that. Also save a `data/portfolios/state/weekly_summary_YYYY-MM-DD.json` with key metrics — so monthly doesn't need to parse HTML.

Structure of weekly_summary JSON:
```json
{
  "week_ending": "2026-04-17",
  "portfolio_value": 1206069,
  "week_over_week_change_pct": 2.34,
  "week_over_week_change_dollar": 27558,
  "ytd_return_pct": -13.03,
  "top_movers_positive": [...],
  "top_movers_negative": [...],
  "signals_generated": {"TRIM": 2, "WATCH": 4, "ADD": 4, "MONITOR": 1, "HOLD": 30},
  "notable_events": ["IRDM earnings in 5d", "V thesis-downgraded TRIM"],
  "ai_executive_summary": "...short summary from weekly..."
}
```

**3.2 Create `_load_recent_weekly_summaries(n=4)` helper.** Loads last n weekly summaries sorted by date. Returns list of dicts.

**3.3 Add `_monthly_executive_brief()` section for monthly runs only.** This function:
- Loads last 4 weekly summaries
- Computes MTD trajectory from the 4 weeks
- Identifies what changed vs. what stayed flat
- Calls Opus with a prompt containing: (1) current portfolio state, (2) 4-week history, (3) signals generated during the month, (4) any notable events

Prompt skeleton for monthly brief:
```
You are writing the monthly executive brief for John W. Whiting's portfolio.

CURRENT STATE (end of month):
{current portfolio context}

PAST FOUR WEEKS (oldest to newest):
Week 1 ({date}): {portfolio_value}, {wow_change}, notable: {events}
Week 2 ({date}): {...}
Week 3 ({date}): {...}
Week 4 ({date}): {...}

SIGNALS GENERATED THIS MONTH:
{list of signals with dates}

TASK: Write a 4-paragraph monthly brief covering:
1. What the portfolio did this month (direction, magnitude, drivers)
2. What changed in thesis or positioning (entries, exits, rebalances)  
3. What to watch going into next month (upcoming earnings, deadlines, action items)
4. One strategic decision to make this month (with specific dollar amount and rationale)

Be specific. Cite real numbers. Acknowledge uncertainty where it exists.
```

**3.4 Insert monthly brief at top of monthly HTML.** Right below Commander's Summary. Short section. 4 paragraphs.

### Files modified
- `scripts/portfolio_ai_analyst.py` — add `_load_recent_weekly_summaries`, `_monthly_executive_brief`
- `scripts/portfolio_weekly_report.py` — add weekly_summary JSON output if not already there
- `scripts/portfolio_monthly_report.py` — call new monthly brief, place in HTML

### Deploy gate
Manually create 4 fake weekly_summary JSONs dated 3, 10, 17, 24 days ago. Run monthly in dry-run. Check that the output cites week-over-week progression and makes sense against the fabricated history.

---

## Phase 4: Smart cache invalidation

**Effort:** 1-2 hours  
**Risk:** Low  
**Acceptance:** Cache regenerates when portfolio composition changes significantly, not just when 30 days have passed.

### Substeps

**4.1 Compute portfolio signature.** Add helper:
```python
def _portfolio_signature(portfolio: Dict) -> str:
    """Hash of portfolio composition. Changes when anything material changes."""
    import hashlib
    totals = portfolio.get("portfolio_totals", {})
    holdings = [(h.get("symbol"), round(h.get("market_value", 0) / 100) * 100) 
                for h in portfolio.get("holdings", [])]
    holdings.sort()
    sig_str = f"{round(totals.get('total_value', 0) / 1000) * 1000}|{holdings}"
    return hashlib.md5(sig_str.encode()).hexdigest()[:16]
```

This rounds to nearest $100 per position and nearest $1,000 total — so daily noise doesn't force regeneration, but real changes do.

**4.2 Store signature in cache metadata:**
```python
def _save_cache(state_dir, key, text, portfolio_sig=""):
    (Path(state_dir) / f"ai_{key}.json").write_text(
        json.dumps({
            "key": key, 
            "text": text, 
            "ts": datetime.now().isoformat(),
            "portfolio_sig": portfolio_sig
        }, indent=2))
```

**4.3 Check signature in `_should_refresh`:**
```python
def _should_refresh(state_dir, key, max_days=30, current_sig=""):
    f = Path(state_dir) / f"ai_{key}.json"
    if not f.exists(): return True
    try:
        d = json.loads(f.read_text())
        age = (datetime.now() - datetime.fromisoformat(d.get("ts", "2000-01-01"))).days
        if age >= max_days: return True
        cached_sig = d.get("portfolio_sig", "")
        if current_sig and cached_sig and cached_sig != current_sig:
            return True  # Portfolio changed materially
        return False
    except: return True
```

**4.4 Pass signature through `run_ai_analysis`:**
```python
current_sig = _portfolio_signature(portfolio)
# then in the loop:
if force_refresh or _should_refresh(state_dir, key, 30, current_sig):
    ...
    _save_cache(state_dir, key, text, portfolio_sig=current_sig)
```

### Files modified
- `scripts/portfolio_ai_analyst.py` only

### Deploy gate
Run twice with same portfolio → second run uses cache. Modify a position significantly in the portfolio JSON, run again → cache invalidates, fresh generation. Log should show "cached" vs. "refreshing" appropriately.

---

## Phase 5: Intel Arc Pro B50 local LLM integration

**Effort:** 2-4 hours (plus hardware install time)  
**Risk:** Medium (Intel GPU LLM stack is less mature than NVIDIA CUDA)  
**Acceptance:** Ollama runs qwen3:14b on the Arc Pro B50, AI Deep Analysis quality visibly improves vs. qwen3:1.7b on CPU.

### Substeps

See separate document: `intel_arc_llm_setup.md`

At a high level: install Intel drivers, install IPEX-LLM (Intel Extension for PyTorch for LLM), configure Ollama to use Intel backend, pull qwen3:14b, swap model name in portfolio_ai_analyst.py line 25 and 47.

### Critical dependency

Phase 5 depends on Phase 1 (hardcoded numbers removal). If Phase 1 isn't done, a bigger model will just hallucinate more convincingly against stale context. Phase 1 MUST land first.

---

## Phase 6: Portfolio theory — MPT, Black-Litterman, Monte Carlo

**Effort:** 15-20 hours, phased sub-releases  
**Risk:** Medium-high (new math, new dependencies, requires validation against known benchmarks)  
**Acceptance:** Monthly report shows Efficient Frontier position, Monte Carlo success rate for Roth/retirement plan, and Black-Litterman-blended allocation recommendations.

### Why this is worth doing

The current `portfolio_ai_analyst.py` tells you **what your portfolio looks like.** Phase 6 makes it tell you **what your portfolio SHOULD look like** based on actual portfolio theory used by Betterment, Wealthfront, and Vanguard Digital Advisor. This is the jump from reporting to advisory.

Specifically, it answers questions the current system can't:
- "What's the probability my Golden Window Roth conversion plan succeeds?"
- "Given my AI WWIII defense thesis, what's the optimal allocation that respects my bearish market view?"
- "Am I taking too much risk for my expected return, or not enough?"
- "Which accounts should hold which asset types for maximum after-tax wealth?"

### Why it's a big deal architecturally

This is **not a prompt change** — it's new quantitative infrastructure. Requires:
- Historical price data for covariance matrix (you may or may not have this yet)
- Numerical optimization libraries (numpy, scipy, cvxpy)
- Simulation engine (numpy broadcasting for speed)
- Validation against known benchmarks (your results should match Vanguard's published allocations for similar risk profile)

Do this AFTER Phases 1-5 land. Phase 1 gives you clean data inputs. Phase 2 gives you Opus for synthesizing complex output. Phase 3 gives you cross-time context. This phase adds the math layer on top.

---

### Phase 6A: Monte Carlo for retirement/Roth conversion

**Effort:** 4-5 hours  
**First to ship because:** Lowest risk, highest user value (answers "will my Golden Window plan work?")

**What it does:**
Simulates 10,000+ market paths from today through age 73 (RMD age). Each path uses bootstrapped historical returns from your actual holdings' composition. Reports:
- Probability of Roth being at target balance by Golden Window close (2040-08-20)
- 5th/50th/95th percentile outcomes
- Probability of running out of money in retirement
- Sensitivity to conversion amount ($25K vs $35K vs $50K/yr)

**Implementation approach:**
```python
# New file: scripts/portfolio_monte_carlo.py

def run_monte_carlo_retirement(portfolio, personal_config, n_paths=10000):
    """Run 10,000 path simulation from today to RMD age.
    Returns success probability and percentile outcomes."""
    
    # Inputs from portfolio
    starting_value = portfolio["portfolio_totals"]["total_value"]
    asset_mix = _compute_asset_class_weights(portfolio)
    
    # Historical return distributions per asset class
    # (from Fama-French data or similar, bootstrapped)
    returns_data = _load_historical_returns()
    
    # Simulate
    paths = np.zeros((n_paths, years_to_rmd))
    for path_i in range(n_paths):
        # Bootstrap sample returns, apply to portfolio year by year
        # Account for conversions, contributions, withdrawals per plan
        ...
    
    return {
        "success_probability": (paths[:, -1] > target).mean(),
        "percentile_5": np.percentile(paths[:, -1], 5),
        "percentile_50": np.percentile(paths[:, -1], 50),
        "percentile_95": np.percentile(paths[:, -1], 95),
        "conversion_sensitivity": _run_sensitivity_analysis(...)
    }
```

**Where output lands:**
- Monthly report: new "Retirement Roadmap Monte Carlo" section below Golden Window
- CC AI tab: new "Probability Analysis" card showing success rate
- Weekly report: unchanged (MC doesn't need to run every week)

**Dependencies:**
- `numpy` (probably already installed)
- Historical return data — simplest: use 30-year annual returns from S&P 500, bonds, international. Better: use each asset class (large cap, small cap, intl, bonds) from Fama-French factor library.

**Validation:**
Run MC on a 60/40 static portfolio starting at $1M, 30-year horizon. Compare to published academic results and/or Vanguard's Monte Carlo. Your success probability should be within ±2% of theirs for the same inputs.

---

### Phase 6B: Black-Litterman optimization

**Effort:** 5-7 hours  
**Why second:** Needs 6A's return estimates, benefits from Opus synthesis for user-view interpretation

**What it does:**
Blends market equilibrium (what the market implies returns should be) with your "views" (e.g., "AI WWIII defense tilt," "bearish on tech concentration") to produce optimal weights. Unlike naive MPT which produces unstable corner solutions (100% in one stock), Black-Litterman produces intuitive, stable portfolios.

**Your views — make these config-driven:**
```yaml
# config/portfolio_views.yaml
views:
  - name: "AI WWIII defense thesis"
    type: "absolute"
    assets: ["LMT", "RTX", "NOC", "KTOS", "AVAV"]
    expected_return: 0.12  # 12% annual expected
    confidence: 0.7        # 0-1, how confident you are
    
  - name: "V concentration unwind"
    type: "relative"
    long: ["SCHD"]
    short: ["V"]
    expected_spread: 0.02  # SCHD outperforms V by 2%
    confidence: 0.5
    
  - name: "Bearish US equities"
    type: "absolute"
    assets: ["VTI", "SPY", "VOO"]
    expected_return: 0.05  # reduced from long-term 8-10%
    confidence: 0.6
```

**Implementation approach:**
```python
# New file: scripts/portfolio_optimizer.py

def black_litterman_optimize(portfolio, views, risk_aversion=2.5):
    """Produce optimal weights blending market equilibrium with user views."""
    # Market cap weights → implied equilibrium returns (reverse MPT)
    equilibrium_returns = _reverse_optimize(market_weights, cov_matrix, risk_aversion)
    
    # Apply views via BL formula
    blended_returns = _blend_views_with_equilibrium(equilibrium_returns, views, cov_matrix)
    
    # Solve for optimal weights
    optimal_weights = _mean_variance_optimize(blended_returns, cov_matrix, risk_aversion)
    
    return {
        "current_weights": _current_weights(portfolio),
        "optimal_weights": optimal_weights,
        "drift": _compute_drift(current, optimal),
        "expected_return_change": ...,
        "expected_risk_change": ...
    }
```

**Where output lands:**
- Monthly report: new "Optimal Allocation Analysis" section
- CC Rebalance tab: enhanced with BL-recommended weights alongside current weights
- Opus is prompted with the math output to write plain-English explanation of what to trade and why

**Dependencies:**
- `numpy`, `scipy` (optimization)
- `cvxpy` (constrained optimization, e.g., no-shorting, max position %)
- Covariance matrix of your holdings' returns (60-90 days of daily price data minimum)

**Validation:**
Feed BL a 100% equity starting allocation with "bullish on bonds" view at medium confidence. Output should shift 10-30% to bonds. Reverse the view → output shifts back.

---

### Phase 6C: Asset location optimization

**Effort:** 3-4 hours  
**Why third:** Simpler math than BL, but needs Phase 1's account-level data fully cleaned

**What it does:**
Given your 4 account types (401k, Rollover IRA, Roth IRA, Taxable), figures out which assets should live in which account for maximum after-tax wealth. Rule of thumb:
- **Roth:** Highest-growth assets (growth stocks, small caps) — tax-free forever
- **Tax-deferred IRA:** Highest-dividend/interest assets (BDCs, bonds, REITs) — ordinary income anyway
- **Taxable:** Tax-efficient equities (broad index ETFs, qualified dividend payers) — benefits from long-term cap gains rates
- **401k:** Whatever the plan allows (constrained)

**Implementation:**
```python
def optimize_asset_location(portfolio, config):
    """Recommend which holdings to move between accounts (in-kind transfers or sell-buy)."""
    # Score each holding on "tax inefficiency"
    # High yield + ordinary income = belongs in IRA
    # Low yield + growth = belongs in Roth
    # Index ETF low turnover = fine in taxable
    ...
    return {
        "recommendations": [
            {"ticker": "CSWC", "from": "taxable", "to": "rollover_ira", 
             "rationale": "10.5% ordinary-income yield is tax-inefficient in taxable",
             "estimated_annual_tax_savings": 234},
            ...
        ]
    }
```

**Where output lands:**
- Monthly report: new "Asset Location Review" section (or integrate into Tax Optimization section)
- Opus synthesizes specific recommended moves with step-by-step instructions

**Dependencies:**
None beyond Phases 1-2.

---

### Phase 6D: Efficient Frontier visualization (optional polish)

**Effort:** 2-3 hours  
**Why last and optional:** Nice-to-have visual. Value over 6A/6B is marginal.

Render a chart showing:
- Your current portfolio position (risk, return)
- The efficient frontier curve
- Optimal portfolios for different risk levels
- BL-recommended portfolio position

Goes on the CC Rebalance tab or a new "Portfolio Theory" tab. Matplotlib → PNG → embed in HTML.

---

### Critical caveats for Phase 6

**1. Historical returns do NOT predict future returns.** Every MC simulation you run carries this limitation. Output should always include a "Past performance does not guarantee future results" disclosure. This is SEC-mandated language and also just true.

**2. Black-Litterman is sensitive to confidence parameters.** Setting confidence too high on your views produces the same corner solutions MPT has. Setting too low makes your views invisible. Starting point: use confidence=0.5 for most views, raise only for things you have strong conviction on.

**3. Your portfolio is too concentrated for clean theory.** MPT assumes you can rebalance freely. You have tax lockups (V +702% in taxable, can't sell without cap gains) and account constraints (Fidelity 401k limited to plan funds). The math must respect these constraints — use cvxpy constraints not pure unconstrained optimization.

**4. Covariance matrix is noisy.** With ~30 holdings and only 90 days of data, the covariance matrix is unstable. Use shrinkage estimators (Ledoit-Wolf) to stabilize.

**5. Validation matters more than in other phases.** MC and BL can produce plausible-looking output that's mathematically wrong. Validate every output against a benchmark (published academic results, Vanguard's advisor output for similar profile) before trusting it for decisions.

### Sub-phase sequencing for Phase 6

Recommended order:
1. **6A (Monte Carlo)** — 4-5 hours, ship first, validate against Vanguard MC
2. **6C (Asset Location)** — 3-4 hours, ship second, quick win
3. **6B (Black-Litterman)** — 5-7 hours, ship third, needs most validation
4. **6D (Efficient Frontier viz)** — 2-3 hours, optional, ship if time/interest

**Total Phase 6:** 15-20 hours across 4 sub-phases. Do over multiple weekends.

---

## Phase 7: ETF Intelligence Enrichment + AI Integration

**Effort:** 10-14 hours across sub-phases  
**Risk:** Medium (new data pipeline + AI prompt restructuring)  
**Acceptance:** ETF-specific data (expense ratio, tracking difference, distribution consistency, holdings overlap, NAV premium/discount, liquidity, factor exposure, concentration) is collected per ETF, stored in state, and fed into BOTH Ollama (weekly) and Sonnet/Opus (monthly) AI pipelines for analysis and recommendations.

### Why this matters

Today your signals engine treats ETFs like any other ticker — just a position with a beta and market value. But ETFs have dynamics stocks don't: they can drift from their index, their expense ratios compound into real drag, and their distribution sustainability matters for income-focused holdings. Your portfolio has multiple ETFs where this matters:

- **Income ETFs:** SCHD, DIV, JEPI/JEPQ if added — distribution stability is critical
- **Sector ETFs:** XLI, XLB, XLF — low priority metrics but useful for rebalancing
- **Thematic/active ETFs:** ARKQ, ARKG — high expense ratio, active management, tracking difference doesn't apply the same way
- **Broad-market ETFs:** SCHG, SP500-D (via FXAIX fund equivalent) — should be cheap and tight
- **Fixed income ETFs:** BND, VCIT, SGOV if added — duration, credit quality matter

Without ETF-specific intelligence, your AI analyst can't tell you things like:
- "SCHD's expense ratio at 0.06% is excellent; no action needed"
- "ARKG's tracking error to its own stated strategy is 12% annualized; reconsider thesis"
- "JEPQ distribution coverage ratio is 0.89x — sustainability at risk"
- "Your SCHD and FID-CONTRA-F have 23% holdings overlap — you're doubling up on Microsoft/Apple without realizing it"

Phase 7 makes these analyses possible.

### Sub-phase 7A: ETF data collection pipeline (3-4 hours)

**Goal:** Build `scripts/etf_enrichment.py` that collects all 8 ETF metrics weekly.

**Data sources (free tier):**
- **ETF.com** — expense ratio, tracking difference, premium/discount, liquidity metrics
- **Yahoo Finance API (via yfinance)** — holdings, distributions, NAV
- **Issuer websites (scraping)** — most recent distribution, factor exposure where published
- **Finnhub API** — already in .venv, has some ETF data
- **SEC EDGAR N-PORT filings** — authoritative holdings (monthly lag)

**Storage:** `data/portfolios/state/etf_metrics.json`

```json
{
  "generated_at": "2026-04-18T10:00:00",
  "etfs": {
    "SCHD": {
      "expense_ratio": 0.0006,
      "tracking_difference_1y": -0.02,
      "distribution_consistency": {
        "last_4_quarters_ttm": [0.71, 0.72, 0.73, 0.71],
        "yoy_growth": 0.028,
        "coverage_ratio": 1.12,
        "status": "stable"
      },
      "premium_discount_nav": 0.0001,
      "top_10_weight_pct": 41.2,
      "holdings_top_10": ["HD", "VZ", "CVX", "KO", ...],
      "liquidity": {
        "avg_daily_volume": 15400000,
        "bid_ask_spread_bps": 1.2
      },
      "factor_exposure": {
        "value": 0.42,
        "quality": 0.38,
        "size": 0.11,
        "momentum": -0.02
      },
      "concentration_risk": "low"
    },
    "JEPQ": { ... },
    "ARKG": { ... }
  }
}
```

**Build approach:**
1. Start with 5 priority ETFs (SCHD, DIV, CSWC, PFLT, ARKQ — your income + speculative holdings)
2. Wire each data source one at a time, validate each against manual check
3. Add remaining ETFs to the collection loop
4. Add systemd weekly timer (Sunday 5 AM, before Monday refresh) to keep data fresh

**Critical design decisions:**

*Distribution coverage ratio* — the most valuable metric for your income ETFs. Calculate as: `TTM Net Investment Income / TTM Distributions Paid`. If < 1.0, the ETF is paying from principal (unsustainable). Requires scraping fund financials quarterly.

*Holdings overlap* — compute against your other holdings, not just internal. Requires your holdings dict as input. Output "overlap %" per pair.

*Factor exposure* — hardest to compute without paid data. Start with Morningstar's published style box as a proxy. Real factor regression is Phase 6B territory (Black-Litterman).

### Sub-phase 7B: Feed ETF data to Ollama (weekly) AI (2-3 hours)

**Goal:** When `_USE_OLLAMA=True`, include relevant ETF metrics in the prompt context for sections that analyze ETF positions (especially dividend_strategy, bond_strategy, deep_holdings).

**Implementation — extend `_mini_context()` function:**

```python
def _mini_context(portfolio: Dict, analysis: Dict = None, rebalancing: Dict = None, 
                   etf_metrics: Dict = None) -> str:
    # ... existing context building ...
    
    # Add ETF-specific context for ETF holdings
    etf_holdings = [h for h in holdings if _is_etf(h['symbol'])]
    etf_lines = []
    for h in etf_holdings[:8]:  # Top 8 by MV
        etf = etf_metrics.get(h['symbol'], {})
        if not etf:
            continue
        etf_lines.append(
            f"  {h['symbol']:6} ER={etf.get('expense_ratio', 0)*100:.2f}%  "
            f"TrackDiff={etf.get('tracking_difference_1y', 0)*100:+.2f}%  "
            f"DistCov={etf.get('distribution_consistency', {}).get('coverage_ratio', 0):.2f}x  "
            f"Top10={etf.get('top_10_weight_pct', 0):.0f}%"
        )
    
    etf_block = "\n".join(etf_lines) if etf_lines else "  (no ETF metrics available)"
    
    return existing_context + f"\n\nETF METRICS (for owned ETFs):\n{etf_block}\n"
```

**Budget:** Keep ETF context compact for Ollama — ~8 lines max for weekly. Full context goes to Sonnet.

**Updated prompts for weekly sections:**

For `_dividend_strategy` weekly (Ollama):
```
Analyze dividend portfolio. Note ETF-specific risks:
- Any distribution coverage <1.0 is red flag (unsustainable payout)
- Expense ratio >0.5% on income ETFs is drag
- Tracking difference >2% suggests poor execution

Given the ETF metrics in context above, identify which income position has the weakest distribution sustainability and recommend action.
```

### Sub-phase 7C: Feed ETF data to Sonnet/Opus (monthly) AI (2-3 hours)

**Goal:** Full ETF context for monthly deep analysis. Sonnet can handle all 8 metrics per ETF.

**Implementation — extend `_portfolio_context()` function:**

Add a full ETF intelligence section to the context dict, not just summary metrics. For Sonnet, include:
- All 8 metrics with historical trends where available
- Cross-position holdings overlap matrix (e.g., "SCHD + FID-CONTRA-F overlap 23% on MSFT/AAPL/GOOGL")
- Distribution history quarterly (4-8 quarters)
- Factor exposure breakdown

**Updated prompts for monthly sections:**

For `_dividend_strategy` monthly (Sonnet):
- Existing prompt + "Review ETF-specific metrics above. For any income ETF with coverage ratio <1.05, flag with specific recommendation (reduce, watch, exit). Cross-reference holdings overlap to identify inadvertent concentration."

For `_deep_holdings_analysis` monthly (Sonnet):
- Add: "For each ETF in top 8 holdings, evaluate: (1) is expense ratio competitive vs. alternatives, (2) is tracking difference acceptable, (3) if thematic, is strategy still working? Recommend keep/switch/exit per ETF with specific alternative tickers."

**New section for monthly flagship (Opus):** "ETF Quality Review"
- Once per month, deep dive on all ETF holdings
- Flag any ETF where switching to a cheaper/better alternative would improve returns by >10 bps/year after tax
- Specific switch recommendations with trade mechanics

### Sub-phase 7D: CC dashboard integration (2-3 hours)

**Goal:** Surface ETF intelligence on Command Center. New "ETF Quality" tab or integration into existing Holdings tab.

**Options:**
1. **New tab:** "ETF Intelligence" — dedicated view with all metrics per ETF, color-coded quality scores
2. **Integration:** Add ETF-specific columns to Holdings table when filtering to ETFs only
3. **Minimal:** Add ETF metrics to Holdings drawer (clicking an ETF row shows metrics alongside position details)

Recommend Option 3 for minimal disruption, Option 1 if you want a real ETF review workflow.

### Sub-phase 7E: Weekly/monthly alerts for ETF issues (1-2 hours)

**Goal:** Proactive alerts when ETF metrics deteriorate.

Rules to add:
- Distribution coverage ratio drops below 1.0 → Telegram alert
- Tracking difference exceeds 2% annualized → flag in weekly report
- Expense ratio changes (rare but happens) → flag in monthly
- Top 10 holdings change materially → flag in monthly (strategy drift indicator)

### Sub-phase sequencing for Phase 7

Recommended order:
1. **7A (data collection)** — 3-4 hours, must ship first, validates the data sources work
2. **7B (Ollama weekly)** — 2-3 hours, smaller context so easier to test
3. **7C (Sonnet/Opus monthly)** — 2-3 hours, biggest prompt changes
4. **7D (CC integration)** — 2-3 hours, optional visual polish
5. **7E (alerts)** — 1-2 hours, polish after data is flowing

**Total Phase 7:** 10-14 hours across 5 sub-phases.

### Critical dependency

Phase 7 depends on Phases 0-1 (fresh data, no hardcoded numbers). Don't try to feed new ETF data to an AI that's still dumping biographical preamble and citing $1,201,407 instead of live values.

Phase 7 also benefits from Phase 5 (GPU) because the larger Ollama prompts with ETF metrics will run faster on qwen3:14b on B50 than on qwen3:1.7b on CPU.

### Validation approach

For each ETF metric collected, spot-check 3 ETFs manually against the source website. Tracking difference is the trickiest — make sure the calculation uses NAV-adjusted returns vs. index, not just price.

### Cost notes

- ETF.com scraping is free but may need rate-limiting (2-second delay between requests)
- yfinance is free, no key needed
- Finnhub: you already have a key
- SEC EDGAR: free, public
- **No new paid subscriptions needed** for basic implementation

### Critical prerequisite: Ticker mapping audit (discovered 2026-04-18)

**Before Phase 7A can work reliably, the ticker mapping table in `config/manual_beta_overrides.json` must be audited against authoritative source (Fidelity NetBenefits).**

**Bugs discovered during April 18 beta computation session:**

Yesterday's Claude Code built `manual_beta_overrides.json` by guessing ticker mappings from partial information. Cross-referencing against actual Fidelity NetBenefits holdings (with CUSIPs) revealed:

| Local code | Wrong mapping | Correct ticker | Issue |
|---|---|---|---|
| TRP-LVAL | TRLVX (SEI Core Fixed Income bond fund) | TILCX (T. Rowe Price Large-Cap Value I) | Totally unrelated fund |
| AB-DISC-Z | VOE (Vanguard Mid-Cap Value ETF) | ABSZX (AB Discovery Value Z) | Different issuer entirely |
| SS-SMMD | SVSPX (State Street S&P 500) | Russell Small/Mid Cap fund (ticker TBD) | Wrong size/style |
| VANG-FTSE-SOC | VFTSX (Investor share class) | VFTNX (Institutional share class) | Different share class, different expense ratio |

**How to audit:** Pull your NetBenefits holdings screen with CUSIPs and tickers. Build a canonical mapping file at `config/fidelity_plan_mapping.yaml`:

```yaml
# Single source of truth for Fidelity 401k plan fund mappings
# Generated from NetBenefits holdings screen on YYYY-MM-DD
# CUSIP is authoritative; local_code is how our code refers to it

funds:
  - local_code: TRP-LVAL
    cusip: TILCX  # Assuming TILCX, verify from statement
    plan_name: "TRP LARGE-CAP VAL I"
    ticker: TILCX
    asset_class: us_large_value
  - local_code: SP500-D
    cusip: 84679P405
    plan_name: "SP 500 INDEX PL CL D"
    ticker: FXAIX  # Verify this is the underlying, not a plan wrapper
    asset_class: us_large_blend
  # ... one entry per plan fund
```

**This file becomes the input to `manual_beta_overrides.json`, not the reverse.** The workflow:
1. NetBenefits is source of truth (export quarterly or screenshot)
2. `fidelity_plan_mapping.yaml` is the human-verified mapping
3. `manual_beta_overrides.json` is generated from mapping + computed betas
4. `scripts/fetch_betas_yfinance.py` runs against correct tickers

**Plan-specific share classes:** Some 401k plans use institutional or plan-custom share classes of underlying funds. These may not exist on Yahoo Finance. When yfinance returns no beta for a plan-specific share class, fall back to the parent fund ticker (with documented divergence).

### Known issue: S&P 500 is wrong benchmark for non-large-blend funds (2026-04-18)

During beta computation testing, several funds with plausibly-correct computed betas failed the R²>=0.30 confidence threshold:

- **AB Discovery Value (ABSZX)**: beta=0.909, R²=0.23 — predicted range was 0.90-1.10
- **T. Rowe Price Large-Cap Value (TILCX)**: beta=0.775, R²=0.19 — predicted range was 0.85-0.95
- **Defense stocks (LMT, NOC, RTX, LHX, LDOS, BAH, KTOS, AVAV, KBR, CACI, DRS)**: low R² across the board

The computed betas are reasonable numbers. The low R² reflects that **S&P 500 is not the right benchmark** for value funds, small/mid-cap funds, or sector-specific equities. They have factor exposures (value premium, size factor, sector dynamics) that don't move with a cap-weighted large-blend index.

**Future fix:** Multi-benchmark regression in Phase 7B:

```python
BENCHMARK_BY_CATEGORY = {
    'us_large_blend': '^GSPC',      # S&P 500
    'us_large_value': 'IWD',        # Russell 1000 Value
    'us_large_growth': 'IWF',       # Russell 1000 Growth
    'us_mid_value': 'IWS',          # Russell Mid-Cap Value
    'us_small_value': 'IWN',        # Russell 2000 Value
    'us_smmid_blend': 'SMMD',       # Russell 2500
    'international': 'ACWX',        # MSCI ACWI ex-US
    'defense_sector': 'ITA',        # iShares Aerospace & Defense
    'utilities': 'XLU',             # Utilities Sector SPDR
    # ... etc
}

def compute_beta_regression(ticker, category, years=3, freq='weekly'):
    benchmark = BENCHMARK_BY_CATEGORY.get(category, '^GSPC')
    # regress against category-appropriate benchmark
```

The computed beta becomes more meaningful (higher R² because benchmark matches fund mandate), and the R² threshold becomes genuinely usable as a confidence indicator.

**Alternative: multi-factor regression (more work, more power):**

Build Fama-French 3-factor or 5-factor regression:
- Market excess return (MKT-RF)
- Size (SMB)
- Value (HML)
- (Optional: momentum UMD, quality QMJ)

Each fund gets loadings on each factor, with R² measuring total explanatory power. This is Black-Litterman territory (Phase 6B) but useful even at simpler Phase 7 level.

**Workaround for today:** accept that ~15 of 27 entries can't get computed beta via naive S&P 500 regression. Leave them null until Phase 7B lands. Not ideal but honest.

---

## Phase 8: Personal Situation modal editor

**Effort:** 3-4 hours for 8A-8C (shipped 2026-04-19), +3-4 hours for 8D (future)  
**Risk:** Low (follows existing .env modal pattern in CC)  
**Acceptance:** John can edit personal financial inputs (Roth conversions YTD, 401k contributions, mortgage balance, etc.) via a modal dialog on Command Center. Every edit is timestamped and historically preserved. AI analysis pulls from this source of truth — zero hardcoded personal values in prompts.

**Status:** 8A, 8B, 8C shipped 2026-04-19. 8D (historical query + time-travel UI) scoped for future session.

### Why this matters

Currently, values like "$35K Roth converted YTD" or "$408,347 mortgage balance" live in config/personal_situation.yaml or hardcoded in prompts. They go stale the moment John makes a new contribution or pays down principal. The AI writes confidently-wrong advice because it's reading stale numbers.

Phase 8 makes personal financial data a live, editable, versioned source of truth via a modal dialog on CC (following the same pattern as the existing .env modal).

### Sub-phase 8A: Data model (1 hour)

**New file:** `data/portfolios/state/personal_situation.json`

```json
{
  "generated_at": "2026-04-19T10:00:00",
  "schema_version": "1.0",
  "fields": {
    "roth_conversion_ytd_2026": {
      "current_value": 35000,
      "last_updated": "2026-03-15",
      "history": [
        {"value": 25000, "date": "2026-02-10", "note": "Q1 partial"},
        {"value": 35000, "date": "2026-03-15", "note": "Topped up to stay within 22% bracket"}
      ],
      "data_type": "currency",
      "category": "tax"
    },
    "401k_contribution_ytd_2026": {...},
    "mortgage_balance": {...},
    "filing_status": {
      "current_value": "MFS",
      "data_type": "enum",
      "options": ["single", "MFJ", "MFS", "HOH"],
      "category": "tax"
    },
    "dependents_count": {...},
    "ssdi_monthly": {...},
    "schedule_c_gross_ytd": {...}
  }
}
```

**Save endpoint** in whatever server serves CC:
- `POST /api/personal_situation/update` — body: `{field, new_value, effective_date, note}`, appends to history + updates current_value
- `GET /api/personal_situation` — returns current state for modal to populate

All writes timestamp automatically with server time. History is append-only — old values never overwritten.

### Sub-phase 8B: Modal UI in Command Center (1-2 hours)

Follow the existing `.env modal` pattern (commit `debaf7c` expanded it from 6 to 26 fields). Add a new button to CC header: "Personal Situation" or similar icon.

Modal contents:
- Sections grouped by category (Tax / Retirement / Housing / Income)
- Each field shows: label, current value, last updated date, "edit" button
- Edit expands inline: new value input + date picker (defaults to today) + optional note + save/cancel
- Submit calls POST endpoint
- Small "history" toggle next to each field shows prior values in collapsible list

Staleness indicators:
- Field not updated in >30 days → yellow highlight
- Field not updated in >90 days → red highlight
- Helps John see at a glance what needs refreshing

### Sub-phase 8C: Wire into AI prompts (1 hour)

This is Phase 1 of the original rewrite scope, specifically for personal situation data.

**Changes to `scripts/portfolio_ai_analyst.py`:**

1. Add `_load_personal_situation()` function that loads the JSON
2. Replace every hardcoded personal value in prompts with dynamic pull:
   - Before: `"Already converted $35,000 in 2026"` (hardcoded)
   - After: `f"Already converted ${ps['roth_conversion_ytd_2026']['current_value']:,} in 2026 (as of {ps[...]['last_updated']})"`
3. Include staleness warning in AI prompt if data is >30 days old:
   - `"NOTE: roth_conversion_ytd_2026 was last updated 45 days ago — John may have contributed more since."`
4. AI can recommend updates: `"If you've converted more since March 15, update via Personal Situation modal before relying on this analysis."`

### Sub-phase 8D: Historical query and time-travel UI (3-4 hours)

**Sequencing note:** 8D is logically AFTER Phase P1 (PostgreSQL migration including history tables). Building 8D on JSON arrays works for current small histories but gets slow as history grows and doesn't support the analytical queries 8D-3 (AI context injection) benefits from. Estimated rework to migrate JSON-based 8D to Postgres later: 2-3 hours. Doing P0 → P1 → 8D in order saves that rework. One exception: 8D-2 (simple history endpoint) can be built on JSON anytime — it's just exposing existing data, not querying it analytically.

**Purpose:** Make the append-only history already captured in `personal_situation.json` usable for analysis, audit, and trend visualization. Turn raw history arrays into a queryable time-series.

**Why this is worth doing (eventually):**

Today, history is captured per field but effectively write-only — you can see IT EXISTS (history count on each field) but can't easily:
- Reconstruct "what did I know on April 15 when I made that rebalance decision?"
- See mortgage balance paying down over 2 years in a chart
- Audit when filing status changed and what the tax implications were at each point
- Give AI prompts historical context ("mortgage balance has dropped from $450K to $408K over the past 18 months — consider the trajectory")

**Three deliverables:**

#### 8D-1: Historical reconstruction endpoint (1 hour) — SHIPPED 2026-04-19 (commit 2dbf19a)

New server endpoint: `GET /api/personal/as_of/<YYYY-MM-DD>`

Returns the full personal_situation state as it would have looked on that date, reconstructed from current values + walking history backwards.

**Algorithm:**
```python
def _reconstruct_as_of(data: dict, target_date: str) -> dict:
    """Reconstruct personal_situation state as of target_date.
    
    Walks each field's history backwards: if the current value was set AFTER
    target_date, use the most recent history entry that was set BEFORE or ON
    target_date. If no prior history exists, field didn't exist yet at that time.
    """
    target = date.fromisoformat(target_date)
    result = copy.deepcopy(data)
    
    for field_name, field in result.get("fields", {}).items():
        if not isinstance(field, dict):
            continue
        
        current_date = field.get("last_updated", "")
        if not current_date or current_date <= target_date:
            continue  # Current value is already <= target, no reconstruction needed
        
        # Walk history backwards to find most recent entry <= target
        history = field.get("history", [])
        best_entry = None
        for entry in history:
            entry_date = entry.get("date", "")
            if entry_date and entry_date <= target_date:
                if not best_entry or entry_date > best_entry.get("date", ""):
                    best_entry = entry
        
        if best_entry:
            field["current"] = best_entry["value"]
            field["last_updated"] = best_entry["date"]
            field["_reconstructed"] = True
            field["_reconstructed_from"] = "history"
        else:
            # No entry <= target exists: field didn't have a value at that date
            field["current"] = None
            field["_reconstructed"] = True
            field["_reconstructed_from"] = "not_yet_set"
    
    # Re-run compute_derived_fields on the reconstructed state
    result = _compute_derived_fields(result)
    result["_as_of"] = target_date
    result["_reconstructed_at"] = datetime.now().isoformat()
    return result
```

**Acceptance:** `GET /api/personal/as_of/2026-01-15` returns state as of mid-January. Fields changed since then show their old values. New fields (added after Jan 15) show null.

#### 8D-2: History query endpoint (30 min) — SHIPPED 2026-04-19 (commit 4bcc8bc)

New server endpoint: `GET /api/personal/history/<field_name>`

Returns the complete history array for one field, plus current value, sorted oldest-first for easy charting.

```python
def _handle_personal_history(self, field_name: str):
    """GET /api/personal/history/<field> - return full history for one field."""
    if not PERSONAL_PATH.exists():
        self._json(404, {"ok": False, "error": "personal_situation.json not found"})
        return
    
    data = json.loads(PERSONAL_PATH.read_text())
    field = data.get("fields", {}).get(field_name)
    if not field:
        self._json(404, {"ok": False, "error": f"field '{field_name}' not found"})
        return
    
    history = list(field.get("history", []))
    # Append current as newest entry
    history.append({
        "value": field.get("current"),
        "date": field.get("last_updated"),
        "note": "current",
        "_is_current": True
    })
    history.sort(key=lambda e: e.get("date", ""))
    
    self._json(200, {
        "ok": True,
        "field": field_name,
        "data_type": field.get("data_type"),
        "category": field.get("category"),
        "description": field.get("description"),
        "history": history,
        "change_count": len(field.get("history", [])),
        "first_value_date": history[0].get("date") if history else None,
        "current_value": field.get("current"),
        "current_date": field.get("last_updated")
    })
```

**Acceptance:** `GET /api/personal/history/mortgage_balance` returns array of `{value, date, note}` entries in chronological order, plus metadata.

#### 8D-3: Time-travel UI in modal (2-3 hours) — PARTIAL: 8D-3a shipped 2026-04-19 (commits 8edb246 + polish), 8D-3b and 8D-3c pending

Add a "History" view mode to the Personal Situation modal with three components:

**Component A: Date slider at top of modal**

When the modal opens, show a date slider defaulting to "today" but draggable back to the oldest history date.

- Slider label updates: "Viewing state as of 2026-01-15"
- When slider moves, fetch `/api/personal/as_of/<date>` and repopulate all fields with reconstructed values
- Reconstructed fields get a subtle visual indicator (italic, maybe a small clock icon)
- A "Back to current" button snaps slider to today

**Component B: Field-level history popup**

Clicking the "X prior values" link next to any field (already in Phase 8B) opens a mini-chart or table:

- Table mode: chronological list of {date, value, note} — already displayable as text
- Chart mode: for numeric fields (currency, percentage, integer), render a tiny sparkline using inline SVG showing value over time
- Hover over a chart point shows the exact date/value/note

Example for mortgage_balance:
```
   $450K ─┐
          │  ●
   $430K ─┤    ●
          │       ●
   $410K ─┤          ●──── current: $408,347
          └────────────────
          2024      2025    2026
   
   [3 prior values • span: 18 months • avg change: -$2,350/month]
```

**Component C: AI context injection (historical snapshots)**

When running AI analysis, if `personal_situation.json` has meaningful history (>5 fields with >1 history entry each), include a "HISTORICAL CONTEXT" block in prompts:

```
=== HISTORICAL CONTEXT (last 12 months) ===
Mortgage balance: $450,000 (2024-10) → $408,347 (2026-04) — paying down $2,350/mo
Roth YTD: $18,000 (2026-01) → $35,000 (2026-04) — converted $17K over Q1
Filing status: unchanged (MFS since 2024-01)
```

This helps AI distinguish between "John just started converting" vs "John has consistently maxed his bracket."

### Migration strategy

1. Read current `config/personal_situation.yaml` (if exists)
2. Read hardcoded personal values from `portfolio_ai_analyst.py` prompts
3. Consolidate into initial `personal_situation.json` with `last_updated` = migration date
4. For each hardcoded value removed from prompts, verify AI output unchanged (same number, just sourced differently)
5. Deploy modal UI
6. Delete old YAML + hardcoded values in prompts after 1-2 weeks of verified operation

### Acceptance tests

**For 8A-8C (shipped 2026-04-19):**

1. Click "Personal Situation" button in CC header. Modal opens with all categories visible and current values populated.
2. Click "Edit" on Roth Conversion YTD. Modal shows inline edit form with current value, new value field, date (defaults to today), note field.
3. Enter new amount, submit. Modal closes. Value updates.
4. Verify: personal_situation.json has new history entry with timestamp.
5. Run weekly AI analysis. Verify output cites the NEW value (not the old one).
6. Click "history" toggle on Roth Conversion YTD. See full list of past values with dates.
7. Verify staleness: manually set a field's last_updated to 45 days ago. Field shows yellow highlight in modal.
8. Verify AI prompt includes staleness warning when field is >30 days old.

**For 8D (future):**

9. `GET /api/personal/history/mortgage_balance` returns chronologically sorted history array plus metadata (field type, category, first_value_date, change_count).
10. `GET /api/personal/as_of/2026-01-15` returns personal situation reconstructed as of mid-January. Fields updated after Jan 15 show their older values. Fields added after Jan 15 show null with `_reconstructed_from: "not_yet_set"`.
11. Computed fields in the reconstructed state recompute correctly (age as of that date, Golden Window based on that-date's disability_end_age if changed).
12. Modal time-slider: dragging slider to an older date repopulates all field values with reconstructed values. Reconstructed fields visually distinguished (italic + small clock icon).
13. "Back to current" button snaps slider back to today and reloads live values.
14. Clicking field history opens popup. For currency/percentage/integer fields, popup shows sparkline chart with hover showing exact date/value/note. For enum/boolean fields, popup shows chronological table.
15. AI prompts include HISTORICAL CONTEXT block when personal_situation.json has meaningful history (>5 fields with >1 history entry). Block shows trajectory for key fields like mortgage balance declining over time.

## Phase P: PostgreSQL migration (phased, pragmatic)

**Effort:** 8-12 hours across 5 sub-phases  
**Risk:** Low-to-medium (existing db_adapter.py provides foundation)  
**Acceptance:** Category-1 state migrated to Postgres. Time-series history queryable. JSON preserved as fallback during transition.

### Context

PostgreSQL is already installed and active on MS-01 (since April 13). The repo already contains:
- `scripts/db_adapter.py` — Drop-in storage adapter that auto-detects platform. If Linux + DB creds → PostgreSQL, else → JSON files. Uses `psycopg2`.
- `linux_port_v2/linux/db_setup.sql` — Schema for 5 Category-1 tables: holdings (JSONB, one row per day), price_cache (symbol + date + close_price), portfolio_snapshots (date + total_value + accounts JSONB), trade_ai_state, run_summary.
- `requirements.txt` includes `psycopg2-binary==2.9.10`

The hard architectural work is already done. Phase P is turning on what exists and extending it.

**Key architectural decision already made:** db_adapter distinguishes Category-1 (should migrate, has daily/historical value) from Category-2 (38 state files that are "computed fresh every run and owned by their single module" — stay as JSON). This is the right call. **Do NOT migrate all 43 JSON files.** Migrate the ones with real query value, leave the caches.

### Sub-phase P0: Turn on existing Postgres adapter (1-2 hours)

**Smallest possible Postgres win — mostly already built.**

Steps:
1. Set DB_HOST, DB_NAME, DB_USER, DB_PASSWORD in .env
2. Create the database and user in Postgres: `sudo -u postgres createdb tradeai`
3. Run existing schema: `psql tradeai < linux_port_v2/linux/db_setup.sql`
4. Verify db_adapter.py routes to Postgres for 5 Category-1 tables
5. Test: does daily pipeline work with Postgres as storage backend?
6. Keep JSON writes active as fallback (dual-write mode) for first week

Acceptance: Daily pipeline completes without error. Data lands in Postgres tables. JSON files still updated as backup.

### Sub-phase P1: Add high-value history tables (3-4 hours)

Add tables for time-series data that JSON doesn't handle well:

```sql
CREATE TABLE signal_history (
    id SERIAL PRIMARY KEY,
    fired_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ticker TEXT NOT NULL,
    signal TEXT NOT NULL,     -- TRIM/WATCH/ADD/MONITOR/HOLD
    rule TEXT NOT NULL,       -- R1..R12
    note TEXT,
    thesis_groups JSONB,
    portfolio_pct NUMERIC,
    INDEX(ticker, fired_at),
    INDEX(fired_at)
);

CREATE TABLE beta_history (
    ticker TEXT NOT NULL,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    beta NUMERIC NOT NULL,
    r_squared NUMERIC,
    n_observations INTEGER,
    source TEXT,              -- yfinance_regression_3y_weekly, morningstar_3y, etc
    PRIMARY KEY (ticker, computed_at)
);

CREATE TABLE ai_recommendation_history (
    id SERIAL PRIMARY KEY,
    generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    section TEXT NOT NULL,    -- executive_summary, v_strategy, etc
    run_type TEXT NOT NULL,   -- daily, weekly, monthly
    model TEXT NOT NULL,      -- sonnet, haiku, gpt-4o, ollama
    content TEXT NOT NULL,
    portfolio_signature TEXT, -- hash of portfolio state at generation
    INDEX(section, generated_at),
    INDEX(run_type, generated_at)
);

CREATE TABLE stop_alert_history (
    id SERIAL PRIMARY KEY,
    fired_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ticker TEXT NOT NULL,
    price NUMERIC NOT NULL,
    stop_price NUMERIC NOT NULL,
    distance_pct NUMERIC NOT NULL,
    ai_decision TEXT,         -- HOLD/WATCH/TRIM/HONOR_STOP/DELAY
    ai_brief TEXT,
    actual_action TEXT,       -- what John actually did
    outcome TEXT,             -- backfilled later
    INDEX(ticker, fired_at)
);
```

These tables add capability JSON can't easily provide:
- "Show me every time V got a TRIM signal in 2026" → single SQL query
- "Has LMT's beta drifted over the past 6 months?" → time-series chart
- "Compare what AI recommended last month vs. what I did" → retrospection
- "Which stop alerts did I honor vs. ignore? What were the outcomes?" → behavioral analysis

### Sub-phase P2: Migrate portfolio_news history (2-3 hours)

Current state: `data/portfolios/portfolio_news_history/` directory with daily JSONs.

Postgres schema:
```sql
CREATE TABLE portfolio_news (
    id SERIAL PRIMARY KEY,
    fetched_at TIMESTAMP NOT NULL,
    ticker TEXT NOT NULL,
    headline TEXT NOT NULL,
    url TEXT,
    source TEXT,              -- finnhub, newsapi, polygon, etc
    score INTEGER,            -- LLM-scored 0-100
    category TEXT,            -- earnings, analyst, company, sector, macro
    urgency TEXT,             -- MONITOR, WATCH, URGENT
    relevance_type TEXT,      -- company_specific, sector_spillover, etc
    brave_context TEXT,
    INDEX(ticker, fetched_at),
    INDEX(score DESC, fetched_at DESC)
);
```

Migration script reads directory → INSERT. Once migrated, `portfolio_news.py` writes directly to Postgres going forward.

Query value:
- "Show me every Visa news item with score > 75 in the last 30 days"
- "What was the urgency distribution of news around the last LMT stop alert?"
- JOIN news events to signal firings to see if news caused the signal

### Sub-phase P3: Snapshots to Postgres (1-2 hours)

You have 16 daily snapshots in `data/portfolios/snapshots/` folder. Schema already exists (portfolio_snapshots table from db_setup.sql). 

Migration: loop over snapshot files, INSERT each. Then update snapshot-writing code to write both JSON (for compatibility) and Postgres (for queries).

Query value:
- "What was my portfolio on January 15?" — single SELECT
- Drift analysis: compare any two dates cleanly
- Performance attribution queries

### Sub-phase P4: Category-2 decisions case-by-case (ongoing)

Not a single migration — case-by-case evaluation. Most Category-2 files correctly stay as JSON. Specific candidates worth considering:

- `trade_journal.json` — has query value (search by ticker, date range, PnL)
- `tax_lots.json` — lot-level detail useful for cost basis queries  
- `dividend_calendar.json` — date-based queries useful for income planning
- `earnings_dates.json` — date-based queries useful for signal Rule 11

**Others should stay as JSON.** Moving ai_analysis_cache to Postgres adds zero value — it's a text blob rewritten every pipeline run.

### Sub-phase P5: Advanced features (future, when needed)

- Read replicas for reporting (if you build a web dashboard)
- TimescaleDB extension for time-series queries (not urgent until P1 tables get large)
- Backup strategy: pg_dump nightly to offsite (SFTP, S3, or USB drive)
- Connection pooling (pgbouncer if concurrent access becomes a problem)

### Recommended execution order

1. **P0 only** — set env vars, run schema, verify existing db_adapter works. Stop. Live on dual-write for a week.
2. **After dual-write stable: P1** — add history tables. This is where Postgres starts paying dividends.
3. **P2 and P3 in parallel** — news and snapshots both benefit, independent of each other.
4. **P4 as needs arise** — don't pre-migrate anything.

### What NOT to do

- **Don't replace all JSON at once.** The existing architecture already correctly distinguishes what should migrate vs. stay.
- **Don't pre-migrate caches.** ai_analysis_cache, risk_management, technical_snapshot, correlation — these are regenerated every run, JSON is fine.
- **Don't skip dual-write.** Run both JSON and Postgres writes for at least a week before retiring JSON. Gives you a fallback.
- **Don't build a migration script that does all 43 files.** Build 5-file scripts for specific categories.

### Acceptance test

After P0 and P1:
- `SELECT COUNT(*) FROM signal_history WHERE fired_at > NOW() - INTERVAL '7 days';` returns meaningful number
- `SELECT * FROM beta_history WHERE ticker = 'V' ORDER BY computed_at DESC LIMIT 5;` shows beta evolution
- Daily pipeline completes with dual-write (JSON + Postgres)
- Recovery test: `rm data/portfolios/state/holdings.json && run pipeline` — system should pull from Postgres, not fail

---

## Small bounded bug fixes (do any order, any time)

These are 15-30 min each. Tackle when you want wins.

**Bug A: Duplicate __main__ block.** Delete lines 750-765. Entire block is copy-paste of lines 733-748.

**Bug B: Dead code in `_exec_summary`.** Lines 428-439 are unreachable code after line 356's return. Delete.

**Bug C: DOCX +7701% gain display bug.** Weekly DOCX (image 14 from tonight) shows "+7701.17%" and "+672.92%" as gains on V and SCHD. This is cost basis being one lot ($1,933) against current market value ($150,844). Fix by ensuring cost basis aggregates across all lots for a symbol, or display "N/A" when cost basis < 10% of market value (clearly incomplete).

**Bug D: Weekly Telegram markdown leak.** Image 13 shows `**Rebalance the portfolio...**` — raw markdown in the weekly Telegram message. The monthly pipeline got `_clean_sonnet()`; the weekly pipeline did not. Apply same function to weekly Telegram payload generation.

**Bug E: Critical Flags `[object Object]` regression watch.** Earlier today Task 4 claimed to fix this. Verify it stays fixed after Phase 1-4 work — no regression.

---

## Recommended sequence

**Weekend session 1 (3-4 hours):**
- Small bug fixes A + B + C + D (quick wins, builds momentum)
- Phase 0 (data freshness gate + refresh script — THE foundation)

**Weekend session 2 (3-4 hours):**
- Phase 1 (hardcoded numbers removal — the big one)

**Weekend session 3 (2-3 hours):**
- Phase 2 (model routing)
- Phase 4 (smart cache)

**Weekend session 4 or mid-week (3-4 hours):**
- Phase 3 (weekly-to-monthly aggregation)

**When GPU arrives:**
- Phase 5 (Intel Arc setup)

**After Phases 0-5 all land and system is stable (multiple sessions over weeks):**
- Phase 6A (Monte Carlo retirement analysis) — 4-5 hours
- Phase 6C (Asset Location optimization) — 3-4 hours
- Phase 6B (Black-Litterman portfolio optimization) — 5-7 hours
- Phase 6D (Efficient Frontier visualization) — 2-3 hours, optional

**Parallel track — ETF Intelligence (can start after Phase 1):**
- Phase 7A (ETF data collection pipeline) — 3-4 hours
- Phase 7B (Ollama weekly ETF context) — 2-3 hours
- Phase 7C (Sonnet/Opus monthly ETF context) — 2-3 hours
- Phase 7D (CC dashboard integration) — 2-3 hours, optional
- Phase 7E (ETF deterioration alerts) — 1-2 hours, polish

**Total:** 11-17 hours for Phases 0-5 (reliability baseline), +15-20 hours for Phase 6 (theory layer), +10-14 hours for Phase 7 (ETF intelligence). Plan for 10-14 focused sessions total.

---

## What NOT to do

- **Do not skip Phase 0.** Data freshness is the foundation. Without it, every other phase produces "correctly-formatted wrong answers." A sophisticated AI analysis of stale data is still wrong — just more convincingly.

- **Do not try to do all phases in one night.** 766-line file + architectural change + Intel Arc integration + portfolio theory = multi-week project. Tonight's session already ran 12+ hours.

- **Do not let Claude Code attempt Phase 1 as a single prompt.** It will produce a sprawling rewrite that looks plausible but has bugs. Instead, do Phase 1 in chunks: one function at a time, verify output, move to next function.

- **Do not defer Phase 1.** Every later phase is built on Phase 1. If hardcoded numbers stay, even Opus will cite "V concentration 49.6%" because that's what's in the prompt.

- **Do not enable GPU Phase 5 before Phases 0-1 are complete.** Bigger model + stale context = more convincing bad analysis.

- **Do not attempt Phase 6 before Phases 0-5 land.** Phase 6 builds on fresh data (Phase 0), clean prompts (Phase 1), proper model routing (Phase 2), and cross-time context (Phase 3). Running portfolio theory math on stale hardcoded inputs produces mathematically correct answers to the wrong question.

- **Do not treat Phase 6 output as financial advice without validation.** Monte Carlo and Black-Litterman can produce plausible-looking output that's mathematically subtly wrong. Validate against external benchmarks (Vanguard MC, published academic results) before acting on any recommendation.

---

## Tomorrow morning checklist

When you come back, you can paste this into Claude Code to start Phase 0 (the data freshness foundation):

```
This is Phase 0 of the portfolio_ai_analyst.py rewrite — data freshness gate and single source of truth.

Before any code changes, investigate ONLY. Report findings. Do NOT make changes yet.

Investigation tasks:

1. Inventory all state files the system reads/writes:
   ls -la data/portfolios/state/
   For each file, identify:
   - Which script produces it (grep scripts/ for write operations)
   - Which scripts/HTML consume it (grep for read operations)
   - Current cadence (daily/weekly/manual)
   - File modification time — how stale is it right now?

2. Determine the current data refresh flow:
   - How does holdings.json get updated? Manual CSV import? Broker API? Something else?
   - Is there a single entry point to refresh everything, or are scripts run individually?
   - When did each state file last update? (check mtimes)

3. Identify data consistency gaps:
   - Could holdings.json be from Monday while action_signals.json is from Wednesday?
   - Is there any existing "snapshot" or "run ID" concept in the code?
   - What happens if portfolio_ai_analyst.py runs when a critical state file is missing?

4. Check for existing refresh logic:
   - grep scripts/ for "refresh" or "reload" or "update_holdings"
   - Is there already a run_all or master script I missed?

Produce a markdown report at /tmp/phase0_investigation.md covering:
- State file inventory table (file → producer → consumer → current age)
- Current data refresh flow (however ad-hoc it is)
- Consistency gaps identified
- Recommendations for how Phase 0 should be implemented given what's already there

Do NOT modify any files yet. Just investigate and report. I need to see your findings before we design the refresh script — it should fit your existing architecture, not fight it.

Stop after producing the investigation report.
```

Then we design the refresh script based on what you find, and proceed with Phase 0 implementation in small verifiable chunks.

After Phase 0 is solid, we move to Phase 1 (hardcoded numbers) one function at a time.
