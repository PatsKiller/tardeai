# Command Center v3 — UI/UX Design Audit and Redesign Direction

```
Status:      ACTIVE
as_of:       2026-09-27 (America/New_York)
Measured at: main 0a9680a59 (dev tree); served release 0be1da1c8 (CURRENT) for screenshots
Method:      scripts/ui_audit_metrics.mjs (repeatable census, no dependencies) over
             apps/command-center-v3/src; a read-only survey of pages, tokens, primitives and
             gates; Playwright captures via apps/command-center-v3/e2e/ui-audit-screenshots.spec.ts.
             Numbers below are from docs/design/audit/ui_metrics_2026-09.{json,md}; re-run the
             script to refresh them. Nothing in the app was changed to produce this document.
Authority:   READ_ONLY_ADVISORY. No broker, order, stop or holdings path is touched by any
             recommendation here.
Plan:        PR0 (this document) → PR1 tokens → PR2 primitives → PR3 metric guide + insight API →
             PR4-PR9 pages → PR10 AGENTS 1.4.0 + docs/design/UI_STANDARDS.md. Rollback: runtime
             ui_v5 toggle → exact-SHA release rollback → git revert.
Supersedes:  docs/ui_redesign/REDESIGN_TARGETS.md and docs/ui_redesign/UI_REDESIGN_BACKLOG.md
             (both marked SUPERSEDED BY this document; open items absorbed in §12).
```

## 1. Executive summary

The Command Center shows a great deal of correct data and very little decision support. The
audit found no semantic colour system, no shared tooltip, no shared collapsible, no ticker
header, and card-level insight only on the options desk. Styling is almost entirely inline
(14,048 inline style objects against 348 class uses), with 3,269 raw hex colours outside the
token files, 1,394 fonts below the 10px floor the token file itself declares, 56 distinct
border radii and 29 distinct box shadows. Only 29.3% of metric-like elements carry any help
text. There is no light theme and no Settings page.

The redesign direction is the operator's: **insight first, data second**; a **ticker
intelligence header**; **collapsible information architecture**; a **semantic colour
framework** (green positive, red risk, yellow watch, blue informational, purple AI insight);
and a **universal tooltip system** (definition, why it matters, interpretation, benchmark)
on every metric. §13 of AGENTS.md still binds: insight text and tones are supplied by the
API; the frontend renders, it does not decide.

## 2. Repo-wide numbers (2026-09-27)

| Signal | Value | Target after the redesign |
|---|---|---|
| Files scanned (`src/{pages,components,lib,control-plane,hooks}`) | 444 | — |
| Raw hex outside token files | 3,269 | 0 (tokens.css + designTokens.ts only) |
| fontSize < 10px | 1,394 (9px: 995, 8px: 374, 7px: 25) | 0 |
| Inline style objects | 14,048 | falling; primitives carry the styling |
| className uses | 348 | rising |
| `var(--…)` uses | 6,536 | all semantic names |
| Distinct border-radius values | 56 | 3 (`--radius-sm\|md\|lg`) |
| Distinct box-shadow values | 29 | 3 (`--shadow-1\|2\|3`) |
| Native `<details>` | 43 | replaced by `Collapsible` where state must persist |
| `title=` attributes | 824 | replaced by `Tooltip`/`MetricGuide` on metrics |
| Metric-like elements | 188 | — |
| … carrying `guideKey`/`tip` | 55 (29.3%) | 100% on converted files, ≥ 95% repo-wide |
| Token files imported | watchTokens 63, terminalUi 36, terminalHubChrome 28, holdingsTerminalTokens 28, proposalDeskTheme 14, watchlistTerminalTokens 13, watchlistCardTokens 12, terminalCardTheme 4 | one (`designTokens.ts`; `watchTokens.ts` as facade until PR9) |
| Themes | dark only, two CSS-variable sets in `src/index.css` | dark + light via `[data-theme]` |

Radii in use (top): 6 (486), 8 (404), 10 (302), 4 (271), 2 (234), 5 (170), 3 (98), 7 (66), 12 (62), 999 (47), 50% (33), `var(--radius)` (13).

