# Hermes Phase 30D — Expanded Backlog Staged-Write Mapping

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no DB writes

---

## Purpose

Map the 11 backlog candidates from the expanded Librarian dry-run to future hermes_research_intelligence staging. This is a design doc — no staging occurs in Phase 30.

---

## Mapping: Findings → Backlog Rows

### From Journal Findings

| Finding | Target research_type | symbol | priority | owner |
|---------|---------------------|--------|----------|-------|
| JRN-ALL: Journal empty | research_backlog | NULL | medium | hermes_librarian_agent |

### From Backtest Findings

| Finding | Target research_type | symbol | priority | owner |
|---------|---------------------|--------|----------|-------|
| BT-5: swing_trade SHMD 0% | research_backlog | SHMD | low | hermes_librarian_agent |
| BT-5: core_growth_compounder 0% | research_backlog | NULL | low | hermes_librarian_agent |
| BT-5: recovery_watch 0% | research_backlog | NULL | low | hermes_librarian_agent |
| BT-5: earnings_catalyst 0% | research_backlog | NULL | low | hermes_librarian_agent |
| BT-1: combined 27.59% (n=29) | research_backlog | NULL | high | hermes_librarian_agent |
| BT-1: momentum_scalp 30% (n=20) | research_backlog | NULL | high | hermes_librarian_agent |
| BT-1: all_signals 33.9% (n=59) | research_backlog | NULL | high | hermes_librarian_agent |
| BT-3: combined pf=0.3153 (n=29) | research_backlog | NULL | medium | hermes_librarian_agent |

### From Screener Findings

| Finding | Target research_type | symbol | priority | owner |
|---------|---------------------|--------|----------|-------|
| MS-1: Underfilled runs | research_backlog | NULL | low | hermes_librarian_agent |

### From Catalyst Findings

| Finding | Target research_type | symbol | priority | owner |
|---------|---------------------|--------|----------|-------|
| CAT-2: Generic catalysts | research_backlog | NULL | medium | source_discovery_agent |

---

## Recommended Staging Priorities for Phase 32

If a future phase stages these, the recommended top 5 (de-duplicated, highest value):

| # | Title | Priority | Reason |
|---|-------|----------|--------|
| 1 | Journal learning system is empty | medium | System gap — learning loop inactive |
| 2 | momentum_scalp 30% win rate (n=20) | high | Most active strategy, meaningful sample |
| 3 | all_signals aggregate 33.9% (n=59) | high | Largest sample, system-wide concern |
| 4 | Combined strategies 27.59% (n=29) | high | Multi-strategy underperformance |
| 5 | Generic catalyst classification gap | medium | Affects catalyst quality across pipeline |

The BT-5 findings (0% win rate, n=1) are too small to stage individually — better tracked as a group "insufficient backtest samples" item.

---

## No DB Writes in Phase 30D

This is design only. Staging requires separate Phase 32 approval.
