# Trade AI v12 — Application Documentation Scope

**Status:** Requested end of April 17 2026 session. Deferred from "do it tonight" because the phrase "document the whole app" can mean four very different projects with different audiences and effort levels. This doc scopes each one so you can pick which (if any) to execute.

**Goal:** Produce the documentation that actually earns its keep, without writing documentation for the sake of it.

---

## TL;DR — Which one should I do?

If you're unsure, do **Project 1 (README) first, then Project 4 (docstrings)**. Together ~10-14 hours, highest ROI, everything else can be skipped or deferred.

Skip Project 2 (developer docs) unless you're planning to hire a contractor.

Project 3 (user guide) is nice polish but not urgent — do it if you ever plan to show the system to someone else (investment partner, family member, etc.).

---

## Project 1: README for future-John

**Audience:** You in 6 months when you've forgotten how the system works.

**Why this matters:** You've built a sophisticated system over many months. Today you know every file, every flow, every gotcha. Six months from now you'll remember 30% of it. A well-written README bridges that gap in 10 minutes of reading instead of 3 hours of code archaeology.

### Scope

A single file at `~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/README.md` covering:

**1. What this project is** (1 paragraph)
- What problem it solves
- High-level architecture (1-2 sentences)

**2. System overview diagram** (ASCII or markdown table)
- Inputs: CSV imports, price feeds
- Core pipelines: daily, weekly, monthly
- Outputs: CC dashboard, Telegram, HTML/DOCX reports

**3. Architecture** (~2 pages)
- Backend: Python, JSON state files, no database (yet)
- Frontend: CC at port 7777, server.py + HTML/JS
- AI layer: Sonnet (monthly flagship), Haiku (exec summary), Ollama qwen3 (weekly), planned Opus for monthly synthesis
- Signals engine: 12-rule mechanical rules, outputs action_signals.json
- Integration points: Telegram bot, Google Drive, Fidelity NetBenefits (manual), Schwab (CSV export)

**4. Directory layout** (filesystem tree, annotated)
```
trade-ai-v12-rebuild/
├── scripts/              # All Python entry points
│   ├── portfolio_daily.py
│   ├── portfolio_weekly.py
│   ├── portfolio_monthly_report.py
│   ├── portfolio_signals.py         # Rules engine
│   ├── portfolio_ai_analyst.py      # Sonnet/Opus/Ollama AI
│   └── ...
├── data/portfolios/
│   ├── state/            # JSON state (refreshed by pipelines)
│   ├── reports/          # Generated HTML/DOCX (served)
│   └── imports/          # CSV drops from Schwab/Fidelity
├── reports/              # Served static HTML (command_center.html, monthly/)
├── config/               # YAML config (thesis, personal_situation, etc.)
├── assets/               # Fixed data (portfolio_accounts.yaml, etc.)
└── README.md             # THIS FILE
```

**5. Common operations** (cheat sheet)
- "I want to refresh all portfolio data": `./scripts/refresh_portfolio_data.sh`
- "I want to regenerate the monthly report without sending Telegram": specific command
- "I want to see why a signal fired": which JSON to read, how to interpret
- "I want to add a new rule to the signals engine": which file, which pattern
- "The May 1 monthly report fired wrong": where to look in logs

**6. Known quirks and gotchas** (the things that will bite you later)
- Monthly runner button on CC calls `run_portfolio_monthly_lite.sh` (no Ollama, no DOCX). Full monthly only runs via systemd Monday 1st of month 7:05 AM.
- Fidelity 401k constraint: AI suggestions restricted to plan funds until 2027 rollover
- V concentration is 15.9% of portfolio (12.5% Rollover + 3.4% Roth), NOT 49% — don't be fooled by stale hardcoded numbers in prompts (see Phase 1 of rewrite scope)
- Ollama qwen3:1.7b hallucinates specific numbers — output must be sanity-checked, not trusted blindly
- Finviz v=141 column mapping has been unstable historically — if earnings data breaks, check column mapping first
- Signal R11 (earnings proximity) requires `earnings_dates.json` to be fresh — stale earnings data = R11 never fires

**7. "If everything breaks" recovery** (half a page)
- Systemd timer locations and how to restart
- Where logs live (journalctl -u portfolio-*.service)
- How to revert to last known good: git commands if under version control
- How to manually deploy a monthly report if the automated pipeline fails

### What NOT to include in Project 1

