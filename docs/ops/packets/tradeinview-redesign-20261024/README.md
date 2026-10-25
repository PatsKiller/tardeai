# WP-22 TradeInView A source packet

Original task `DSN-20261024-tradeinview-data-P1-T1`; legitimate continuation
claim `20261024T233738Z-codex-3255d812` from root's released `a37f0929` claim.
Starting checkpoint `9031d4b775ff88581086f95883016f69e887171d` is WIP, not an
accepted release. This packet never installs a workflow, changes a schedule,
executes a provider/broker, repairs state, merges or releases.

[Field lineage and trust](../../TRADEINVIEW_REDESIGN_20261024.md) maps UI values
to API fields, stores, columns and writers. Real business measurements and
read-source completeness stay distinct. Missing values never become fabricated
zeroes, dates, fill confirmations or calibrated confidence scores.

The existing API module exports:

- `get_list(query)` / `get_detail(trade_id, query)` for Journey v1 plus receipt,
  reconciliation and registered-schedule fields.
- `get_calendar(query)` for explicit `month=YYYY-MM`, `account`, `names`.
- `get_history(query)` for `range=all` or explicit `start/end`, `symbol`, `sort`.
- `get_replay(query)` for exact `trade_id`, `interval=1D`, `stored_only=1`.

[The W3-owned central routing patch](api_v2-owner-integration.patch) is supplied
for normal source-owner integration. It was not applied by A; the batch-28
coordinator applied it unmodified (see the packet JSON status). The
stored-only branch must precede legacy `ohlc_charts` import/provider hierarchy.
The helpers' schema passes do not establish that the central HTTP route is
installed. Do not roll out B/C without the combined route patch.

Calendar paging keeps existing DTO fields while bounding material:

| Query / field | Meaning |
| --- | --- |
| `event_offset`, `event_limit` | Global events, default 0/50, limit 1–100 |
| `day=YYYY-MM-DD` | Expand only that selected day, within requested month |
| `day_event_offset`, `day_event_limit` | Selected-day event page, default 0/50 |
| `trade_offset`, `trade_limit` | Selected-day trade page, default 0/50 |
| `events_paging`, day `events_paging` / `trades_paging` | offset, limit, returned_count, known_total, total_count, next_offset |
| Day preview | At most three events / ten trades; independent server totals |
| `event_counts` | Observed count by kind, not independent full-source coverage |
| `total_count: null` | Missing/truncated/undated source prevents complete count |
| `gaps_paging` | Count and bounds for the first 100 findings |

The producer computes every financial statistic before paging. UI pagination
must display observed/complete distinctions, request selected-day pages and
never treat previews as the full population. Journey re-entry counters are
server `re_entry.condition_counts.met/total`; unavailable conditions yield null
with a reason, not 0/0. No UI recomputation is required.

The broad Calendar and History read snapshots each have one 60-second in-memory
cache entry. Paging shares that snapshot; original collection and record clocks
remain unchanged. Replay has no per-trade cache growth. Catalyst reads project
only consumed metadata rather than descriptions/raw payloads. No new durable
store/writer or actor is created.

Full schema proof uses existing system Python with the installed validator:

```bash
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -q tests/test_tradeinview_projections_20261024.py
```

The reproducible test-only dependency is `requirements-ci-tradeinview.txt`;
existing CI jobs install it. This worker never runs an installer. The canonical
virtualenv's earlier missing-jsonschema result remains recorded; no skip or
partial validator replaced the required full Draft 2020-12 check.

Optional private COPY proof (no live-state fallback): set
`TRADEINVIEW_PRODUCTION_COPY` to the original immutable input COPY, and
`TRADEINVIEW_EXPORT_DIR` to an owned scratch directory, then run
`tests/test_tradeinview_real_tree_20261024.py` with system Python and the same
psycopg2-hidden barrier. These variables identify fixture inputs and outputs;
no database, host schedule or live HTTP access occurs. Source SHA and per-query
copy coherence are preserved in receipts.

Private evidence root: `/home/johnclaw/.cache/rtc/codex-tradeinview-a-20261024/`.
`producer-exports/` contains schema-validated actual outputs and receipts. The
actual Replay/history and Replay/calendar variants share exact recorded trade
IDs. Its missing bars are a genuine capture gap. Positive bars/closes and fresh/
stale receipt examples must remain explicitly labelled synthetic producer
fixtures. No production observations are invented to make a screenshot green.

Remaining: source-owner routing integration, final B/C producer-fixture/mobile
integration, required actual PR checks, operator merge/release and authorized
served readback. Missing ingest success and incomplete historical transitions
remain evidence gaps; A does not instrument protected broker producers.
