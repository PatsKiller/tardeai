# Watch Desk v4 — Terminal Grade (2026-07-16, evening)

Status:      ACTIVE
as_of:       2026-07-16T17:34:46-04:00
Measured at: efcc51365 / not measured

Builds on v2 (7d72bdb, e155dbe) + v3 (19434adc). Commits `65d79b18..c776a8a4`
(`watch-v4:` prefix, one per WS). All five tabs on one design system; every
functional gap from the v4 prompt closed or explicitly flagged. Advisory-only,
paper-only, promotion governed throughout.

## WS-A — Design system (ships alone, commit 65d79b18)

- **`lib/watchTokens.ts`** — THE single entry point: re-exports BB + chrome, adds
  semantic slots (link, extIntel brand tints, heldBadge, RAIL, focusRing), the locked
  type scale TYPE {10/11/12/14/18/24}, chip constructors, and the deprecation map for
  the whole v2/v3 ad-hoc palette (file header).
- **Zero-hex census: 93 → 0** across the six Watch pages (token file excepted).
  WatchlistHub's local palette constants now point AT tokens (one edit converted the page).
- **Type floor 10px: 0 sub-10 fontSizes** (was 8/9px pockets on four pages).
  `terminalHubChrome` raised 9→10 — deliberately affects ALL hubs for consistency.
- **One mono stack** — all `fontFamily: 'monospace'` → `BB.mono` + tabular-nums.
  borderRadius normalized to 2 (999 pills excepted, by construction).
- **Rails**: every row-like element carries the 3px verdict rail (watchpool rows by
  promotion state, directive rows by status, finds rows by α sign, sector cards by
  momentum, pullback cards by tier/conflict). Legend line lives in the Watch header.
- **Chip vocabulary** (`components/TerminalChip.tsx`): four classes distinct by
  construction — state pills (never clickable), metric chips (mono, hairline, click =
  drill), action chips (pill, amber, the only pressable-as-chips), count bubbles.
  `StatePills` enforces max-3 + "+N" overflow; `ChipLegend` popover linked from the header.
- **Keyboard (A5 debt paid)**: j/k row focus + Enter on Watchpool (drill) and
  Watchlist (expand ensemble), s = star, a = alert composer; amber focus ring token;
  focused card scrolls into view. **Flag:** `x` (hide) is not wired — watchlist rows
  have no hide endpoint (never built in v2/v3); noted, not faked.
- **Deliberately NOT unified:** Card v4 internals (locked, reference not target);
  the external-intel ✦Grok/✦ChatGPT glyph links (kept one muted brand tint each per
  the token file); the Add-Watch modal accent (hermes tint — it creates a directive,
  which is hermes-adjacent; revisit if it grates).

## WS-B — Watchlist (75006bbb)

- **Saved views**: named filter presets (all 14 filters + search), max 8, SERVER-side
  in a new `ui_prefs` key/value table (`GET /api/v2/ui/prefs/get` + POST
  `/api/v2/ui/prefs`) — localStorage exists in the app but doesn't travel
  desktop↔phone. Hit the GET-map-swallows-POST gotcha AGAIN → GET lives at `/get`.
- **Bulk actions**: row checkboxes → bar with Star-all / Alert-all (one condition+
  threshold applied to ≤25, one confirm). **Flag:** bulk Stage/Hide not delivered —
  no per-row watchlist endpoints for either verb exist server-side.
- **HELD pills** on rows via the same held context as pullback cards (B3).
- **Payload tail (B4)**: 1.03MB → **929KB**. Render census against the LOCKED card:
  dropped from list payload = dual_consensus_json (1.4KB/row), synthesis_conflicts_snip,
  trigger_source, origin_detail, provenance_reason, technical_summary,
  holdings_llm_summary — all rendered ONLY by the ToS-desk diligence view, which now
  requests `?full=1` (1.4MB). **<700KB is NOT reachable honestly**: the remaining top
  fields (hermes_score_components 81KB, narrative snips 44KB, setup_context 40KB) are
  genuinely rendered by Card v4. The prompt anticipated exactly this outcome.

## WS-C — Watchpool (4a9f6c44)

- **Directive drawer** (`GET /api/v2/watch/directives/detail?id=`): thesis/rationale,
  aliases from spec.aliases, 90d hit-timeline sparkline, α outcome ledger
  (watch_candidate_events by source_id — all 2,902 directive hits are linked), staged
  watchpool children, TTL countdown.
- **TTL enforced** (diagnosis: 267/358 active directives stored ttl_days, NOTHING
  enforced it): Sunday hygiene now expires past-TTL actives (status CHECK gained
  'expired'; resume un-expires; blast radius at ship time: 0 rows). Rows show
  "EXPIRES Nd" pills ≤14d.
- **In-UI tier-3 approvals**: `GET /api/v2/watch/directives/merge-plan` imports the
  dedup module's `plan([3])` (no subprocess, 6h cache) and renders the live Sunday
  plan — currently exactly the operator's pending **#420 + #612 → #244** — with
  one-tap Approve per family through the SAME governed `merge_into` action as the
  CLI/Telegram path.