- Line-by-line code explanation (that's Project 4, docstrings)
- How to onboard a new developer from scratch (that's Project 2)
- User-facing "what does each CC tab mean" (that's Project 3)

### Effort
2-3 hours. Most of this is structured thinking you can do in prose without writing new code.

### Acceptance test
Six months from now, read only the README. Can you remember how to:
1. Manually regenerate a monthly report?
2. Explain what the signals engine does and what its rules are?
3. Find where action_signals.json lives and how to interpret its contents?
4. Restart the automated pipelines after a reboot?

If yes to all four, README succeeded.

---

## Project 2: Developer onboarding documentation

**Audience:** A contractor or collaborator you hire to work on the system. Or a future version of yourself who returns after 2+ years away.

**Why this might matter:** If you ever want help with this system (beyond Claude Code), whoever you bring on will need 10-20 hours of ramp time without docs, versus 2-3 hours with good docs.

**Why this usually doesn't matter:** You're not hiring anyone. Don't write docs for a hypothetical contractor who won't arrive. Skip this unless/until you're actively planning to bring someone on.

### Scope (only if needed)

Either:
- A `docs/` folder with ~10 markdown files, OR  
- A generated docs site using MkDocs or Sphinx

Content (the things that take hours of code reading to figure out):

**1. Architecture deep-dive** (4-6 pages)
- Why JSON state files instead of a DB (pros/cons)
- How the three pipelines (daily/weekly/monthly) differ
- Why Sonnet for monthly + Ollama for weekly (cost/quality tradeoff)
- Where the critical path lives (if THIS breaks, the whole system breaks)

**2. Each module explained** (one page per major module)
- portfolio_signals.py: what rules exist, how they compose, how to add new ones
- portfolio_ai_analyst.py: how sections map to prompts, how caching works
- portfolio_monthly_report.py: the full pipeline from holdings → HTML → Telegram
- portfolio_risk.py, portfolio_rebalance.py, etc.

**3. Data flow diagrams** (visual — could be Mermaid in markdown)
- Daily flow: CSV import → holdings.json → signals → CC refresh
- Weekly flow: daily output → weekly aggregation → AI analysis → Telegram
- Monthly flow: weekly aggregates × 4 → monthly synthesis → DOCX + Telegram

**4. Testing guidance**
- How to run the pipeline against a sample portfolio without breaking real state
- How to test prompt changes without calling Sonnet API (unit tests on prompt builders)
- How to verify signals engine output (known-portfolio regression suite)

**5. Deployment and operations**
- How systemd timers are configured
- How to SSH to MS-01 and what tmux sessions exist
- How to check service health
- How to roll back a change

### Effort
10-15 hours. Mostly writing, some diagramming. Could be 8 hours if you already have a whiteboard architecture in your head.

### Acceptance test
Hand a competent Python developer the docs. Can they, in 2 hours:
1. Set up the dev environment on their own machine?
2. Run a test pipeline?
3. Understand where to make a change to add a new signal rule?
4. Deploy their change to MS-01?

If yes, Project 2 succeeded.

### When to actually do this
- You're hiring a contractor (post a listing, this becomes required before the first week)
- You're considering open-sourcing parts of the system
- You're considering selling or licensing the system

Until one of those is true, skip.

---

## Project 3: CC user guide

**Audience:** You as the user of the product (not the developer). Or a non-technical family member, partner, or investment advisor you want to share findings with.

**Why this might matter:** CC has a lot of screens. You know what every tab means because you built them. A user guide forces you to articulate the product value clearly — which often reveals where the product is actually confusing.

### Scope

A single markdown file or small website (~10-15 pages) walking through each CC tab:

**Per tab coverage:**
- Screenshot
- Purpose in one sentence
- What each KPI/metric means and how it's calculated
- What to do with the information (when to act)
- Common misinterpretations (e.g., "Portfolio Heat 2.3% sounds low but 82% of portfolio is unprotected, so heat only applies to the 18% with stops")

**Tabs to cover:**
1. Holdings (with filter pills, Flagged chip)
2. Journal
3. Returns (Summary/History/Compare modes)
4. Technical (position cards + drill-down drawer)
5. Tax & Lots (with DRIP caveats)
6. Risk (Portfolio Heat, Escalation Lane)
7. Retirement (Golden Window)
8. Attribution (benchmark comparison)
9. Dividends
10. Watchlist
11. Rebalance
12. Correlation
13. AI (Executive Summary, Action Signals, Deep Analysis, Earnings)

**Plus:** a "Daily/Weekly/Monthly workflow" page describing how to actually use CC day-to-day:
- Morning: check Action Signals card, scan Movers + Sector Posture, review Critical Flags
- Weekly: read the weekly Telegram, review Earnings panel, check for WATCH signals near earnings
- Monthly: read the Commander's Summary, decide on any ADD/TRIM actions from signals table

### Effort
4-6 hours. Most effort is in screenshots and clear-writing, not technical work.

### Acceptance test
Show the user guide (without showing CC) to someone who doesn't know your system. Can they predict what each tab will look like and what it does? Can they describe when they'd use it?

If yes, Project 3 succeeded.

### When to actually do this
- You're planning to show the system to someone else
- You find yourself explaining CC tabs verbally more than twice to the same person
- You want to use CC explanations as marketing/portfolio material (e.g., blog post, professional website)

---

## Project 4: Code-level docstrings and type hints

**Audience:** Your future Claude Code sessions, your IDE, your own code reading, any future reader.

**Why this matters MORE than it sounds:** Every future Claude Code session becomes 30% smarter when functions have docstrings explaining what they do. Every bug-hunting session is faster when you can hover a function and see its purpose. Every refactor is safer when type hints catch mismatches at development time.

This is the most valuable documentation project for a solo developer, because it pays compound returns every time anyone (you or Claude Code) touches the code.

### Scope

Systematic addition of:

**1. Module-level docstrings** (top of every .py file)
```python
"""portfolio_signals.py — Mechanical rules engine for portfolio actions.

Produces action_signals.json with TRIM/WATCH/ADD/MONITOR/HOLD recommendations.
Rules engine v3 with 12 rules covering concentration, stop proximity, 
earnings proximity, dividend gap, RSI extremes, and thesis protection.

Inputs:
    - data/portfolios/state/holdings.json
    - data/portfolios/state/ai_analysis_cache.json (for dividend data)
    - data/portfolios/state/risk_management.json (for stops)
    - data/portfolios/state/earnings_dates.json (for Rule 11)
    - config/thesis.json (thesis groups, targets)

Outputs:
    - data/portfolios/state/action_signals.json

Key functions:
    generate_action_signals() — main entry
    _evaluate_rule_N() — one per rule (R1 through R12)

Invariants:
    - Ticker-level aggregation (V appears once even across 2 accounts)
    - Size gate: positions <0.5% of portfolio MV → MONITOR
    - Thesis-protected positions: TRIM/EXIT downgrades to thesis floor
    - Rule 11: earnings within 7d downgrades TRIM/EXIT to WATCH
"""
```

**2. Function docstrings** (every non-trivial function)

Before:
```python
def _v_strategy(portfolio, rebalancing):
    ctx = _get_context(...)
    return _ai(...)
```

After:
```python
def _v_strategy(portfolio: Dict, rebalancing: Dict) -> str:
    """Generate V (Visa) concentration strategy analysis.
    
    Uses Sonnet for monthly runs, Ollama for weekly runs (via _ai router).
    Output covers: HOLD/TRIM/SELL recommendation, optimal rotation target,
    5-year scenario analysis, timing/execution strategy, emotional risk.
    
    Args:
        portfolio: Portfolio state dict from holdings.json
        rebalancing: Rebalance suggestions dict with v_to_schd_scenario
    
    Returns:
        Prose analysis string (max ~1500 tokens). Contains specific share
        counts, dollar amounts, ticker recommendations.
    
    Note: V position is pulled live from holdings.json (both Rollover IRA
    and Roth IRA accounts aggregated). Hardcoded V business facts (P/E,
    payment volume, etc.) are baked into the prompt for Sonnet context.
    """
    ctx = _get_context(...)
    return _ai(...)
```

**3. Type hints on all function signatures**
```python
# Before
def _should_refresh(state_dir, key, max_days=30):

# After  
def _should_refresh(state_dir: Path, key: str, max_days: int = 30) -> bool:
```

**4. Inline comments on complex logic** (where the "why" isn't obvious from the "what")
```python
# V position weight must aggregate across both Rollover and Roth IRAs because
# concentration rules operate at the ticker level, not account level.
# See Phase 1 of rewrite scope for more.
v_total_pct = sum(h.get("portfolio_pct", 0) for h in holdings if h["symbol"] == "V")
```

**5. Classes and constants documented** at point of definition.

### Effort
8-12 hours. Highly parallelizable across files — do one file at a time, each takes 20-30 min.

### How to actually execute

**Don't hand this to Claude Code as "add docstrings to everything."** You'll get mediocre generic docstrings.

Instead, do it file by file with this pattern:

```
Add module-level docstring + function docstrings + type hints to scripts/portfolio_signals.py.

For each function:
1. Read the full function body
2. Understand what it does from the code (not guesswork)
3. Write a docstring with: one-line purpose, Args, Returns, and Note (for gotchas)
4. Add type hints to signature

Rules:
- Docstrings describe actual behavior, not idealized behavior
- If a function has a known bug or quirk, mention it in Note
- Type hints must match what the function actually returns, including Optional/Union where applicable
- Do not "fix" or "refactor" code while adding docs — doc-only change
- Do not add docstrings to trivial one-liner functions unless their purpose is non-obvious

Output a patched version of the file. I will review before committing.
```

One file at a time. Review each before moving on. A 766-line file like portfolio_ai_analyst.py takes maybe 45-60 min.

### Acceptance test
After Project 4 is done, hover over any function in your IDE (or ask Claude Code "what does X do?"). The answer should be visible immediately in the docstring without reading the function body.

### Priority order
If you only have time to document some files, do them in this order:

1. `portfolio_ai_analyst.py` (most important, most complex, most rewritten) — you'll be working in it for Phases 1-6
2. `portfolio_signals.py` (core business logic, highest value to get right)
3. `portfolio_monthly_report.py` (complex, drives user-facing output)
4. `portfolio_risk.py` (safety-critical)
5. `portfolio_rebalance.py`
6. All other scripts/

---

## Recommended execution plan

### Minimum viable documentation

**Week 1: Project 1 (README)** — 2-3 hours, one weekend morning.

**Week 2-3: Project 4 (docstrings) for top 3 files** — 3 hours per file, spread across 3 sessions.

**Total: ~11-12 hours over 2-3 weekends.** Stop there. Everything else is polish.

### Full documentation pass

**Week 1: Project 1 (README)** — 2-3 hours
**Week 2-4: Project 4 (all files)** — 8-12 hours total
**Week 5: Project 3 (CC user guide)** — 4-6 hours
**When/if hiring: Project 2 (developer docs)** — 10-15 hours

**Total: 24-36 hours if you do everything.** Most people should not do everything.

---

## What to skip entirely

- **"Document every variable"** — noise, not value
- **"Generate auto-docs from source"** without manual review — produces sprawling, low-quality output that hides real information under signal
- **"One master reference doc"** — nobody reads a 200-page wiki. Small focused files > monolithic docs
- **"Keep documentation in a separate wiki/Notion"** for a project this size — harder to keep in sync than code-adjacent markdown
- **Documenting planned features** — only document what exists. Planned features belong in scope docs (like this one), not user docs

---

## Tomorrow morning — what to actually do

Paste this into Claude Code after you've done the small bug fixes A and B:

```
Documentation project — Phase 1: README for future-John.

Single task: create README.md at the root of the trade-ai-v12-rebuild project.

Do NOT invent architecture or functionality. Read the actual scripts and describe what exists.

Structure:

1. What this project is (1 paragraph)
2. Architecture overview (Python + JSON + HTML/JS, no DB, Ollama + Claude API hybrid)
3. Directory layout (ls -R the repo, annotate what each folder/file is for)
4. Common operations (cheat sheet of commands for daily use)
5. Known quirks and gotchas (things you learn the hard way)
6. "If everything breaks" recovery steps

Read these files to understand the architecture before writing:
- scripts/portfolio_daily.py
- scripts/portfolio_weekly.py
- scripts/portfolio_monthly_report.py
- scripts/portfolio_signals.py
- scripts/portfolio_ai_analyst.py
- scripts/portfolio_server.py (or whatever serves CC)
- reports/command_center.html (first 100 lines for structure)
- ls scripts/ (full inventory)
- ls data/portfolios/state/ (what state files exist)

For "Common operations" section, verify commands actually work by checking 
systemd timer files in ~/.config/systemd/user/ and any shell scripts in scripts/.

For "Known quirks", include these known ones (verified tonight):
- Monthly runner button ≠ systemd monthly run (lite vs. full)
- Ollama qwen3:1.7b hallucinates (see Phase 1 of rewrite scope doc)
- V concentration is 15.9%, not 49%
- Signal R11 needs fresh earnings_dates.json

Do NOT include planned features (Phase 0-6 of rewrite scope are NOT yet done 
— don't describe them as if they exist).

Produce README.md at /tmp/README_draft.md. I will review before committing to repo.
```

When draft comes back, read it, verify every claim is true about your actual system, edit, then commit to repo.

Then next weekend, start Project 4 (docstrings) with `portfolio_ai_analyst.py` — but only after Phases 0-1 of the rewrite scope are done, because documenting code that's about to change is wasted effort.

---

## Honest assessment

Documentation is the thing everyone says they value and nobody does. Three failure modes to watch for:

**1. Perfectionism paralysis.** "I'll do it when I know the final architecture." You'll never know. Document what exists now. Revise later.

**2. Over-scoping.** Writing a 200-page bible that nobody reads, including future-you. Keep each doc short enough that reading it is fast.

**3. Never updating.** Docs that lie are worse than no docs. If you change behavior, update the doc. If you won't maintain it, don't write it.

The best documentation is the documentation that gets read. For a solo project, a 5-page README read 20 times is worth more than a 50-page wiki read twice.

Pick small. Pick real. Pick what you'll maintain.
