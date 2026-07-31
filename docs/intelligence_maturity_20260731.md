# Intelligence Hub — Maturity, Overlap & Actionability Audit (2026-07-31)

Supersedes `docs/intelligence_maturity_20260622.md` for anything about the Intelligence hub. That audit
graded every sub-tab A/A- on **data completeness + UI polish**. This audit uses a different, harder
rubric the operator asked for directly: *is curation deterministic or LLM-assisted, is every card
actionable, is data duplicated across hubs, and does the system show what it's actually learning* — not
just whether a feed has data flowing into it.

## TL;DR

- **7 sub-tabs → 5** (`Command Center`, `Inferences`, `News`, `Topics`, `Ops`, plus a new `Learning` tab —
  net add of one after collapsing four). `Signal Quality` was the same items feed as `Command Center`
  re-lensed with two decorative (non-clickable) charts — folded in as a KPI + inline avg-quality readout.
  `Sources` + `Workflow` were both pipeline-plumbing views with no independent decision content — merged
  into one `Ops` tab (workflow diagram now collapsed-by-default, since it's diagnostic, not daily-use).
- **Curation was, and remains, mostly deterministic math** (`baseQscore` in `CentralIntelligencePages.tsx`:
  confidence − freshness/source/model penalties). The one place an LLM was already in the loop (the
  per-card "Ask LM to verify" → Grok+ChatGPT+local-gemma ensemble) only *displayed* a verdict behind a
  click — it never fed back into ranking or the badge shown on collapsed cards. **Fixed**: a bulk read of
  already-computed ensemble verdicts (`GET /api/v2/inference/ensemble`) is now joined onto every card by a
  **stable, content-derived id** (previously a positional index — see bug below) and applied as a bounded
  (±12pt) adjustment to the quality score, with a visible "ensemble consensus BLOCK" reason and a KPI
  ("Ensemble BLOCK") in the Command Center header. No new LLM calls are made on the render path — this
  only surfaces verdicts an operator already requested.
- **Fixed 3 real link/UX bugs**: (1) News articles' `source_url` was fetched but never rendered — added an
  "Open source →" link; (2) action buttons on `SynthesizedReportCard` with no `url` and no `onAction`
  handler rendered as dead no-op buttons — now hidden; (3) same-app action links (`/v3/risk`, `/v3/rotation`,
  etc.) were plain `<a href>` tags, causing a full-page SPA reload on every click — now client-side
  `navigate()`, and true external links open in a new tab instead of hijacking the app.
- **Found and fixed a latent id-stability bug**: intelligence cards' ids were `${source}-${index}}` — a
  position in that poll's array, not a property of the signal. A persisted "Ask LM" verdict for the risk
  item that happened to be at position 0 last poll could silently reappear on an *unrelated* item that
  lands at position 0 next poll (once the ensemble join above went live, this stopped being a
  cosmetic-only bug). Ids are now a content hash (`type|source|symbol|title`) — stable across polls/reorders.
  Also removed the now-orphaned `IntelligenceRotationTab.tsx` (dead code, not imported anywhere).
- **Central-source duplication was already mostly solved architecturally**: cards drill into
  `DetailDrawer.tsx`, which is the one place analyst consensus, Fibonacci/Finviz charts, insider Form-4,
  and holdings-LLM evidence render — cards themselves only show severity/quality/ensemble chips, not
  re-rendered fundamentals. Nothing needed to change here; documented so it isn't re-litigated.
- **New `Learning` tab** answers "how autonomous are we and what is the system learning" from data that
  already existed but was buried on `/hermes` (`maturity-dashboard`, `learning-scorecard`) and `/rec-intel`
  (`summary`) — no new data source. Includes gate-by-dimension pass counts, outcome hit-rate / false
  positive-negative rates, and which recommendation *sources* actually get executed (a source with many
  ideas and near-zero execution is itself a learning signal). `HermesHub` gained one small fix to make this
  tab's deep-links actually work: it had no `?tab=` URL support at all, so `/hermes?tab=maturity` always
  silently landed on the default "Briefs" tab — added the same query-param pattern `IntelligenceHub`
  already used.

## Methodology

1. Read every sub-tab's frontend component and its backend route in `scripts/api_v2.py` /
   `scripts/inference_api.py`.
2. Hit every live endpoint against the running server (`localhost:7777`, real Schwab-backed data, ~$1.25M
   book) to check freshness, real vs. stub content, and response shape assumptions in the frontend.
3. Traced every `<a href>`, `<Link>`, `onDrill(...)`, and action button to its target and confirmed it
   resolves to a real route/URL (a full browser click-through wasn't possible in this environment — the
   sandbox's inotify watcher limit blocks `vite dev`; verification is via `tsc --noEmit` + `vite build`
   production bundling, which both pass clean, plus manual trace of every link target against `App.tsx`'s
   route table).
4. Built an overlap matrix against every other hub that shows ticker/news/research content.

## Per-tab scoring (1–10, actionability-weighted)

| Tab (post-consolidation) | Curation | Actionable | Duplication | Score | Notes |
|---|---|---|---|---|---|
| **Command Center** | Deterministic + LLM-ensemble-assisted (new) | High — Act now/Monitor split, click-to-filter KPIs, verification plan on weak cards | None — drills to `DetailDrawer` | **8/10** | Was 6/10 (deterministic-only, decorative Quality-mode charts, positional ids). Real remaining gap: `baseQscore` weights are hand-tuned constants, not learned from `outcome_hit_rate`/`false_positive_rate` in the new Learning tab — see Recommendations. |
| **Inferences** | Deterministic confidence + live per-item ensemble | High — every card has a real one-click action (`ACTION_FOR` map to a real v3 route) | None | **8/10** | Already solid; stable ids (DB primary key) so its ensemble wiring was never affected by the bug above. |
| **News** | None (raw feed + a relevance score) | Medium — was low (no way to read the actual article); now has an outbound link | None — this *is* the canonical article corpus other tabs should link to, not duplicate | **6/10** | Filtering/pagination is solid; still no read/dismiss/promote-to-watchlist action, so it's a reading room, not a queue. |
| **Topics** (was "Research") | None — raw LLM narrative, ungrounded | Medium — gaps have a real "assign research" action; auto-research briefs are read-only | Genuinely distinct from Research Intel desk (topic registry / auto-research LLM briefs vs. curated article staging) — was previously unlabeled, easy to assume it duplicated RI | **5/10** | Added an explicit "not the article desk, here's the link" banner and a caveat that auto-research figures aren't cross-checked against holdings — this is real fabrication risk (LLM free-text financial claims), not fixed at the source. |
| **Ops** (was Sources + Workflow) | N/A — pipeline telemetry, not intelligence content | Low by design — it's a health/diagnostic surface, not a decision queue | None | **6/10** (was two separate 6-7/10 tabs) | Correctly minimized: workflow diagram now collapsed by default since nobody needs the ingestion DAG daily. |
| **Learning** (new) | N/A — read-only rollup of existing gate/scorecard math | High — every number is either a pass/fail gate or a rate that should trigger a review | None — reads `/api/v2/hermes/*` and `/api/v2/rec-intel/summary`, doesn't recompute anything | **7/10** | New; capped below 8 because it's read-only observability with no drill-to-remediation flow yet (e.g. clicking a failing gate should jump into the specific Hermes/agent-runtime surface that owns the fix, not just show the raw gate JSON). |

Dropped from the visible tab bar (content preserved, not deleted):
- **Signal Quality** — folded into Command Center (avg-quality readout + High error-rate/Ensemble BLOCK
  KPIs replace the separate page; the two `recharts` pie/bar charts were pure decoration — clicking them
  did nothing — and were removed rather than ported, per the "cut what isn't actionable" instruction).
- **Sources**, **Workflow** — merged into **Ops** (see above).
- **Rotation** slug already redirected to `/v3/rotation` before this audit (unchanged, still correct).

## Curation: deterministic vs. LLM — what actually happens now

`baseQscore(item)` (`CentralIntelligencePages.tsx`) is pure arithmetic: structural facts (risk/stop/open-trade/setup)
are scored on data completeness and staleness only; everything else gets confidence minus freshness/source/model
penalties. This is intentional and correct for facts (a stop-breach doesn't need an LLM opinion to be true) but
it means "quality" for opinion-type signals (news mentions, research gaps, external-LM reports) was **never**
actually checked by a second opinion — it just measured "does this look complete," not "is this right."

The multi-LLM ensemble (Grok + ChatGPT OAuth + local gemma, `scripts/inference_ensemble.py`,
`inference_ensemble_jobs`/`inference_ensemble_results` tables) already existed and was already wired to a
manual "Ask LM to verify" button per weak card — but the verdict only rendered in that one card's footer
and was thrown away for ranking purposes. It's now:

1. Bulk-read once per poll (`GET /api/v2/inference/ensemble?limit=200`, filtered client-side to
   `target_type=signal`) — no additional LLM calls, this is a read of jobs the operator already ran.
2. Joined onto matching cards by the new stable id.
3. Applied as a bounded, visible delta to `qscore` (consensus BLOCK: −12pts; consensus APPROVE ≥8/10:
   +12pts; ≥6/10: +5pts) — bounded so one ensemble call can't fully override the deterministic base.
4. Surfaced as an `ensemble` chip on the card (via `SynthesizedReportCard`'s existing chip row) even when
   the card isn't currently "weak," and as a reason string in the verification plan
   (`ensemble consensus BLOCK (grok+chatgpt+local, 3.1/10)`).
5. Rolled up as a new "Ensemble BLOCK" KPI in the Command Center header.

This is the honest answer to "is curation deterministic or does it need LLM help": it was 100% deterministic;
it is now deterministic-by-default with LLM override where the operator has actually asked for a second
opinion. It is **not** "every card gets an LLM opinion automatically" — that would mean an LLM call per
poll per card, which nothing in this codebase currently rate-limits or budgets for, and was explicitly out
of scope (no new cost/latency on the render path).

## Overlap matrix (Intelligence vs. other hubs)

| Content | Intelligence hub | Also lives on | Verdict |
|---|---|---|---|
| Per-ticker analyst/technical/insider data | Never rendered directly — only via `DetailDrawer` drill | Portfolio, Watchlist, Rec Intelligence detail views (same `DetailDrawer`) | **No duplication** — single shared surface, confirmed by reading `DetailDrawer.tsx` in full. |
| News articles | `News` tab (raw feed) | Research Intel desk (curated/staged subset), Reports "brief" | `News` is the fire-hose; RI is the curated subset. Kept both, but... |
| Article/topic administration | `Topics` tab (auto-research briefs, topic monitor, gaps) | Research Intel desk (`/research-intelligence`) | These were easy to conflate. Added an explicit banner distinguishing "topic registry" from "article desk" rather than merging (merging would have meant moving CRUD for topic monitor into RI, out of scope and higher-risk than a label fix). |
| Hermes pipeline health | `Ops` tab (RAG coverage, ingestion sources, unified library) | `HermesHub` "Pipeline Ops"/"Provenance"/"Pipeline" tabs (deeper, Hermes-specific) | Intelligence's `Ops` is a summary dashboard; Hermes's tabs are the operational drill-down (queue replay, provenance audit). Not duplicated content, different depth — left as-is. |
| Maturity/learning metrics | `Learning` tab (new) | `HermesHub` "Maturity"/"Closed Loop" (full detail) | Intelligence's `Learning` is the rollup; Hermes owns the detail. Deep-linked, not duplicated. |
| Rotation ideas | Folded into Command Center feed (`rotation/summary` → a handful of `setup`-type cards) | Rotation hub (full desk) | Intelligence only shows the top ideas as action cards; full mechanics stay on Rotation. Correct split. |
| Sizing/risk-adjusted recommendations | `Inferences` tab (table) | Portfolio, Risk hub | Read-only advisory table, links out; not duplicated. |

**Central per-ticker source of truth**: `DetailDrawer.tsx` (analyst consensus via `AnalystReviews`, Fibonacci
charts via `FibChartsInline`, Finviz technicals/fundamentals via `FinvizEnrichmentPanel`, insider Form-4 via
`InsiderActivity`, holdings-LLM evidence via `EvidenceBlock`). Every intelligence card that has a symbol
already drills here through `onDrill(...)`. This existed before this audit; it's the reason the "don't
repeat ticker data" instruction was largely already satisfied — the finding is documentation, not a fix.

## Link audit findings

| Issue | Where | Fix |
|---|---|---|
| `source_url` fetched, never rendered | `IntelligenceNewsTab.tsx` | Render as "Open source →", opens in new tab, `stopPropagation` so it doesn't also trigger the row's drill |
| Dead no-op action buttons (no `url`, no `onAction` wired) | `SynthesizedReportCard.tsx` (shared by Reports/Inferences/Intelligence) | Hidden instead of rendered as a clickable-looking button that does nothing |
| Same-app action links caused full-page reload | `SynthesizedReportCard.tsx` action row (`/v3/risk`, `/v3/rotation`, etc. used by `InferenceLayersPanel`'s `ACTION_FOR` map) | Client-side `navigate()` via `react-router-dom`'s `useNavigate`; true external links now open in a new tab (`target="_blank"`) instead of navigating away from the app in-place |
| Orphaned component, not imported anywhere | `IntelligenceRotationTab.tsx` | Deleted |
| Deep-link to a tab that doesn't support `?tab=` | New `Learning` tab's links to `/hermes?tab=maturity` / `?tab=closed-loop` | Added the missing `?tab=` support to `HermesHub.tsx` (same pattern `IntelligenceHub` already used) so the links this audit is *adding* don't ship broken |
| Latent id-instability (would have silently misattributed ensemble verdicts) | `CentralIntelligencePages.tsx` item ids | Changed from positional index to content hash |
| Legacy bookmarks to retired tab slugs (`?tab=quality`, `?tab=sources`, `?tab=workflow`) | `IntelligenceHub.tsx` | Added `LEGACY_SLUG` redirect map so old links land on the tab that now owns that content, instead of silently falling back to the default tab with no indication anything moved |

No endpoint returned a 404/500 during this audit; the "links don't work" complaint traced to the issues above
(mainly: a real link that existed but wasn't rendered, dead buttons that looked clickable, and full-page
reloads that *felt* broken even though they technically worked).

## What's genuinely NOT fixed (be honest about scope)

- **Auto-research briefs are still ungrounded LLM narrative.** A caveat banner was added, but the underlying
  fix (cross-checking specific figures the LLM states against live holdings/market data before display)
  is a backend grounding pipeline change, not a frontend link/IA fix, and was out of scope for this pass.
- **`baseQscore` weights are still hand-tuned constants**, not fit against the `Learning` tab's own
  `outcome_hit_rate` / `false_positive_rate`. The infrastructure to close that loop now exists in one place
  (Learning tab reads the same scorecard); actually wiring scorecard-derived weights back into
  `CentralIntelligencePages.tsx`'s scoring constants is a follow-up, not done here.
- **No browser click-through was performed** — this sandbox's `vite dev` fails on `ENOSPC` (inotify watcher
  limit), a host constraint unrelated to this change. Verification is `tsc --noEmit` (clean) +
  `npx vite build` (clean production bundle) + manual trace of every route/action target against
  `App.tsx`. Recommend a manual click-through on a host without the watcher limit before considering this
  fully closed.
- **Pre-existing, unrelated build-guard failures**: `npm run build`'s design-token guard also fails on
  `components/TradeAIPanel.tsx` and `components/AgentSoulEditor.tsx` (6 violations vs. baseline 5 each).
  Confirmed via `git status`/`git log` these were not touched by this change and predate it (last touched
  by an unrelated `agent-runtime` commit). All files actually touched by this audit pass the guard at or
  under their baseline.

## Files changed

- `apps/command-center-v3/src/pages/IntelligenceHub.tsx` — 7→5 tabs, legacy slug redirects, updated subtitle copy
- `apps/command-center-v3/src/components/CentralIntelligencePages.tsx` — merged Quality mode into Command, stable content-hash ids, bulk ensemble join + bounded score adjustment, removed decorative charts
- `apps/command-center-v3/src/components/SynthesizedReportCard.tsx` — client-side nav for same-app action links, hide dead no-op buttons, external links open in new tab
- `apps/command-center-v3/src/components/intelligence/IntelligenceNewsTab.tsx` — render `source_url`
- `apps/command-center-v3/src/components/intelligence/IntelligenceResearchTab.tsx` — RI-desk banner, ungrounded-LLM caveat
- `apps/command-center-v3/src/components/intelligence/IntelligenceOpsTab.tsx` — **new**, merges Sources + collapsed Workflow
- `apps/command-center-v3/src/components/intelligence/IntelligenceLearningTab.tsx` — **new**, Learning & Autonomy view
- `apps/command-center-v3/src/components/intelligence/IntelligenceRotationTab.tsx` — deleted (orphaned)
- `apps/command-center-v3/src/pages/HermesHub.tsx` — added `?tab=` deep-link support

## Recommendations (not done, next steps)

1. Ground auto-research brief figures against live holdings/market data before display, or clearly mark
   which sentences are numeric claims vs. narrative color.
2. Feed `Learning` tab's `outcome_hit_rate`/`false_positive_rate` back into `baseQscore`'s penalty constants
   on a scheduled basis (e.g. monthly recalibration job), closing the loop the tab currently only observes.
3. Give the `Learning` tab's failing-gate cards a real remediation drill (link straight to the Hermes
   surface that owns that specific gate) instead of a raw JSON dump in `DetailDrawer`.
4. Run an actual browser click-through once off this sandbox's inotify limit, to catch anything a static
   trace can't (hover states, timing-dependent renders, etc).
