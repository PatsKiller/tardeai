# Conflict engine golden replay and producer gaps (d)–(g), 2026-10-25

Binding rules: `EXCEPTIONS_MATRIX.md` (handoff `conflict-resolution-20261024`, sha256 bound in
`config/conflict_rulebook.json`). Operator, 2026-10-25: "I need you to fix everything that's missing before deployment."

## What each gap closes

| Gap | Matrix rule | Code | Test |
|---|---|---|---|
| (d) decision anchor | R15: a resolution holds until a side changes ACTION or conviction moves ±5 | `scripts/lib/conflicts/hysteresis.py`; `ledger.transition` stores `decision.anchor`; `ledger.decision_inputs` carries it; `adapters.evaluate_inputs` hands it to the engine when no side changed action; the engine (`profiles/security.py`) compares conviction | `tests/test_conflict_r15_anchor_20261025.py` (incl. the matrix case "conviction 70±1 over 3 runs → one flag") |
| (e) producer freshness | R1: age = oldest material input; superseded after min(14 d, 2× cadence); refresh only to a producer that writes the compared input | `config/conflict_producer_registry.json`, `scripts/lib/conflicts/producer_registry.py` (applied in `adapters.evaluate_inputs`); re-entry desk materials quote + plan; `data_broker/entry_plan.py` now returns the plan's `created_at` | `tests/test_conflict_producer_registry_20261025.py`, `tests/test_conflict_entry_plan_time_20261025.py` |
| (f) golden replay | "golden replay of the live flags" | `scripts/conflict_golden_capture.py`; `tests/fixtures/conflicts/golden_20261025/{inputs,expected}.json` | `tests/test_conflict_golden_replay_20261025.py` |
| (g) read-only Watch source | AGENTS.md §23.3 / DD01 exception for the resolver | `scripts/lib/conflicts/watch_source.py` | `tests/test_conflict_watch_source_20261025.py` (closure + §23.3 scan) |

### R1 producer rows (config/conflict_producer_registry.json)

| Source the engine sees | Cadence | Supersede limit | inputs_as_of | Writes the compared input | Refresh lane |
|---|---|---|---|---|---|
| CIO record (canonical) | 1 trading day | R7b: 2 / 10 trading days | oldest weighted conviction component (`cio_truth._material_clock`) | yes | `cio-prospect-shadow` |
| watchlist CIO review | 3.5 d | 7 d | artifact `inputs_as_of` when written, else `completed_at` | yes | `watch-review-workers-cio` |
| watchlist_final_synthesis | 7 d | 14 d | not exposed (row `updated_at`) | **no**: every `process_watchlist_agent_jobs` lane is RETIRED | — |
| trade_ai (gate) | 7 d | gate, not superseded | packet `generated_at` | yes | `shadow-batch-generator-at-15-10` |
| reentry_decision_desk | materials | binding material | quote (§7A `quote_price` 0.25 h, session time) and plan (7 d), whichever is furthest past its own limit | **no**: computed on read; its materials have owners | — |

"Session time": a closed market does not age a quote taken at or after the last official close, so a Sunday
replay does not supersede Friday's closing quotes.

## (f) The capture

The 2026-10-24 capture of the 31 live flags was never saved (not in the repo, the fixtures or the handoff folder).
The fixture is today's real state instead, captured read-only at **2026-10-25T18:22:17Z** (Sunday):

| Input | How it was read | Notes |
|---|---|---|
| Watch cards (266 symbols) | `GET /api/v3/data-broker/watch-intelligence?view=all` and `view=expired`, pages of 100 | the served read model the resolver's `compose_universe` builds (165 live + 103 expired rows) |
| Holdings + positions (27 rows) | `GET /api/v2/portfolio/holdings`, `GET /api/v2/risk` | CIO truth `portfolio.holdings`, `positions.rows` (GUIDs, stop states) |
| CIO stances | `cio_prospect_shadow.json` written 13:53Z today by the real-data proof run of #2102 (merged 17:30Z) | production `data/cio/` has no shadow yet: the canary lane first runs Monday 09:00 ET. Without it 316 of 320 subjects are R7 "No CIO stance" (#2111). |
| Re-entry desk (92 rows) | stored snapshot `data/runtime/reentry_decision_desk_latest.json` (13:58Z) | never rebuilt |
| Identity | `resolve_security_identity` over a copy of `data/runtime/identity_registry.json` | |

No database session was opened by the capture (the read models above are what the pages serve). No `.env`, cookie
or credential file was read; the fixture is scanned for secret markers by the test. 323 subjects.