Worst files by raw hex: `components/HermesClosedLoopPanel.tsx` 205, `components/BrokerOrders.tsx` 150, `pages/JournalHub.tsx` 144, `pages/HermesHub.tsx` 129, `pages/RotationIntelligence.tsx` 125, `pages/SystemHub.tsx` 99, `pages/TradingHub.tsx` 93, `pages/PortfolioHub.tsx` 86, `components/HermesPanel.tsx` 78, `pages/HomeHub.tsx` 77.

Worst by inline styles: `HermesClosedLoopPanel` 426, `BacktestPanel` 331, `RotationIntelligence` 292, `CioHub` 285, `TradingHub` 285, `ResearchIntelligenceHub` 279, `HermesHub` 268, `RedeployDesk` 266, `SystemHub` 259, `StopManagement` 244.

## 3. Cross-cutting findings

### 3.1 Insight first, data second
Only the options cards open with a takeaway (`plain_english`, `committee_memo`, `cio_view` from
`scripts/lib/options_plain_english.py` and `options_economics.py`). Every other card and every
hub opens with a metric grid. There is no shared `InsightLine`/`TakeawayBanner`; where a verdict
exists it is `VerdictBanner` in `components/primitives/cardPrimitives.tsx`, used by four cards.
**Recommendation (PR2/PR3):** a server-supplied `insight` object on every card payload
(`scripts/lib/ui_insight.py`, reusing the options explainers and the existing server-side
verdict/materiality logic), rendered by `TakeawayBanner` as the first content of every card.

### 3.2 Ticker intelligence header
Three different headers exist: `WatchlistCardV4` (symbol + name), `SymbolIntelligencePage`
(local `Panel/Pill/Fact` helpers, 14 metrics, 0% help coverage), `cio/SymbolThesisCard` (no
name, no tooltips). None shows sector, industry, market cap or a sentiment score together.
**Recommendation (PR2/PR5):** one `TickerHeader` primitive fed by an `identity`/`status_chips`/
`sentiment` block added to the symbol-intelligence and watchlist payloads.

### 3.3 Collapsible information architecture
43 native `<details>` in 26 files plus ad-hoc `useState` toggles; nothing persists; the largest
pages (`CioHub` 2,110 lines, 13 tabs; `ResearchIntelligenceHub` 2,559; `RedeployDesk` 1,631)
render everything at once. **Recommendation (PR2):** `Collapsible` (with `persistKey` through
the existing `/api/v2/ui/prefs`), `Accordion`, `ShowMore`, `DetailDrawer`; every card has a
summary state (header + takeaway + ≤4 metrics + actions) and an expanded state.

### 3.4 Semantic colour framework
Colour is named by hue (`BB.green`, `BB.amber`, `WL.signal.red`) or by role (`RAIL`
favorable/attention/breach/neutral; verdict READY/WAIT/FIX/SKIP). There is no
success/warning/danger/info/ai vocabulary, so the same red means "risk", "error" and "down"
depending on the file, and AI-sourced content is coloured per vendor (`T.extIntel.hermes/gpt/grok`).
**Recommendation (PR1):** `src/styles/tokens.css` with `--success|warning|danger|info|ai|neutral-{color,bg,border}`,
both themes, WCAG 2.1 AA verified by `scripts/check_token_contrast.mjs`; `watchTokens.ts` becomes
a facade so existing imports keep working while files convert.

### 3.5 Universal tooltip system
Help exists only as native `title=` (824 uses) and options-only dictionaries
(`lib/optionsTooltips.ts`, `lib/optionsMetricTooltips.ts`, `lib/stopReviewTooltip.ts`) plus a
local `TIPS` in `OptionProposalCardV4`. `MetricChipTooltip.tsx` already has the right shape
(short / more / watch / warning with phases). Coverage: `OptionProposalCardV4` 0/35,
`SymbolIntelligencePage` 0/14, `SymbolJourneyPanel` 0/13, `PositionDecisionCard` 0/9,
`cio/CioBrainPanel` 0/8, `PrivateProxyCard` 0/8, `WatchlistIntelligenceBoard` 0/7; `OptionPositionCardV4`
11/11 and `OptionsTrendsPanel` 6/6 are the models. **Recommendation (PR3):** one versioned
`assets/ui_metric_guide.yaml` (label, short, definition, why it matters, interpretation,
benchmark, watch, warning) served at `GET /api/v2/ui/metric-guide`; a generated `MetricGuideKey`
type so a typo fails `tsc`; every `Metric` carries `guideKey`; a coverage gate.