- **Cap evidence chip**: "sweep cap 180 · pool 21d α n/a (n=0)" — honest n=0 because
  directive_hit emissions have no evaluated outcomes yet; fills as the reconciler runs.
  Display only, no auto-tuning.

## WS-D — Finds quality gate (78f4278c) — the −4.82% response

- **Converted-α breakdown (D1)**: header now splits all-emissions α −4.82% (n=385)
  vs **converted-to-proposal α −11.0% (n=4)** vs per-source. Verdict: the funnel-top
  number is ai_discovered noise as suspected, BUT the tiny converted sample is worse,
  not better — n=4 is too small to be damning, big enough to watch. 123 converted
  total, only 4 scored so far.
- **Emission gate (D2)** at the WATCH intake boundary (`config/watch_quality_gate.json`:
  n≥30 & rolling 21d α < −2%): `ai_discovered` is gated today; its rows carry
  `low_efficacy_source` and fold into a collapsed amber band (119/120 recent rows).
  Nothing blocked or deleted; the label lifts automatically on recovery (1h cache).
  Engine Room WS-4 hook: the backlog drain can read the same per-source table
  (note in `_watch_quality_gate` docstring).
- **Per-source drill (D3)**: source chips filter the emissions band; hover carries
  emitted/α/converted-α/n definitions.

## WS-E — Sectors (7a1a5863)

- **RS history**: new `sector_rs_daily` (rs_date, symbol, close, spy_close, rs) +
  `scripts/sector_rs_daily.py` nightly cron 17:20 wd; backfill from market_quotes
  daily-last-quote gave 253 rows (patchy pre-history — 19–45 sessions/ETF, XLRE has
  no quotes at all; disclosed as n= on hover, completes forward).
- Tab renders 20d/60d RS change + trend arrow + 30-session sparkline per sector.
- **Book overlay**: holdings look-through weights (holdings.json resolved_sectors —
  fund decomposition, so SCHG counts as tech) as "book N%" chips. The predicted
  honesty moment happened: **Technology 23.8% book + deteriorating RS and
  Industrials 13.1% both flag "overweight while RS deteriorates — review rotation
  candidates"** (amber, deterministic copy).
- **Rotation verdict (E3)**: NOT duplicates — Sectors = passive monitoring lens
  (RS history, book overlay, setups); RotationIntelligence = strategy engine (pairs,
  review amounts, advisor oversight, cloud-LLM on request). Cross-links added in both
  headers; no merge recommended.

## WS-F — Pullback + forward fix (c776a8a4)

- **Regime disclosure (F1)**: risk_off (same `/api/v2/risk-regime/latest` read as the
  tab strip) → amber rail note on TRIGGER cards + header statement. Disclosure only —
  suppression waits for outcome-ledger proof.
- **Score transparency (F2)**: score chip hover breaks the composite using the
  screener's OWN YAML constants served as `score_formula`
  (100 − (prox/0.6)×30 − |pull−20|×1.5 + trend). Render-only.
- **Journal threading (F3)**: `discovery_trace_id` now threads proposal→fill:
  pullback screener stamps `pbm-YYYYMMDD-SYM` at proposal creation (momentum fast
  path's slug convention); `trade_lineage.extract_lineage_from_proposal` passes it
  through; `paper_trade_logger` writes it to paper_trades. E2E-proven on live
  proposal #888 (soc- trace → extractor → exact confidence). Journal joins via
  journal_trade_reviews.paper_trade_id (existing).
  **Flagged for supervised patch (broker-adjacent, untouched):** the 33/121 fills
  written directly by `alpaca_paper_adapter.py` (9/26 lineage) and alpaca_sync (0/7)
  bypass the logger's lineage block; and proposal writers other than pullback/momentum
  (watchlist propose modal 1,751, screener 110) still create traceless proposals.

## Self-scored maturity (structure; evidence accrues with data)

| Tab | Score | One-line justification |
|---|---|---|
| Watchlist | 9 | Views/bulk/keyboard/held/payload done; bulk Stage/Hide blocked on missing endpoints (flagged) |
| Watchpool | 9.5 | Drawer, TTL, in-UI approvals, evidence chip — full lifecycle on one screen; α ledger still n=0 |
| Finds | 9.5 | Converted-α + gate + drill shipped; verdict authority arrives as converted-n grows |
| Sectors | 9 | RS history + book overlay live; sparklines honest-thin until the nightly accrues ~60 sessions |
| Pullback | 9.5 | Regime disclosure + score transparency + forward attribution; historical hop stays dead by design |

## Operator items (standing)

Key rotation + full-history gitleaks — repo cycled public/private FOUR times 07-16;
outranks everything. Schwab dated Cost Basis export ×4. Tier-3 merge — now one tap
on the Watchpool tab (WS-C3) or Telegram. Jul-30 Gain Guardian review.
Engine Room WS-1 topology: DONE earlier tonight (see ENGINE_ROOM_V1.md).
