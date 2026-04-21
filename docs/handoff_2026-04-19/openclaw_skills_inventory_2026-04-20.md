# OpenClaw Installed Skills Inventory

**Date:** 2026-04-20
**Author:** Claude Opus 4.6
**Status:** Read-only discovery — no modifications made

---

## 1. Executive Summary

| Count | Status |
|-------|--------|
| **7 skill groups** | Confirmed at `~/.openclaw/skills/` |
| **14 individual sub-skills** | Confirmed via SKILL.md files |
| **1 duplicate** | `wealth/steph-wealth-advisor` is an older copy of `steph-wealth-advisor` (root-level is newer) |
| **1 operational skill** | `tradeai-safe-ops` — directly relevant to the portfolio agent ecosystem |

All skills confirmed via SKILL.md frontmatter + directory contents. No uncertainty.

---

## 2. Skills Inventory Table

| Group | Sub-Skill | Purpose | Agent | Advisor Reuse |
|-------|-----------|---------|-------|:---:|
| **email-calendar** | email-draft-assistant | Draft/rewrite/polish emails | Maria | Low |
| | follow-up-builder | Craft follow-up messages | Maria | Low |
| | meeting-prep-helper | Agenda, questions, outcomes for meetings | Maria | Low |
| **integrations** | github | GitHub CLI interactions (gh) | Maria | Low |
| | gog | Google Workspace CLI (Gmail, Calendar, Drive) | Maria | **Medium** |
| **light-research** | option-compare | Compare 2-5 options with criteria | Maria | Medium |
| | research-summarizer | Summarize topics/documents | Maria | Medium |
| | source-action-extractor | Extract actions from notes/threads | Maria | Low |
| **operations** | tradeai-safe-ops | Run portfolio pipelines safely | Maria/Steph | **High** |
| **personal-productivity** | daily-planner | Turn brain dumps into plans | Maria | Low |
| | next-step-checklist | Convert tasks to actionable checklist | Maria | Low |
| | summary-cleanup | Clean rough notes into readable summaries | Maria | Low |
| **steph-wealth-advisor** | (root skill) | Portfolio Q&A, Roth, concentration, rebalancing | Steph | **High** |
| **wealth** | steph-wealth-advisor | Older copy of above | Steph | Deprecated |

---

## 3. Skill-by-Skill Notes

### email-calendar (3 sub-skills)

| Sub-Skill | Generic? | Maria overlap | Steph overlap | Portfolio advisor relevance |
|-----------|:---:|:---:|:---:|:---:|
| email-draft-assistant | ✓ Generic | ✓ Direct Maria use | None | Low — but future Gmail notifications could reuse draft patterns |
| follow-up-builder | ✓ Generic | ✓ Direct Maria use | None | Low |
| meeting-prep-helper | ✓ Generic | ✓ Direct Maria use | None | None |

**Notes:** These are Maria-owned personal productivity skills. The portfolio advisor wouldn't draft emails — it would generate structured alert content. But the `gog` integration (in `integrations/`) handles actual Gmail send, which IS relevant.

### integrations (2 sub-skills)

| Sub-Skill | Generic? | Maria overlap | Steph overlap | Portfolio advisor relevance |
|-----------|:---:|:---:|:---:|:---:|
| github | ✓ Generic | ✓ Maria tool | None | None |
| gog | ✓ Generic | ✓ Maria tool | None | **Medium** — Gmail send capability needed for advisor notifications |

**Notes:** `gog` is the Google Workspace CLI wrapper. The future portfolio advisor will need Gmail send capability for alerts/digests. Rather than building a custom email skill, it should reuse `gog gmail send` (or the Google Calendar/Gmail MCP servers already configured in `openclaw.json`).

### light-research (3 sub-skills)

| Sub-Skill | Generic? | Maria overlap | Steph overlap | Portfolio advisor relevance |
|-----------|:---:|:---:|:---:|:---:|
| option-compare | ✓ Generic | ✓ Maria research | Mild (could compare tickers) | Medium — rotation analysis is "compare options" |
| research-summarizer | ✓ Generic | ✓ Maria research | Mild | Medium — article summarization pattern similar |
| source-action-extractor | ✓ Generic | ✓ Maria tool | None | Low |

**Notes:** The `research-summarizer` and `option-compare` patterns are conceptually similar to what the portfolio advisor does (summarize market research, compare alternatives). However, these are generic text-processing skills — the advisor needs domain-specific financial logic that wouldn't fit these generic wrappers.

### operations (1 sub-skill)

| Sub-Skill | Generic? | Maria overlap | Steph overlap | Portfolio advisor relevance |
|-----------|:---:|:---:|:---:|:---:|
| tradeai-safe-ops | Project-specific | Shared (Maria can trigger) | Shared (Steph can trigger) | **HIGH** — portfolio agent may need to trigger pipelines |

**Notes:** This skill wraps the Trade AI pipeline commands (daily, weekly, monthly-lite, price-cache, status). Boundaries are explicit: no monthly-full, no service restarts, no secrets exposure. The future portfolio advisor would NOT use this conversationally — it would call the same scripts directly as a background service. But the command inventory here is exactly what the advisor monitors.