### 3.6 Consistency
23 radii values in components alone (56 across src), 29 shadows, 32 font sizes, `Metric`
re-implemented at least ten times (`OptionProposalCardV4:334`, `OptionPositionCardV4:76`,
`DetailDrawer:89` at 9px, `cio/CioBrainPanel:49`, `RetirementHub:240`, …), three chip/pill
implementations (`TerminalChip`, `statePill/metricChip/actionChip` helpers, `TipChip`, local
`Pill`s). **Recommendation (PR2):** one `Metric`, one `Chip`, one `Tooltip`, one `Collapsible`;
domain wrappers (`StatusBadge status=`, `SeverityBadge severity=`, `StopKindPill`,
`ProAnalystPill`) stay as thin wrappers because the designer workflow validates their props.

### 3.7 Data presentation
recharts in 18 files with default legends, no shared sparkline, no inline trend indicator,
per-page sort code in PortfolioHub/TradingHub. **Recommendation (PR2/PR6/PR7):** `Sparkline`,
`TrendIndicator`, interactive `Legend`, `useSort`/`SortHeader`; chart palette from the
dataviz method (`--chart-1..6`, both themes).

## 4. Page-by-page findings

Each section: **Current issues** (with a number from §2 or a file:line), **Recommended
improvements** (change · priority · PR · effort), **Mockup notes** (summary and expanded
states; primitives; API fields). Before-screenshots: `apps/command-center-v3/e2e/screenshots/ui-audit/before/<slug>.png`
(PNGs are not committed; `manifest.json` is; CI syncs captures to Drive).

