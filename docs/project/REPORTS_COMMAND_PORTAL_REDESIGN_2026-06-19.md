# Reports Command Portal — Redesign (2026-06-19)

Status:      HISTORICAL
as_of:       2026-06-19T19:00:48-04:00
Measured at: efcc51365 / not measured

Redesign of `/v3/reports` from a single-column report *reader* into an operator **Reports Command
Portal**: visual summaries, deterministic action extraction, advanced search/filter/quick-views, and a
split-pane (list + reader + metadata) layout — while preserving the existing fully-readable report bodies
and the purge path.

## Current state (before)

- `scripts/reports_portal.py` — data layer. Normalizes four stores (`notification_log`, `alert_events`,
  `telegram_outbox`, `ai_reports`) into one item shape, grouped into ~17 portal categories. Read + purge
  only. Functions: `categories()`, `list_items()`, `get_item()`, `purge()`.
- `apps/command-center-v3/src/pages/ReportsHub.tsx` — single centered column (max 980px): category
  chips → search/date bar → a vertical feed of fully-rendered "article" cards (Telegram/markdown → React
  via `inline()`/`Article()`), pagination, and a `PurgeModal` (preview-before-delete). Useful but
  "dump-like" — it shows reports but does not surface *what needs action*.

## Current endpoints (unchanged, must not break)

- `GET /api/v2/reports/categories` — tabs with counts + last-activity.
- `GET /api/v2/reports/list?category=&q=&page=&per_page=&days=` — paginated, searchable items.
- `GET /api/v2/reports/item?source=nl|ae|ob|ar&id=` — single report detail.
- `POST /api/v2/reports/purge` — dry-run/preview + apply delete (retention).

Routing: `scripts/api_v2.py` — handlers `_reports_categories/_reports_list/_reports_item` registered in
the `ROUTES` dict (~line 18914); purge handled in the POST block (~line 19416). `ROUTES` handlers receive
`query` if they accept ≥1 arg and the return is auto-wrapped in `{ok, data}`.

## New API additions

- `GET /api/v2/reports/portal-summary?days=7` — KPI roll-up: totals; counts by category, severity,
  source, and action_class; top mentioned symbols; recent items; and the headline counters
  (critical/urgent, open actions, risk/stop, approvals, system/Hermes).
- `GET /api/v2/reports/action-items?category=&q=&days=7&limit=100&classes=&severity=` — flattened,
  deterministically extracted action items across categories, each routed to a real v3 page. Optional
  server-side `classes` (comma-separated action_class names) and `severity` (comma-separated) filters so a
  quick view stays **exact at any day range** — a class-based view passes its filter to the server instead
  of relying on a client-side pass over a severity-capped fetch (e.g. 90d Approvals returns all 52, not a
  crowded-out subset).

Both are pure read-only aggregations over the existing normalized rows. **No LLMs** — deterministic
regex/rule classification only.

### Action classes

`risk_review · approval_needed · stop_triggered · unprotected_position · research_needed ·
system_health · cron_or_backup · portfolio_review · broker_manual · llm_review · hermes_review ·
informational`

### Action → route map (real v3 routes only)

| class | route | label |
|---|---|---|
| risk_review / stop_triggered / unprotected_position | `/v3/risk` | Risk |
| approval_needed / broker_manual | `/v3/trading` | Trading |
| portfolio_review | `/v3/portfolio` | Portfolio |
| research_needed | `/v3/intelligence` | Intelligence |
| hermes_review | `/v3/hermes` | Hermes |
| system_health / cron_or_backup / llm_review | `/v3/system` | System |
| informational | report's own v3 link if present, else `/v3/reports` | Reports |

A report's own embedded `/v3/...` link (via the existing `_action_links`) takes precedence over the
class default route.

### Phase 3 — list item enrichment (cheap, per-page only)

Each item from `list_items` also carries: `action_count`, `action_classes[]`, `symbols[]`,
`has_actions`, `route_count` — computed by running the same extractor on the paginated slice (≤ per_page
items), so list cards can show "2 actions · Risk · PFLT/LHX" without a second request.

## New UI layout

Header: **Reports Command Portal** — "operator reports, actions, briefings, alerts, and advisories".

- **Top KPI grid**: Total 7d · Critical/Urgent · Open actions · Risk/Stop · Approvals · System/Hermes.
- **Quick views** (client-side where possible): Today · Needs Action · Risk/Stops · Approvals · Hermes ·
  System · Critical.
- **Category chips**: compact, horizontally scrollable.
- **Three-pane body**:
  - left ~34%: search + filters + report list cards (with enrichment badges) + pagination.
  - center ~44%: selected report reader (full `Article` rendering preserved) + section markers +
    read-full/collapse + action links.
  - right ~22%: Action Queue (from `/action-items`) + Top symbols + Severity/Category bars (inline
    `MiniBarChart`, no external chart lib).
- Stacks vertically on narrow screens.
- Purge demoted to a quiet "Retention / purge old reports" control (same modal, preview-before-delete).

New components (in `ReportsHub.tsx`): `ReportsCommandSummary`, `ReportsQuickViews`, `ReportsActionQueue`,
`ReportsVisualSummary`, `ReportsFilterBar`, `ReportsListPane`, `ReportReaderPane`, `ReportMetadataRail`,
`MiniBarChart`, `SeverityBadge`, `ActionPill`. Existing `Article`, `inline`, `pageLink`, `PurgeModal`
retained unchanged.

## Safety guarantees

- Advisory / read-only. No broker actions, no order/execution paths created.
- No deletes except the existing purge modal path (unchanged).
- No `.env`, secrets, holdings, broker execution, live-trading, or gate code touched.
- Existing `categories/list/item/purge` endpoints and full readable report rendering preserved.
- Classification is deterministic regex — no LLM calls, no metered APIs.

## Acceptance tests

- `GET /api/v2/reports/categories` still returns tabs+counts.
- `GET /api/v2/reports/portal-summary?days=7` returns KPI roll-up with the headline counters.
- `GET /api/v2/reports/action-items?days=7&limit=20` returns routed actions, each with a real v3 route.
- `GET /api/v2/reports/list?...` still paginates and now carries enrichment fields.
- Frontend build (`tsc && vite build`) passes.

## Screenshot / browser verification notes

Open `https://ms01-openclaw.tail163d14.ts.net/v3/reports` (hard refresh for the new bundle). Verify: KPI
cards render; Action Queue populates; quick views filter; category chips work; search works; a Morning
Brief renders as a readable article in the reader pane; action links route to real v3 pages; purge modal
still previews before delete; no horizontal overflow.
