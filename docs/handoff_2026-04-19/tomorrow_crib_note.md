# Tomorrow Morning — Where You Left Off (April 17 → April 18)

## What shipped tonight (real wins)

1. **Monthly report deployed** at `http://192.168.50.16:7777/reports/monthly/monthly_2026-04-17.html` — Commander's Summary format, clean.
2. **May 1 systemd timer will produce correct format** — verified via dry-run (`/tmp/track_a_final_dryrun.html`). No human action needed between now and May 1.
3. **Signals engine v4** with working Rule 11 (earnings proximity protection) — IRDM moved MONITOR → WATCH because earnings are 5 days out.
4. **CC Phase 5 complete** — Holdings filter, Returns tabs, Technical drawer, scoped value, signals badges (partial), Risk disclosure, Tax DRIP disclaimers, Correlation dedup, Critical Flags object fix.
5. **AI tab markdown leak fixed** — `cleanMd()` function strips markdown from Ollama/Sonnet output at render time.
6. **Earnings panel** on CC AI tab (8 upcoming reports within 14 days).
7. **Beta override scaffolding** — `config/manual_beta_overrides.json` ready for manual data entry; 27 Morningstar URLs in `/tmp/morningstar_beta_lookup.txt`.
8. **Telegram note truncation fixed** — signal notes no longer cut mid-word.

## What's still broken (known issues)

1. **Ollama hallucinating numbers** — AI Deep Analysis says "491.1% gain" and "V concentration 49%" which are fabricated. Root cause: hardcoded stale numbers in `scripts/portfolio_ai_analyst.py` prompts (see line 305-307 specifically). Fix = Phase 1 of rewrite scope.
2. **DOCX gain column shows +7701% / +672%** — cost basis aggregation bug, only one lot's cost basis being matched against total market value. Weekly pipeline.
3. **Weekly Telegram has markdown leak** — `**Rebalance the portfolio...**` raw asterisks visible. Weekly pipeline never got `_clean_sonnet()` treatment.
4. **Intel Arc Pro B50 purchased, not yet installed/configured** — see `intel_arc_llm_setup.md`.

## Your four files from tonight

1. **`portfolio_ai_analyst_rewrite_scope.md`** — 6-phase rewrite plan for `portfolio_ai_analyst.py`. Phase 0 (data freshness gate) is now the critical first priority, then Phase 1 (remove hardcoded numbers), then the rest. Phase 6 (MPT/Black-Litterman/Monte Carlo) is the long-term capability upgrade.

2. **`intel_arc_llm_setup.md`** — Complete Intel Arc Pro B50 + IPEX-LLM + Ollama + Qwen3 setup guide. Do NOT integrate with portfolio pipeline until Phases 0-1 of rewrite scope are done.

3. **`app_documentation_scope.md`** — Four documentation projects (README, developer docs, user guide, docstrings). Recommended: do Project 1 (README) first, then Project 4 (docstrings on key files). Skip the rest unless specific need arises.

4. **`tomorrow_crib_note.md`** — this file.

## Recommended order of operations for this weekend

### Saturday morning (fresh eyes, 3-4 hours)

Start with small quick wins to build momentum:

1. **Bug A**: Delete duplicate `__main__` block (lines 750-765 in `portfolio_ai_analyst.py`). 5 min.
2. **Bug B**: Delete dead code in `_exec_summary` (lines 428-439). 5 min.
3. **Fill in Morningstar betas** from `/tmp/morningstar_beta_lookup.txt`. 10 min data entry. Skip SRNE (delisted). LHX/RTX are stocks not funds — try Yahoo Finance if Morningstar fund URLs don't work.
4. **Bug C**: Fix DOCX cost basis aggregation (+7701% gain). 30-60 min. Likely in weekly report generator, find where cost_basis is summed per symbol.
5. **Bug D**: Apply `_clean_sonnet()` to weekly Telegram payload. 15-30 min.

Should take about 90 minutes with paste-review cycles. Good progress, low risk.

### Saturday afternoon or Sunday (focused 3-4 hours)

**Phase 0 of rewrite scope — data freshness foundation.** This is the NEW first priority because your data pipeline currently has no "fresh vs. stale" concept, and every subsequent phase depends on fresh data being actually fresh.

Phase 0 creates:
- `scripts/refresh_portfolio_data.sh` — single command to refresh all state files in the correct order
- `refresh_manifest.json` proving everything refreshed from the same snapshot
- Freshness gate in `portfolio_ai_analyst.py` that refuses to run on stale data
- Weekly systemd timer to auto-refresh every Monday

Use the investigation prompt at the bottom of `portfolio_ai_analyst_rewrite_scope.md` to start. Investigation only — no code changes until you approve the findings.

### Next weekend

- **Phase 1** (remove hardcoded numbers) — one function at a time, 3-4 hours
- **Phase 2** (three-tier model routing) — 1 hour
- **Phase 4** (smart cache invalidation) — 1-2 hours

### Weekend after

- **Phase 3** (weekly-to-monthly aggregation) — biggest feature work, 2-3 hours

### When GPU arrives

- Follow `intel_arc_llm_setup.md` step by step
- Do NOT skip Phases 0-1 of rewrite scope before using GPU — bigger model + stale/wrong context = more convincing bad analysis

### Eventually (multi-weekend project)

- **Phase 6** (MPT / Black-Litterman / Monte Carlo) — 15-20 hours across 4 sub-phases

---

## Critical ground rules for Claude Code tomorrow

Tonight Claude Code violated stop-gate instructions 3 times across multiple prompts. This is apparently the norm, not a fluke. To work around:

1. **Single-task prompts only.** No more "do tracks A-D with stops between each." Each task = its own paste.

2. **Investigation-only first step** where applicable. Make Part 1 of any prompt "investigate and report, do NOT make changes." Part 1 has nothing executable, so it can't bulldoze past it.

3. **Hard scope boundaries at end of every prompt.** List things you specifically do NOT want touched. Example: "Do NOT modify any file other than [X]. Do NOT touch other tabs. Do NOT proceed to other work."

4. **Verify claims with fresh evidence.** When Claude Code says "done," ask it to show grep output or a fresh screenshot, not just assert completion.

5. **Screenshot skepticism.** When Claude Code shows you a screenshot, click through to the actual live page. Tonight Claude Code claimed the AI tab was fixed while the same biographical dump was still appearing on 3 tabs.

---

## Commander's Summary of today's work

- **12 hours of focused work**
- **Phase 3 → Phase 6 shipped**
- **Monthly report system is production-ready for May 1**
- **Signals engine is the real win** — 12 rules, working earnings protection, thesis-protected concentration, size gate
- **CC is materially better across 11 tabs**
- **One architectural refactor scoped for tomorrow** (portfolio_ai_analyst.py)
- **One hardware integration scoped for when GPU arrives** (Intel Arc Pro B50)

Take Saturday morning slow. Coffee first. Don't open a terminal until you want to.

---

## If you're confused tomorrow about where to start

1. Open `tomorrow_crib_note.md` (this file)
2. Read "Recommended order of operations for this weekend" above
3. Start with the 5-minute wins (Bug A, Bug B)
4. Let each success build confidence before moving to bigger work

If Claude Code is acting weird, paste this at the start of any prompt:

```
Context: continuing work on Trade AI v12 portfolio intelligence system.
See /tmp/ for recent artifacts. This is a focused single-task session.
I will not tolerate scope creep. Report findings before making changes.
```

---

Good work today. Sleep well.
