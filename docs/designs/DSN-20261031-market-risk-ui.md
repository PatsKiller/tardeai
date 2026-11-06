---
id: DSN-20261031-market-risk-ui
title: Market risk on Home and the Risk page (tile, banner with acknowledge, Market-risk tab)
status: LIVE
approval: 'operator, in the coordinator Claude Code session 2026-10-31 ~14:55Z (verbatim) "approved market-risk-ui, check again" then "record it from my message, keep going" — recorded from the message because the Approvals → Designs tap wrote no ledger row (tap defect under fix, design-tap-fix-20261031)'
source: docs/designs/DSN-20261031-market-risk-engine.md (P3-T2); operator 2026-10-31 "mock up the Home and Risk market-risk design"
summary: >-
  Where the Market Risk Engine's output lives in the Command Center. Home: the header "Market" fact becomes a MARKET RISK
  fact (tier colour, score, one-line why) and a full-width banner appears above the header only while Orange or Red is active,
  with the Acknowledge button that silences repeats; the "Market in one look" card gains the five contributors. Risk: the
  "Regime" tab becomes "Market risk" and holds the nine category states, score history, probabilities, episode log and the
  regime panel it replaces. Phone first (390/412), desktop 1440. Mockups (synthetic data) in the private design store; the
  canvas for viewing is a private claude.ai artifact.
phases:
- id: DSN-20261031-market-risk-ui-P1
  title: Home v002 — MARKET RISK fact, Orange/Red banner with Acknowledge, contributors in "Market in one look"
  status: DONE
  tasks:
  - {id: DSN-20261031-market-risk-ui-P1-T1, title: 'Build Home v002 (Design: home/v002) once APPROVED; reads GET /api/v2/market-risk/latest; Acknowledge → POST /api/v2/market-risk/ack', status: DONE, areas: [apps/command-center-v3/src/pages/HomeDoNow.tsx, apps/command-center-v3/src/pages/HomeHub.tsx, apps/command-center-v3/src/lib/designTokens.ts]}
- id: DSN-20261031-market-risk-ui-P2
  title: Risk v002 — "Regime" tab renamed "Market risk" with categories, score history, probabilities, episodes
  status: DONE
  tasks:
  - {id: DSN-20261031-market-risk-ui-P2-T1, title: 'Build Risk v002 (Design: risk/v002) once APPROVED; W7RiskRegime content kept inside the new tab', status: DONE, areas: [apps/command-center-v3/src/pages/RiskHub.tsx, apps/command-center-v3/src/components/W7RiskPanels.tsx]}
---

# Market risk on Home and the Risk page

```
Status:      LIVE — approved by the operator in session 2026-10-31 (see front matter); built in #2321, live in 99bfa4abc
as_of:       2026-10-31T03:20Z
Specs:       the home v002 and risk v002 SPEC.md files under design/pages/<page>/versions/v002/
Mockups:     private store ~/trade-ai-releases/persistent-state/data/design/pages/{home,risk}/v002/mockups (sha256 in status.json);
             viewing copy: claude.ai artifact "Market Risk: Home and Risk mockups" (private to the operator)
Depends on:  DSN-20261031-market-risk-engine P2-T1 (projection + GET /api/v2/market-risk/latest) and P3-T7 (POST /api/v2/market-risk/ack)
```

**Why here.** The RCA showed the operator's first market-relevant message on 2026-10-30 was the stop-fill page. Home is the
page opened most, on a phone; the engine's tier must be the first thing seen, and a Red must be impossible to miss or lose.
The Risk page is where the detail belongs, replacing a Regime tab that showed a label the RCA found meaningless.

**What the operator sees.** Quiet day: a small MARKET RISK fact in the Home header ("GREEN 18 · breadth broadening") — no
banner. Yellow: the fact turns amber with the top reason. Orange or Red: a full-width banner above the header with the tier,
score, the five contributors with points, the "your book" line (budget breaches, positions by symbol and stop distance only),
the de-escalation sentence, and one button, **Acknowledge**, which records the ack in the operator-decisions ledger and stops
the repeats; the banner stays, muted, until the tier drops. Nothing on Home sizes, orders or sets a stop.

**Removals, renames, moves (design/README.md rule 4).** Home header fact "Market" → renamed "MARKET RISK" (same slot; the
old content — regime word, VIX, lagging sectors — moves into the "Market in one look" card). Classic Home (`?view=classic`,
kept one release) hero tile "REGIME" → "MARKET RISK". Risk tab "Regime" → renamed "Market risk"; the W7RiskRegime panel is
kept as the last block inside it. Nothing is hidden or deleted.

**Tokens.** One new token, `--risk-orange-color/-bg/-border` (tone `elevated`), is required: the app has success, warning,
danger and info only, and Orange must differ from Yellow in lightness as well as hue. Blue = info, Yellow = warning, Red =
danger, Green = success.