### personal-productivity (3 sub-skills)

| Sub-Skill | Generic? | Maria overlap | Steph overlap | Portfolio advisor relevance |
|-----------|:---:|:---:|:---:|:---:|
| daily-planner | ✓ Generic | ✓ Direct Maria use | None | None |
| next-step-checklist | ✓ Generic | ✓ Direct Maria use | None | None |
| summary-cleanup | ✓ Generic | ✓ Direct Maria use | None | None |

**Notes:** Pure Maria skills. No relevance to portfolio advisor.

### steph-wealth-advisor (root-level, CURRENT)

**The primary financial skill.** 96 lines of SKILL.md with:
- Explicit routing rules ("ask Steph...")
- Data file priority (holdings.json first, then enrichment, then Finviz/Yahoo)
- Sector resolution rules (use `resolved_sectors`, not per-holding `sector_type`)
- Fund look-through rules (use `fund_lookthrough.json`)
- Overlap analysis awareness
- Response structure (Snapshot → What matters → Risks → Next step → Data foundation)
- External LLM permission gate

**Contains detailed data file documentation:** holdings.json, performance_history.json, technical_snapshot, enrichment cache, news, signals, stops, dividend calendar, etc.

### wealth/steph-wealth-advisor (OLDER COPY)

**Shorter version** (25 lines vs 96). Missing:
- Sector resolution rules
- Fund look-through rules
- Overlap analysis awareness
- Detailed data file documentation
- "Updated: April 15, 2026" header

**Verdict:** The `wealth/` copy is deprecated. The root-level `steph-wealth-advisor/` is the current version.

---

## 4. Wealth / Steph Skill Analysis

### `steph-wealth-advisor` (root-level, `/skills/steph-wealth-advisor/`)
- **Status:** CURRENT — actively used
- **Last updated:** April 15, 2026
- **Scope:** Full portfolio Q&A including fund look-through, overlap, sector resolution, data file documentation
- **Contains:** `SKILL.md` + `agents/openai.yaml` + `references/` + `scripts/`

### `wealth/steph-wealth-advisor` (nested, `/skills/wealth/steph-wealth-advisor/`)
- **Status:** DEPRECATED — older shorter version
- **Missing:** Sector rules, fund look-through, overlap, detailed data docs
- **Likely origin:** Early deployment before April 15 updates

### Overlap
They are the SAME skill — one is just an outdated copy in a parent `wealth/` group. No functional overlap or conflict between separate capabilities.

### Recommendation
- Delete or ignore `wealth/steph-wealth-advisor` — it's superseded
- Root-level `steph-wealth-advisor/` is authoritative
- Future portfolio agent should NOT clone this skill — it has a different operating model (background vs conversational)

---

## 5. Reuse vs New Build Recommendation

### Reuse as-is

| Skill | Why reuse | For whom |
|-------|-----------|----------|
| `gog` (integrations) | Gmail send capability for advisor notifications | Portfolio advisor (via `gog gmail send`) |
| `tradeai-safe-ops` | Status checks, pipeline triggers | Portfolio advisor (for monitoring) |

### Clone/customize

| Skill | Why customize | For whom |
|-------|--------------|----------|
| `steph-wealth-advisor` | The data file documentation and priority hierarchy is useful as a reference for the advisor. Don't clone the skill itself, but extract the data-access patterns into the advisor's own config. | Portfolio advisor (as design reference) |

### Do NOT reuse

