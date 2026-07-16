# Reports Desk v2 — Phase 0 Residual Diagnosis (2026-07-16 evening)

Repo at 59aa6118 (Watch Desk v4 SHIPPED between prompt-write and execution —
WS-E is import-only as hoped; `watchTokens.ts` + `TerminalChip.tsx` are the house system).

## ⚠ "psql auth blocker" — RESOLVED, password NOT rotated
Role `johnclaw` has NEVER existed in Postgres (role inventory pasted in session).
Every failing diagnosis ran `psql -U johnclaw`; the app and CLI both work as
`trade_ai` (creds from .env). Fixed durably: `~/.pgpass` (0600) installed →
bare `psql -h 127.0.0.1 -U trade_ai -d trade_ai` works with no env. Operator's
"was the DB password rotated?" → **No.** One rotation item OFF the list (the
GitHub token rotation is ON the list — repo went public a FIFTH time ~18:35 ET,
no local script touches visibility; GitHub-side actor, audit authorized apps).

## 0.1 Artifacts (data/portfolios/reports/)
143 portfolio_brief_*.docx + 140 portfolio_dashboard_*.html + 82 aegis_morning_brief_*.md
at root (morning/manual per day); weekly/ has {docx,html,json} triplets thru 2026-07-12;
monthly/ thru 2026-07-01; analyst/ registry + 439 report entries. Fresh 07-16 morning set
exists. `portfolio_live.html` = latest mirror. Timers visible system-level:
tradeai-continuous (04:00), tradeai-reprice; report cadences run via the
pipeline_cadence_controller (Phase 207–210) not separate timers.

## 0.3 Archive backing (reports_portal.py — hot-reloadable module)
Four corpora: notification_log 329 · **alert_events 23,505** · telegram_outbox 1,610 ·
ai_reports 26. `/api/v2/reports/{categories,list,search,item,portal-summary,action-items}`
all delegate to reports_portal. Alert volume runs ~2,000–2,600/day on weekdays —
plenty for WS-D rollups; weekend dips visible (80 on Sat 07-12).

## 0.4 `<b>` leak: confirmed — telegram_outbox.body stores raw Telegram HTML
(`<b>Pre-Market Brief…</b>`); fix in ONE formatter at render.

## 0.5 Morning brief structure: `fetch` from `/api/v2/aegis/chat-context` (:65) → 
`brief.get("sections",[])` used as DATA in both telegram (:214) and markdown (:387)
renderers; .md export at data/portfolios/reports/ + docs/ copy. → WS-B persists
`brief.json` sidecar next to the .md — purely additive, Telegram path untouched.

## 0.6 Analyst registry: data/portfolios/reports/analyst/registry.json
{version, updated_at, reports: [439]} — entry keys: id, symbol, report_type
(38 symbol_holding / 401 symbol_watchlist), title, recommendation, fingerprint,
generated_at, prior_report_at, generation, exports, oversight_verdict,
publication_blocked, block_reason, grok_edited, sector, topic.
CUSIP rows CONFIRMED in holdings.json: 12507E201 / 543354104 / 628518102, all $0,
empty descriptions → "Unmapped instruments" fold (no name feed available to map —
basis feed has no dated export; flag stands).

## 0.7 Vocabulary sites confirmed: reporting_engine.py:198 lumps
REVIEW/IGNORE/NONE/EXIT/AVOID/SELL as one non-actionable class; :327
`display_rec = latest or llm_rec or syn_rec or "WATCH"` — no held/candidate split.

## 0.8 alert_events: id/alert_uid/alert_type/symbol/severity/source_script/raw_text/
created_at/lifecycle_state/acknowledged_at (from portal reads) — rollup-ready.

## 0.9 watchTokens.ts EXISTS (Watch v4 WS-A shipped tonight) → WS-E import-only.

## 0.10 Hermes gap confirmed: generate_weekly_portfolio_review.py greps 0 for hermes;
morning bundle wired via morning_command_digest.append_section (orchestrator :25 import,
sections appended at :629/:1524/:1663 + fetch_hermes_movers). → WS-F: same
append_section pattern for weekly + monthly only.

## ReportsHub.tsx current data flow (491 lines, 3 modes)
brief mode: /api/v2/overview + /risk + /risk-regime/latest + /trade-ai +
reports/list?category=morning_briefs; archive mode: reports/list + portal-summary +
action-items + categories; analyst mode: its own endpoints. All on terminalHubChrome
(pre-v4 sizes) — WS-E sweep contained to this file.
