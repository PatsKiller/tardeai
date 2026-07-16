# Engine Room v1 — Plumbing & Intake Hardening (2026-07-16)

Session scope from the research-intelligence-desk skill §6 (the original CC prompt file
was never saved to disk — flagged; executed from skill canon). Advisory-only,
paper-only; no broker writes, no gate/2FA/threshold edits. All four workstreams
shipped and verified same-day.

## WS-1 — Server topology (Path B, in-process)

**Root cause (verified this morning):** request threads keep computing and
serializing multi-MB payloads for clients that already disconnected (cache-busted
poll storms, dead Tailscale peers). The sockets sit in CLOSE-WAIT (~33/10min at the
storm peak) while their threads hold `DASHBOARD_MAX_CONCURRENCY` semaphore slots →
`server_busy` 503s for everyone else.

**Path A (gunicorn gthread on :7778, off-hours cutover) is INFEASIBLE** —
`portfolio_server.py` is a raw `http.server.BaseHTTPRequestHandler`, not a WSGI app.
Recorded so it isn't re-proposed.

**Path B (shipped, after 16:00 ET close):** in `scripts/portfolio_server.py`
- `_peer_closed()` — zero-timeout `select` + `MSG_PEEK` EOF probe. Gotcha discovered
  live: plain `recv(MSG_PEEK)` on a timeout-mode socket blocks in select for the full
  socket timeout — the first deploy hung every request for 30s; the `select([conn], [], [], 0)`
  guard is load-bearing, do not "simplify" it away.
- `do_GET` wrapper — aborted client detected **before** compute starts; the request
  costs ~0 instead of a full build+serialize.
- In-flight registry + `engine-room-compute-watchdog` daemon thread — every 5s, any
  request computing past `DASHBOARD_WATCHDOG_ABANDON_SEC` (default 25s) whose client
  is gone gets its socket shut down; the thread dies on next write and releases its
  slot. Never touches a connected client. POSTs are registered too (socket shutdown
  only breaks the response, never the DB work).

**Verification:** 15 aborted heavy polls (`/api/v2/research-intelligence`, 0.3s
client timeout) → `/api/health` 200 in 1ms during the storm, CLOSE-WAIT 0 after
(2 transient at +30s vs ~33 at the morning peak), feed 200 in 60ms.

**Payload audit (Phase 0):** top shell-polled endpoints — research-intelligence
1.97MB (ETag'd, 304s), **symbol-cards 1.95MB/1.04s with NO cache → now 5-min
in-process cache + content ETag; repeat poll = 304 in 14ms / 0B**, watchlist/items
1.12MB (D3-trimmed earlier), watch-directives 585KB, rest <150KB.

## WS-2 — Provenance at production

- `user_research_topics.sources_json` (new column): `auto_research.py` now persists
  the web sources it actually grounded on (`research_symbol_web(..., return_sources=True)`).
- Feed (`lib/research_intelligence.py`) reads persisted sources for the topics lane.
- **Sourceless advisory degrades to wire at write:** `enrich_narrative()` only
  synthesizes advisory framing (implications / ticker recs / sizing) for items with
  real `sources[]`; sourceless items get `provenance_grade: "wire"` and no advisory.
  This alone cleared all 11 `unsourced_advisory` lint flags.
- Per-figure as-of: synthesizer prompt now requires precise dating (source-article
  date or exact date), never "as of mid-2026".
- **Regeneration:** the remaining 10 flagged briefs (all `Industry: …`
  topic_research rows) re-synthesized in place via new
  `topic_research_synthesizer.py --ids 9817,…` targeted mode (grok lane, grounded on
  6–8 crawler articles each). **QA lint: 21 flagged this morning → 0.**

## WS-3 — Universe guard at generators

New `scripts/lib/universe_guard.py` (deterministic, zero LLM, never blocks a write):
every ticker-ish token and corporate-name mention in generated prose is resolved
against symbol_profiles ∪ watchlist; unknown entities are **disclosed in the brief**
("Entities named outside the tracked universe: … — verify identity before acting"),
confidence capped at 0.5, and the resolution stored in
`evidence_json["universe_guard"]`. Wired into `topic_research_synthesizer.py` and
`auto_research.py`. The QA lint treats guarded items as generator-resolved (no
double-flagging); unguarded legacy items still get the post-hoc check. Unit-verified:
real peers (ASML, Applied Materials) resolve, "Beauty Farm Medical"-class
fabrications are caught.

## WS-4 — Hermes intake loop

**The "2,510 backlog / 1,676 high-priority" story was 99% duplicate inflation:**
three identical topics × ~825 rows each, filed before the 2026-06-11 writer dedup
patch (which stopped new dupes but never collapsed the pile).

- **Duplicate collapse (reversible):** 2,480 rows → status `rejected` +
  tag `duplicate_collapsed` (earliest row per topic kept; promoted rows untouched).
  True backlog: **30 rows**, only 2 unresolved-and-drainable.
- **source_surface attribution:** 2,505/2,510 unknown → **0 unknown** (backfilled
  from finding_type/topic; writers — librarian loop, SIEM bridge — now attach
  `source_surface` at write; SIEM writer's no-op dedup replaced with a real
  14-day dedupe_key check + evidence meta).
- **Drain starvation fixed:** `hermes_backlog_drain.py` scanned only the 60 oldest
  archived rows, all already resolved → "No drainable backlog targets" while 2,400+
  waited. Resolved parents now carry a `drained` tag (81 backfilled), excluded in SQL.
- **Validator:** dry-run on live rows → 2/2 VALIDATED (missing-`summary` recovery
  path works); dry-run accounting no longer mislabels validated rows as failed.
- **Nightly drain installed:** cron 02:20 `--apply --max-rows 25 --max-runtime 3000
  --telegram-summary` (one backlog-status Telegram line, bypass_router). Coordinator's
  every-tick drain (N=2) unchanged. Backlog health check now excludes collapsed dupes.

## Operator items (standing)

- Anthropic key + DB password rotation still OVERDUE (git history exposure, 2026-07-04).
- Schwab dated Cost Basis export ×4; tier-3 directive merge approval in Telegram;
  Gain Guardian promote review ~2026-07-30.