Rebuild (writes only `--out`; never overwrites):

```
C=<capture dir>; curl -s "http://127.0.0.1:7777/api/v3/data-broker/watch-intelligence?view=all&page_size=100&page=1" -o $C/wi_all_1.json  # … pages and view=expired
python3 scripts/conflict_golden_capture.py --watch $C/wi_all_*.json $C/wi_expired_*.json --holdings $C/holdings.json \
  --risk $C/risk.json --cio-shadow $C/cio_prospect_shadow.json --reentry-snapshot $C/desk.json --state-root $C/root \
  --captured-at <UTC> --out $C/golden.json
```

## Expected table (reviewed)

Two resolver runs (R15: a new flag needs two consecutive runs). Findings, run 2:

| Finding | Count | Subjects | Examples | Review |
|---|---|---|---|---|
| AGREEMENT R6 | 60 | 55 | AXTI, DT, DXCM, AXON, BND | not-held WATCH ≡ AVOID ≡ SELL; held adjacent steps — never flag |
| SUPERSEDED R1 | 23 | 23 | QCOM, LDOS (reviews frozen 09-02); ADBE, ALXO, ANET, HPE, TSLA (desk plan without time) | see deviation 3 |
| GATE R3 Trade AI | 12 | 12 | QCOM, HPE, KBR, LMT (STALE); FATN, ANET (DETERMINISTIC_FAIL); SMCI (BLOCKED) | matches the matrix's newly visible gates and DESIGN §5 |
| GATE R7b stale stance | 35 | 35 | AAPL, ABNB, FTH | CIO material evidence > 2 trading days on a positive stance, or > 10 |
| GATE R7 no stance | 14 | 14 | ARKG, CACI, NEE | "No CIO stance — WATCH/HOLD by default" |
| GATE R16 identity | 9 | 9 | ABLV, MPWR, SGMT | unresolved GUID gates every action |
| GATE R13 IPS headroom | 2 | 2 | BAH, NOC | positive held stance without a canonical weight |
| NEEDS_OPERATOR R12 | 9 | 9 | SCHD, SCHG, V, XLB | held, broker protection NONE / PENDING ACTIVATION / UNKNOWN — never automatic |
| DATA_ERROR R12 | 3 | 2 | SPCX, V | stop FILLED / awaiting fill — evaluation frozen |
| DATA_ERROR U1 | 39 | 36 | KBR, LMT, SPCX | 28 desk states and 2 review verdicts outside the shared vocabulary (`CURRENTLY HELD` 13, `OVERBOUGHT WAIT` 5, `MISSING PLAN` 4, `MISSING MARKET` 4, `READY TO REVIEW`, `OVERSOLD REVIEW`, `MANAGING`, `HOLD / MONITOR`); 9 subjects with no confirmed GUID |
| CONFLICT U7 | 1 | 1 | SCHG | held: CIO WATCH vs desk synthesis SELL (fresh, 2026-10-22) |

89 of 323 subjects flag; 234 do not (179 have no finding at all). Run 1 differs only in SCHG
(AGREEMENT R15 "Disagreement observed — confirmation due next run").

## Deviations from the matrix estimate (≈17 agreements · 5 superseded · 4 gates · 3 real over 31 flags)

1. **Population.** The estimate classified the 31 flags of 2026-10-24 (281 rows). This replay is the whole Watch
   universe of 2026-10-25 (323 subjects), so absolute numbers are larger; the matrix's "newly visible gaps" (Trade AI
   STALE gates, stance-less rows, unmapped labels, identity) are counted here as R3, R7/R7b, U1 and R16.
