# OpenClaw Enhancement Session — 2026-05-20

**Status:** COMPLETE — 5 enhancements applied, skills 15→17 ready

## System State

- OpenClaw 2026.4.14 (323493f)
- Gateway PID: 3176497
- Primary model: ollama/qwen3:14b
- Fallbacks: openai/gpt-5.4-mini → anthropic/claude-sonnet-4-6
- Agents: main, steph, aegis, alex, iris
- Telegram: enabled
- Skills: 17/54 ready (was 15/54)

## Enhancements Applied

### 1. Session-Logs Skill Enabled

**Problem:** Skill blocked by missing `rg` (ripgrep) binary.

**Fix:** Symlinked Claude Code's bundled ripgrep to `~/.local/bin/rg`:
```bash
ln -sf /usr/lib/node_modules/@anthropic-ai/claude-code/vendor/ripgrep/x64-linux/rg ~/.local/bin/rg
```

**Value:** Search past conversations from Telegram — "what did we discuss about Roth conversions last week?"

**Test:** `what did we talk about last week regarding Roth conversions?`

### 2. Steph SOUL.md — Live API Integration

**Problem:** Steph quoted static portfolio numbers baked into SOUL.md instead of fetching live data.

**Fix:** Added 8 live API endpoints to SOUL.md with explicit instructions to always fetch before answering:
- `/api/v2/overview` — portfolio totals and returns
- `/api/v2/holdings` — full holdings with gain/loss
- `/api/v2/attribution` — alpha, CAGR, Sharpe, Sortino vs benchmark
- `/api/v2/risk-regime/status` — current market regime
- `/api/v2/paper-proposals` — pending trade proposals
- `/api/v2/paper-journal` — closed trade outcomes
- `/api/v2/strategy-rotation/signals` — strategy favor/de-emphasize
- `/api/v2/strategy-rotation/alignments` — trade regime alignment

**Rule added:** "NEVER quote the static portfolio numbers in this SOUL.md — always fetch live"

**Test:** `@steph what's my portfolio value right now?`

### 3. Roth Conversion Headroom Calculator

**Problem:** Steph could discuss Roth conversions conceptually but couldn't compute actual headroom.

**Fix:** Added full 2026 MFS tax bracket table and income estimation to SOUL.md:
- SSDI: $45,600/yr (85% taxable = $38,760)
- Schedule C: ~$12,000 net
- Estimated taxable: ~$50,760
- Headroom to stay in 22%: ~$52,590
- Headroom to stay in 24%: ~$146,540
- IRMAA warning at $103K MFS MAGI
- Standard deduction reminder ($15,700 MFS)
- 401k rollover timing note (2027)

**Test:** `@steph how much Roth conversion headroom do I have?`

### 4. Concentration Alert Thresholds

**Problem:** No automatic risk flags when reviewing portfolio.

**Fix:** Added threshold rules to SOUL.md:
| Alert | Threshold |
|-------|-----------|
| Single stock concentration | >10% of portfolio |
| Sector concentration | >30% of portfolio |
| Account concentration | >50% of portfolio |
| Low cash | <3% of portfolio |
| Cash drag | >10% of portfolio |
| Loss review trigger | Position down >20% from cost |
| Yield check | <1% on income positions |

**Instruction:** Auto-run these checks on "how does my portfolio look?" or "any risks?"

**Test:** `@steph any concentration risks in my portfolio?`

### 5. Daily Portfolio Brief Skill

**Problem:** No structured one-command morning briefing.

**Fix:** Created `wealth/daily-portfolio-brief` skill at:
`~/.openclaw/skills/wealth/daily-portfolio-brief/SKILL.md`

**Format:**
```
DAILY PORTFOLIO BRIEF — [date]
PORTFOLIO: $[total] ([change] today)
REGIME: [label] (conf [pct]%)
CONCENTRATION ALERTS: [flags]
PENDING ACTIONS: [proposals]
FOCUS TODAY: [1-2 items]
```

**Triggers:** "morning brief", "daily brief", "portfolio brief", "how's my portfolio"

**Test:** `@steph morning brief`

## Not Done (Blocked)

| Skill | Blocker |
|-------|---------|
| summarize | Requires brew (macOS only), no Linux binary |
| session-logs on PATH | rg symlinked but may need PATH in openclaw-gateway env |
| apple-notes/reminders | macOS only |
| slack plugin | Upstream bug: missing register/activate export in bundled plugin |
| model-usage | Requires CodexBar CLI (not installed) |

## Files Modified

| File | Change |
|------|--------|
| `~/.openclaw/agents/steph/agent/SOUL.md` | Added live API endpoints, Roth calculator, concentration alerts |
| `~/.local/bin/rg` | Symlink to Claude Code's bundled ripgrep |
| `~/.openclaw/skills/wealth/daily-portfolio-brief/SKILL.md` | New daily briefing skill |

## Known Issue: `openclaw status` Crashes

The `slack` bundled plugin has a missing `register/activate` export, causing `openclaw status` to crash with `PluginLoadFailureError`. This is an upstream OpenClaw bug — no user-side fix available. The gateway itself runs fine (PID 3176497).