### 4.1 Options cards — `OptionProposalCardV4`, `BrokerProposalCardV4`, `PositionDecisionCardV4`, `OptionPositionCardV4`, `OptionsHub`
**Current issues.** `OptionProposalCardV4` is 1,613 lines with 184 inline styles, a local
`Metric` (L334), a local `TIPS` dictionary (L275) and **0 of 35 metric-like elements** carrying
help; `BrokerProposalCardV4` 1,526 lines / 202 inline styles / 18 sub-10px fonts;
`PositionDecisionCardV4` 994 lines / 150 inline styles / 0 of 9 metrics with help. The takeaway
(`plain_english`, `committee_memo`) exists in the payload but renders below the economics grid.
Severity was the edge score until #1300 (fixed: blocked cards are BLOCKED). Hedge cards showed
put-alone max loss until #1300 (fixed). Nine chip styles coexist on one card.
**Recommended improvements.**
| Change | Priority | PR | Effort |
|---|---|---|---|
| Split each card into `Summary` + `Details`; summary = `TickerHeader` + `TakeawayBanner` (from `plain_english`/`committee_memo`/`insight`) + 4 `Metric`s (credit basis, max loss, breakeven, POP) + actions | High | PR4 | L |
| Replace local `Metric`, `TIPS`, `HeroMetricChip` with the primitives; every metric gets a `guideKey` (35 → 35) | High | PR4 | M |
| `RiskFlagChips` and the nine chip styles → `Chip tone=` (danger/warning/info/ai) | High | PR4 | S |
| Economics, greeks, legs, ladder, novice panels → `Accordion` sections (persisted) | High | PR4 | M |
| Executable vs midpoint credit shown as one `Metric` with `trend`-style delta and a `MetricGuide` entry `options.credit_basis` | High | PR4 | S |
**Mockup notes.**
```
┌ DELL · Dell Technologies · Technology / Hardware · $190B · [WATCH] [AI ▸ MONITOR_ONLY] ──── sentiment 62 ┐
│ ▎ Sound thesis; timing and price not compelling — POP 58.7% under the 62 floor, spread 7%.  (rule · 21:22 ET) │
│  Credit 6.35 exec (mid 8.10) ⓘ   Max loss $1,365 ⓘ   Breakeven 513.65 ⓘ   POP 58.7% ⓘ                │
│  [Validate] [Approve]                                                                                  │
│ ▸ Economics  ▸ Legs & liquidity  ▸ Greeks  ▸ Lifecycle & research  ▸ Plain English                    │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
Primitives: `TickerHeader`, `TakeawayBanner`, `Metric size="hero"`, `Chip`, `Accordion`.
API: `insight` (PR3), `identity`/`sentiment` (PR3), existing `economics`, `spread_quote`, `cio_decision`.

### 4.2 `WatchlistCardV4` and WatchHub
**Current issues.** 699 lines on the separate `WL` palette (12 files use it); header shows
symbol + name but no sector/industry/market cap/sentiment; `WatchlistIntelligenceBoard` has 0/7
metrics with help, `WatchIntelligenceUnified` 0/5; card height couples the board layout.
**Recommended improvements.** `TickerHeader` (High, PR5, M); drop `WL` for tokens (High, PR5, M);
`Metric` + `guideKey` on the board and unified view (High, PR5, S); sparkline of score/price
history in the card summary (Med, PR5, S); saved-view chips as `Chip variant="outline"` (Low, PR5, S).
**Mockup notes.** Summary = header + takeaway + 4 metrics (verdict, R:R, α, freshness);
expanded = decision matrix, DD links, directives. Capture the board at the same viewport
before/after because of the height coupling.

### 4.3 `SymbolIntelligencePage`
**Current issues.** 674 lines; local `Panel`, `Pill`, `Fact` helpers; 14 metrics with 0% help;
per-source AI colouring (`T.extIntel`); everything rendered open.
**Recommended improvements.** `TickerHeader` at the top (High, PR5, S); `Fact` → `Metric guideKey`
(High, PR5, S); one `Collapsible` per intelligence source with `tone="ai"` and a source chip
(High, PR5, M); price/score `Sparkline` (Med, PR5, S).
API: `identity`, `status_chips`, `sentiment` on the symbol-intelligence payload (endpoint at the
page's `useApi` calls ~L102/L111; confirm at implementation).

### 4.4 HomeHub + `MetricStrip`
**Current issues.** `HomeHub` 800 lines, 77 raw hex, 24 sub-10px fonts; `MetricStrip` 636 lines
renders numbers with no trend and no help; tiles (`BookTreemap`, `MarketMoversBoard`,
`MajorNewsGrid`) have no takeaway; recharts default legends.
**Recommended improvements.** `MetricStrip` → `Metric size="sm"` with `spark` and `guideKey`,
keeping the literal `(t as any).asOfLabel || 'as_of'` that `scripts/test_metric_strip_labels.mjs`
greps (High, PR6, M); an `InsightLine` per tile from the API (High, PR6, M); interactive `Legend`
on the treemap and movers (Med, PR6, S).

### 4.5 CioHub
**Current issues.** 2,110 lines, 13 tabs, 285 inline styles; `cio/CioBrainPanel` 0/8 metrics
with help; `cio/SymbolThesisCard` has no name header and no tooltips; no takeaway at the top of
any tab.
**Recommended improvements.** Top `TakeawayBanner` from `cio_view` per tab (High, PR6, M);
`SymbolThesisCard` → `TickerHeader` + `Metric guideKey` (High, PR6, S); tab bodies split into
`Collapsible`s (Med, PR6, L); convert inline styles in the two largest tabs first (Med, PR6, L).

### 4.6 PortfolioHub (9 tabs) and TradingHub (11 tabs)
**Current issues.** `PortfolioHub` 984 lines / 86 hex; `TradingHub` 1,329 lines / 285 inline
styles / 55 sub-10px fonts / 12 metrics at 67% help; sorting and filtering written per tab;
`HoldingsCard` has 32 `title=` and no takeaway; `holdingsTerminalTokens.ts` is a fourth palette.
**Recommended improvements.** `useSort`/`SortHeader` on every table (High, PR7, M); `HoldingsCard`
takeaway per holding from the API (High, PR7, M); delete `holdingsTerminalTokens.ts` (Med, PR7, S);
Options tab already redesigned by PR4.

### 4.7 Settings surfaces
**Current issues.** No Settings page. Settings live in `SystemHub` Admin/LLM tabs (874 lines,
99 hex, 56 sub-10px), `ActiveTraderConfigTab` (817), control-plane identity/notifications, and
three modals (`ScreenerConfigModal`, `LlmRoutingModal`, `SecretsManager`).
**Recommended improvements.** New `/v3/settings` route and `pages/SettingsHub.tsx` as an
`Accordion` that moves those sections (High, PR8, M); SystemHub keeps a "Moved to Settings" link
for one release (Med, PR8, S); §17 operator-only guard UI unchanged.

### 4.8 RiskHub · JournalHub · AdvisoryDeskHub · RedeployDesk · RotationIntelligence · ReEntryPageV3 · ResearchIntelligenceHub · Hermes/Intelligence/Communications/Reports · Health/Consumption/System · control-plane
**Current issues.** The largest hex and sub-10px offenders are here (`HermesClosedLoopPanel` 205
hex / 87 sub-10px / 426 inline; `JournalHub` 144 / 65 / 224; `HermesHub` 129 / 61 / 268;
`RotationIntelligence` 125 / 53 / 292; `BrokerOrders` 150 / 62 / 221; `BacktestPanel` 53 / 331).
`RiskHub` has 20 sub-10px fonts. None has a takeaway or a metric guide.
**Recommended improvements.** Same card contract, converted in the order listed (Low, PR9a-c, L
split three ways); delete each legacy token facade when its last importer converts.

## 5. Pills, badges and chips
Three implementations plus per-card variants; sizes 8-11px; colour by hue. Target: one `Chip`
with `tone` (success/warning/danger/info/ai/neutral), `variant` (solid/outline/soft), `size`
(sm 10px / md 11px), optional icon and `guideKey`; radius `--radius-lg`; domain wrappers keep
their prop signatures. Every status chip is clickable where a drilldown exists (collaboration
feedback, memory).

## 6. Colour system and CSS tokens
`src/styles/tokens.css` (dark, light, `.cc-terminal-ui` skin) with `--success-color`,
`--warning-color`, `--danger-color`, `--info-color`, `--ai-color`, `--neutral-color` (+ `-bg`,
`-border`), `--primary-color`, `--secondary-color`, `--bg-0..3`, `--text-0..3`, `--space-1..8`,
`--radius-sm|md|lg`, `--shadow-1|2|3`, `--font-xs..xl` (10/11/12/14/18/24, locked), `--font-mono`,
`--chart-1..6`. Contrast: WCAG 2.1 AA (4.5:1 text, 3:1 large text and UI) in both themes,
enforced by `scripts/check_token_contrast.mjs`. `src/lib/designTokens.ts` mirrors the names for
TS and holds `CHART_HEX` for chart props that cannot take `var()`.

## 7. Tooltips and contextual help
`assets/ui_metric_guide.yaml` → `GET /api/v2/ui/metric-guide` → `Tooltip` + `MetricGuide`
(hover, focus, tap; `aria-describedby`; Escape closes). Migrates the three options dictionaries
and the local `TIPS`. Placeholders (`{spot}`) are substituted from payload values only.

## 8. Progressive disclosure
`Collapsible` (persisted per section through `ui_prefs`), `Accordion`, `ShowMore`, `DetailDrawer`.
Card contract: summary (header, takeaway, ≤4 metrics, actions) → collapsibles.

## 9. Actionability
Every card's first content is a server-supplied `insight` (`headline`, `tone`, `drivers[]`,
`source: rule|llm`, `as_of`, `provenance`). Peer comparisons ("revenue growth slowing vs
sector") are backend features with tests, never frontend arithmetic (§13).

## 10. Data presentation
`Sparkline`, `TrendIndicator` (`goodWhen`), interactive `Legend`, `useSort`/`SortHeader`;
comparative benchmarks come from the metric guide's `benchmark` field.

## 11. Consistency audit and gate
Value → occurrences → target token (radii: 6→`--radius-md`, 8/10/12→`--radius-lg`, 2/3/4→`--radius-sm`,
999/50%→pill; shadows → `--shadow-1..3`; fonts 7/8/9/9.5 → 10). Gate: `scripts/check_ui_standards.mjs`
with `config/ui_standards_baseline.json` (ratchet from PR1, binding in PR10; supersedes
`scripts/check_design_tokens.sh` per AGENTS §20).

## 12. Backlog reconciliation
`docs/ui_redesign/REDESIGN_TARGETS.md` and `docs/ui_redesign/UI_REDESIGN_BACKLOG.md` are marked
SUPERSEDED by this document. Their open items that survive: collaboration-page timestamps, stale
reasons and clickable status chips (absorbed into §5 and the PR9 contract); everything else was
either shipped in v4 or is replaced by the primitives above.

## 13. Change log
- 2026-09-27: created (PR0). Numbers from `ui_metrics_2026-09.json`.