2. **Real conflicts 3 → 1.** DT: today's CIO stance is WATCH (not RE_ENTER), so CIO WATCH vs desk AVOID is the same
   action (R6). SCHD: the operator's R13 decision (broad fund, 25 % limit) means its 16.8 % weight raises no policy
   flag; SCHD now shows the never-automatic R12 protection item instead. SCHG: the three-way split is two-way today
   (review NOT_RUN; the desk's `CURRENTLY HELD` is unmapped vocabulary, U1), so it is one U7 conflict.
3. **Superseded 5 → 23.** 3 are CIO watch reviews frozen since 2026-09-02 (older than 7 d). 20 are re-entry desk sides
   whose plan has no time: every stored desk row has `plan_as_of: null` because `data_broker/entry_plan.get_entry_plans`
   never selected `created_at` (the desk reads `plan.get("created_at")`). R1 says missing time = stale, so the side
   cannot vote. This PR fixes the reader; once deployed the desk carries plan time and these 20 are compared again.
   Without the R1 registry the same capture gives 21 U7 conflicts (20 of them these desk sides) and 3 superseded.
4. **Gates 4 → 72.** R7b (35) and R7 (14) did not exist in the old classifier; they are the matrix's "24 stance-less
   My Watchlist rows" and staleness rules applied to the whole universe.
5. **Desk synthesis is not superseded in this capture.** The served Watch card omits a synthesis older than
   `watch_decision`'s freshness window, so R1 never sees it. `watch_source` (gap g) passes the raw row with its time.
6. **Trade AI time.** The served card has no `trade_ai_as_of`, so a positive stance reads "Unknown: Trade AI checks".
   `watch_source` supplies the packet's `generated_at`.
7. **Not in this capture:** T0 global halt and `next_run` labels (#2111's runner), R9 wash windows, R10 options and
   R12 pending fills (the conflict-producers-a PR).

Residual findings for owners: LDOS is not held in CIO truth while the desk says `CURRENTLY HELD` and Trade AI says
MANAGING (an ownership mismatch, R12 producer); 30 producer labels outside the shared vocabulary (R8).

## (g) Read-only Watch source and the exception rows

`scripts/lib/conflicts/watch_source.py` reads membership, CIO review artifacts (authorized like
`watch_domains.authorize_review_artifact`), desk synthesis rows, live decision packets (projected by the pure
`rockville.decision_projection` with the packet's stored action policy) and the stored re-entry snapshot. Database
access is an injected SELECT callable; `readonly_query()` opens a `default_transaction_read_only` session.
Transitive closure: 11 modules, no `broker_module`, `order_placement`, `direct_sender`, `chokepoint_send`, `db_write`
or `subprocess`; §23.3 guard scan clean (pinned by the test).

The runner swap is not in this PR: `scripts/conflict_resolver.py` is claimed by the conflict-producers-a session.
The exact `collect_inputs` change (proved on #2111's runner):

```python
    from scripts.lib.data_broker.cio_prospect import get_prospects
    from scripts.lib.conflicts.watch_source import read_watch_state, readonly_query
    document = resolve(root, now)
    held = {str(r.get("symbol") or "").upper() for r in document["positions"]["rows"]
            if (r.get("market_value") or 0) >= 100} if document["portfolio"]["holdings"] else None
    query = readonly_query()
    try:
        watch = read_watch_state(query, root=root, now=now, held_symbols=held)
    finally:
        query.close()
    cards, desk, symbols = watch["cards"], watch["reentry"], watch["symbols"]
    projection = get_prospects(shadow_base=Path(root) / "data/cio/cio_prospect_shadow.json", now=now)
    canonicals = stances_for_symbols(symbols, root=root, projection=projection, now=now)
```

(replacing the `compose_universe` / `reentry_rows` lines and moving `document = resolve(root, now)` up; #2111's
`global_halt_inputs` should take `readonly_query()` instead of `db_adapter._execute`).

Measured on #2111's runner with that change:

| Check | #2111 runner | with the swap |
|---|---|---|
| §23.3 guard (`advisory_lane_guard.scan_entry`) | sender, 80 broker modules, 13 trade contexts, 17 account reads | **clean** (no sender, broker, trade context or account read) |
| DD01 `broker_module` | via `watch_intelligence → watch_domains → positions_sync`, `db_adapter` | via `cio_truth → research_lane_health → db_adapter → holdings_guard → schwab_position_sync` |
| DD01 `order_placement` | via `watch_domains → positions_sync → schwab_transport` | via the same `cio_truth` chain → `schwab_transport` |

Rows to remove with the swap:

* `tests/test_agents_policy_7_0_0_advisory_market_data.py` `BASELINE["conflict-resolver"]` — the §23.3 entry.
  `test_baseline_is_shrink_only` then requires its removal.

Rows that stay, restated (they are not caused by the Watch composition):

* `config/n8n_lane_capability_baseline.json` `conflict-resolver.broker_module` / `.order_placement` and
  `CONFLICT_RESOLVER_20261025` in `tests/test_lane_transitive_capabilities_20261015.py`: the chain is now
  `cio_truth → research_lane_health → db_adapter` (W1 canonical) and `conflicts.cio → security_research_spine`
  (CIO memory sink). Removing them needs W1 `cio_truth` and the spine writer to stop importing `db_adapter`.