| Skill | Reason |
|-------|--------|
| email-calendar/* | Maria-specific, too generic for financial alerts |
| personal-productivity/* | Maria-only, irrelevant to portfolio monitoring |
| light-research/* | Too generic — advisor needs domain-specific financial reasoning |
| github | Irrelevant |
| wealth/steph-wealth-advisor | Deprecated copy |

### New custom skills needed

The portfolio advisor likely won't be a "skill" at all (it's a background service, not a conversational interaction pattern). But if it exposes capabilities TO Steph, those would be registered as skills for Steph to invoke.

---

## 6. Proposed Custom Skill Candidates

### For the portfolio advisor to PROVIDE (Steph queries these)

| Candidate | Purpose | Owner | Generic? |
|-----------|---------|-------|:---:|
| `advisor-observations-query` | "What has the advisor noticed this week?" — Steph queries the observation database | Steph (consumer), Advisor (provider) | Project-specific |
| `dividend-yield-tracker` | "Show me SCHD yield history" — query dividend_history table | Steph (consumer), Advisor (provider) | Project-specific |
| `signal-history-query` | "How long has V been TRIM?" — query action_signals_history | Steph (consumer), Advisor (provider) | Project-specific |

### For the portfolio advisor to USE (background capabilities)

| Candidate | Purpose | Owner | Timing |
|-----------|---------|-------|--------|
| `dividend-history-ingestion` | Write daily yield snapshots to Postgres | Portfolio advisor | Phase A1 |
| `advisor-observation-writer` | Write rule-based observations from pipeline data | Portfolio advisor | Phase A1 |
| `analyst-consensus-ingestion` | Scrape and store analyst ratings | Portfolio advisor | Phase B |
| `article-metadata-indexer` | Index news/articles consumed by pipeline | Portfolio advisor | Phase B |
| `sentiment-monitor` | Score Reddit/StockTwits for portfolio tickers | Portfolio advisor | Phase B |
| `recommendation-validator` | External model validation of high-confidence findings | Portfolio advisor | Phase D |

**Key insight:** These are NOT OpenClaw "skills" in the SKILL.md sense — they're background pipeline steps. They only become "skills" if Steph needs to invoke them conversationally. The actual portfolio advisor runs as a service, not as a conversational agent.

---

## 7. Architecture Fit Recommendation

### Skill ownership by agent

| Agent | Skills owned |
|-------|-------------|
| **Maria** | email-calendar/*, personal-productivity/*, light-research/*, integrations/github, integrations/gog |
| **Steph** | steph-wealth-advisor (root), operations/tradeai-safe-ops |
| **Portfolio Advisor** | NEW: advisor-observations-query, dividend-yield-tracker, signal-history-query (exposed TO Steph) |

### How they interact

```
Maria → routes financial questions to Steph
Steph → answers from local data + can query advisor observations
Portfolio Advisor → background service, writes to Postgres, exposes queryable skills to Steph
```

### Division principle

- **Conversational skills** (SKILL.md pattern) = Maria + Steph. User-facing. Interactive.
- **Background capabilities** (pipeline pattern) = Portfolio Advisor. No user interaction. Timer-driven. Writes to DB.
- **Bridge skills** = Small query-focused skills that let Steph read the advisor's findings conversationally.

---

## 8. Risks / Conflicts

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Duplicate notification risk** | MEDIUM | Maria owns email drafting; portfolio advisor generates alert CONTENT. Use gog for Gmail delivery but not email-draft-assistant skill. |
| **`tradeai-safe-ops` authority confusion** | LOW | The skill is for conversational triggering. Background advisor calls pipelines directly, doesn't use the skill wrapper. |
| **Steph querying stale observations** | MEDIUM | Bridge skills should include freshness metadata. Steph should report "advisor last observed 2h ago" not just raw data. |
| **`wealth/` deprecated skill still loaded** | LOW | May confuse skill routing if both resolve to same name. Delete `wealth/steph-wealth-advisor/` or rename. |
| **Portfolio advisor impersonating Steph** | LOW | Clear boundary: advisor writes to DB only. Steph reads from DB and speaks to user. Advisor never speaks directly. |
| **Hidden coupling via shared data files** | MEDIUM | Both Steph and the advisor read holdings.json, performance_history.json, etc. Steph reads live; advisor reads at pipeline time. Timestamps prevent confusion. |

---

## 9. Appendix

### File paths discovered
```
~/.openclaw/skills/email-calendar/email-draft-assistant/SKILL.md
~/.openclaw/skills/email-calendar/follow-up-builder/SKILL.md
~/.openclaw/skills/email-calendar/meeting-prep-helper/SKILL.md
~/.openclaw/skills/integrations/github/SKILL.md
~/.openclaw/skills/integrations/gog/SKILL.md
~/.openclaw/skills/light-research/option-compare/SKILL.md
~/.openclaw/skills/light-research/research-summarizer/SKILL.md
~/.openclaw/skills/light-research/source-action-extractor/SKILL.md
~/.openclaw/skills/operations/tradeai-safe-ops/SKILL.md
~/.openclaw/skills/personal-productivity/daily-planner/SKILL.md
~/.openclaw/skills/personal-productivity/next-step-checklist/SKILL.md
~/.openclaw/skills/personal-productivity/summary-cleanup/SKILL.md
~/.openclaw/skills/steph-wealth-advisor/SKILL.md (CURRENT — 96 lines, April 15 2026)
~/.openclaw/skills/wealth/steph-wealth-advisor/SKILL.md (DEPRECATED — shorter version)
```

### Commands used
```bash
find ~/.openclaw/skills -name "SKILL.md" | sort
ls -la ~/.openclaw/skills/
for d in ~/.openclaw/skills/*/; do ls "$d"; done
diff skills/steph-wealth-advisor/SKILL.md skills/wealth/steph-wealth-advisor/SKILL.md
cat skills/operations/tradeai-safe-ops/SKILL.md
```

### Unresolved questions
- **Are all skills actively loaded?** The gateway likely auto-discovers skills from the `~/.openclaw/skills/` directory, but the exact loading mechanism wasn't investigated.
- **Can skills be assigned to specific agents only?** AGENTS.md in Maria's workspace routes to Steph, but it's unclear if the gateway enforces skill→agent binding or if any agent can use any skill.
- **What's in `steph-wealth-advisor/scripts/`?** Directory exists but contents weren't examined — may contain helper scripts for data access.
- **What's in `steph-wealth-advisor/references/`?** May contain reference documents that inform Steph's responses.
