# Private-Company Proxy Graph

**Status:** Active (PR #127, branch `wt/private-proxy`, unmerged at time of writing) · **Advisory / research only**
**Added:** 2026-07-06 · **Extended to full-graph discovery:** 2026-07-07

Research **private** companies that cannot be bought directly, map them to the **full graph of public
proxies**, score and rank them, and surface paper/review-only equity + options strategy candidates.
Seed case: **Anthropic IPO → Zoom (ZM)** (Zoom Ventures holds a reported Anthropic stake) — but the
operator-named ticker is *not* the whole answer.

## Safety invariants (enforced)
- Advisory / research only. **No auto-promotion, no live order path, no candidate is `live_eligible`.**
- No Schwab / Fidelity / OCO / 2FA behavior is touched.
- Every accepted proxy carries **source citations**; unknown stake values are shown as **unknown**, never
  fabricated. Proxy theses are labeled **event-driven / UNVALIDATED** until paper outcomes exist.
- Options candidates default paper/review-only; **View Chain** is required before any paper or manual action.

## Components
| Layer | Path | Role |
|-------|------|------|
| Registry | `config/private_company_proxies.yaml` | Operator targets: `known_proxy_tickers` seed list to investigate, per-target `card_copy` (beginner summary / education / what-to-monitor), strategy scaffolding with `speculative` / `caps_upside` flags |
| Discovery | `scripts/hermes_private_proxy_research.py` | Web-grounded graph discovery + scoring + ranking + bucketing → `private_company_proxies` |
| Scanner | `scripts/proxy_options_scanner.py` | Ranks deep-ITM / call-debit-spread / CSP for the top-N optionable proxies → `proxy_option_candidates` (`live_eligible=false`, `status=review_only`) |
| API | `scripts/api_v2.py` | `GET /api/v2/proxy/targets`, `POST /api/v2/proxy/{research,scan}` |
| UI | `apps/command-center-v3/src/components/PrivateProxyCard.tsx` | Hermes hub **Proxy Cards** tab |

## Discovery pipeline (`hermes_private_proxy_research.py`)
1. **Target research** — 10 standing questions (IPO status/window/valuation, public investors, materiality,
   disclosure, catalysts) via the free Grok/ChatGPT OAuth lanes. `_llm()` retries across both lanes to
   ride out the proxies' transient 502s.
2. **Graph discovery** — the LLM enumerates every public proxy across the `proxy_type` taxonomy
   (`direct_equity_stake`, `convertible_note`, `preferred_stock`, `corporate_venture_investor`,
   `strategic_partner`, `cloud_provider`, `chip_supplier`, `customer`, `public_comparable`, `ETF`),
   each with evidence_summary, estimated stake (or null), catalyst_type, confidence / materiality /
   dilution / disclosure scores, why-not, and **citations** (a proxy with no source is rejected).
3. **Live enrichment** — market cap via `schwab_transport.get_fundamentals`; optionability
   (has_options / LEAPS / liquidity) via `strategy_research/options_chain.strategy_feasibility`. Degrades
   to `unknown` when the market/broker is closed; refreshed by the next market-hours run.
4. **Rank** — `direct exposure (weighted by confidence) > materiality-vs-market-cap > disclosure >
   catalyst proximity > stock liquidity > options liquidity > dilution-risk penalty`. A small-cap holder
   with a big stake (ZM) can outrank a mega-cap direct investor whose stake is a rounding error (AMZN).
5. **Bucket** — decision cards: best direct / best materiality / best options / best lower-risk equity /
   too-diluted-but-watch / rejected (with reasons).

## Data model
`private_company_proxies` — one row per (slug, proxy_ticker): proxy_type, bucket, rank_overall,
rank_score, accepted, rejected_reason, confidence/materiality/dilution/disclosure scores, market_cap,
estimated_stake_value, stake_to_mktcap_pct, catalyst_type, evidence_summary, optionability jsonb,
has_options/leaps_available, citations jsonb, ticker_plan jsonb (regular/options/watch/invalidation/
why_not), research_answers jsonb. Schema created idempotently by the script's `_ensure_table` (ALTERs).

`proxy_option_candidates` — scanned deep-ITM / debit-spread / CSP rows; `live_eligible=false` invariant.

## Anthropic graph — expected output
Not just ZM. A ranked table incl. **ZM** (highest-materiality CVC proxy), **AMZN / GOOGL** (largest/
cleanest strategic investors, diluted by size), **NVDA** (AI-infra beneficiary; not a clean ownership
proxy unless a stake is confirmed), plus **MSFT / CRM** only if current sources confirm direct Anthropic
economics — otherwise **rejected with reason**.

## Scheduling
Proposed cron (`crontab_private_proxy_proposal.txt`, **not installed** — operator action): daily
web-grounded research + market-hours option scans. Backup-first install command inside the file.

## Operational notes
- Live population needs a working OAuth web lane (Grok :8645 / ChatGPT :8646); both were 502-flapping on
  2026-07-07. When both are down, discovery fails cleanly (no partial writes) and retries via the cron.
- Related legacy lane: `scripts/lib/hermes_discovery/private_proxy.py` (corpus/regex auto-discovery feeding
  `HermesDiscoveryInbox`) is a **separate** subsystem from this operator-registry-driven graph.
