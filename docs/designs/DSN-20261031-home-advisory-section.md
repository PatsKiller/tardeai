---
id: DSN-20261031-home-advisory-section
title: Home "Market advisory" section (shock type and heat-map strip, where leadership is moving, re-entry watch)
status: PROPOSED
approval: awaiting the operator's decision on the home v003 design (AGENTS.md §28.13; design/README.md rule 2)
source: 'operator 2026-10-31, verbatim: "It should also be in a section on the homepage, maybe not prominent up top, but somewhere"'
summary: >-
  One new collapsible card on Home, below "Market in one look" and above "System pulse", that gathers the Market Risk
  Engine's advisory outputs: the shock type with a small sector heat-map strip, the rotation advisor's leadership groups
  with candidates and horizon tags, and the re-entry watch for names the operator was stopped out of. Collapsed by default
  on phone, expanded on desktop. Advisory wording only; nothing is removed or moved.
phases:
- id: DSN-20261031-home-advisory-section-P1
  title: Home v003 — Market advisory card
  status: PROPOSED
  tasks:
  - {id: DSN-20261031-home-advisory-section-P1-T1, title: 'Build Home v003 (Design: home/v003) once APPROVED and its data sources are merged', status: PROPOSED, areas: [apps/command-center-v3/src/pages/HomeDoNow.tsx, apps/command-center-v3/src/lib/designTokens.ts]}
---

# Home "Market advisory" section

```
Status:      PROPOSED
as_of:       2026-10-31
Spec:        the home v003 SPEC.md under design/pages/<page>/versions/v003/
Mockups:     private store (sha256 in the v003 status.json); viewing copy is a private claude.ai artifact
Depends on:  PR #2388 (sectors, shock type, heat map), the rotation advisor and the re-entry watch (in flight)
```

**Why.** The operator asked that the leadership, re-entry and sector-shock intelligence be visible on Home, but not at the
top. Home stays led by money and risk (header, Do now, accounts, movers, opportunities, market in one look); the new card
sits after those so it never pushes the urgent items down on a phone.

**What it is not.** It never says buy or sell, never gives a size, price or stop, and never shows residual positions. It
renders "unknown" for anything not measured and degrades block by block.
