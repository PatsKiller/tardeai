# CIO persistent spine — preconditions board (Slice E)

Date: 2026-08-30 (evidence captured 2026-08-29 late session)
Authority: `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0` · `MBI_COGNITION=1`
Board: `scripts/cio_preconditions_board.py` → `CIOPreconditionsBoard@v1`

**Headline: 2 GREEN, 2 RED.** The spine persists correctly and refuses correctly.
Nothing in the product reads it back. That is the finding, and a truthful RED is
the deliverable here — not a green board.

---

## 1. The four-item board, against live CURRENT

Run: `python3 scripts/cio_preconditions_board.py --root /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`

```
CIOPreconditionsBoard@v1  authority=READ_ONLY_ADVISORY  MBI_BEHAVIOR=0
root      : /home/johnclaw/trade-ai-releases/portfolio-server/8f108622-main-exact-phase2-20260829-223817
store     : /home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl
root probe: ROOT_OK — 40 subject(s)
records   : EXIT=24, HELD=15, SLEEVE=1  (total 40)

PRECONDITIONS
  1. [GREEN        ] S0 attach + rehydrate (operator turn on the record, read back)
        1 record(s) carry an operator turn with a plan_id and hand it back through the gate input
        CAVEAT: read-back verified through cio_rehydrate.gate_input_from_record;
                NO scheduled product wake imports it yet, so this is a working
                mechanism, not yet a working loop
  2. [RED          ] CC shows a non-SCHD held narrative + the cash letter, no ping
        12 non-SCHD held narrative(s) exist on records but none appears in the CC
        payload; the cash letter is on the record but not in the CC payload
  3. [RED          ] Grok critique attach OR reject persisted on a record
        no record carries last_artifact_id, a critique lesson, or a reject outcome
        — no critique has ever been written back
  4. [GREEN        ] dust / CASH-as-a-ticker cannot mint or fire
        9 refusal probes held, a real ticker still mints, and no stored record is
        dust or cash

spine wake consumers: NONE

TOTAL green=2 red=2 cannot_verify=0
```

### Why each verdict

**1 — GREEN, with a caveat that matters.** `HELD:SCHD` carries an operator turn
with `plan_id=plan_79fe9e72f2d4`; that turn moved four cognition fields; and
`gate_input_from_record` hands the plan_id and the pushed eligibility straight
back to a later wake. The mechanism is real. What is *not* real is a caller:
`scan_wake_consumers` finds **zero** product modules importing the spine, and no
cron entry or systemd timer runs one. The GREEN is on the mechanism, and the
board prints the caveat on the same line so it cannot be read as a working loop.

**2 — RED, and not because the narratives are missing.** Twelve non-SCHD HELD
records carry real prose (`HELD:NOC`, `HELD:XLB`, `HELD:BAH`, …), and
`SLEEVE:CASH` carries the cash letter. None of it reaches
`/api/v3/cio/home`: every `holdings_thesis_coverage.items[].why_owned_or_watched`
is `null`, because that field is fed from the symbol-thesis store, not from
`cio.instrument_records`. The "no ping" half is satisfied
(`telegram_sent=false`, `would_send_any=false`, `delivery=dashboard`) — the CC
is silent, it just has nothing of the record's to say.

**3 — RED, unambiguously.** Across all 40 records: `last_artifact_id` is `None`
40/40, `last_outcome` is `None` 40/40, `research_blocked` is unset 40/40, and no
lesson mentions a critique. Slice B's rule-2 branch (reject → reframe the
question, flag `research_blocked`) is implemented and unit-tested but has never
fired on live data.

**4 — GREEN.** Nine refusal probes hold at the gate, the control symbol still
mints (so the gate is not simply refusing everything), and no stored record is a
cash/TEST ticker or one of the four live dust tickers.

### The root trap, handled explicitly

Many CIO stores use relative paths and follow the CWD. Run the board from a
worktree with no `data/` and a careless implementation reports four REDs about a
spine that is perfectly healthy. This board reports **CANNOT_VERIFY** instead,
and names the path it looked at:

```
root probe: ROOT_NO_CIO_DIR — no data/cio under <worktree> — this tree carries no
CIO state. Re-run with --root pointing at the live release (.../CURRENT).
  1. [CANNOT_VERIFY] S0 attach + rehydrate …
TOTAL green=0 red=0 cannot_verify=4
```

Three root verdicts map to CANNOT_VERIFY: `ROOT_NO_CIO_DIR`,
`ROOT_NO_RECORD_STORE`, `ROOT_EMPTY_STORE`. An unreachable CC payload is also
CANNOT_VERIFY, never RED — a surface that cannot be fetched is unverified, not
broken.

---

## 2. Record counts by kind

| kind | count |
|------|-------|
| HELD | 15 |
| EXIT | 24 |
| SLEEVE | 1 |
| **total** | **40** |

129 append-only rows project to 40 subjects. Store resolves through
`CURRENT/data/cio/` to
`/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl`.

---

## 3. The SCHD defer, as shown on the record

```json
"last_operator_turn": {
  "intent": "defer",
  "note": "wait for price buffer",
  "plan_id": "plan_79fe9e72f2d4",
  "text_hash": "65e59e0a6d4cbceb",
  "ts": "2026-08-11T21:33:52.184311+00:00"
}
```

```
next_eligible_at       : 2026-09-06T02:34:32.326342+00:00   (pushed; skips on cadence)
next_research_question : Has a catalyst or earnings event changed the condition
                         behind the defer (wait for price buffer)?
notify_priority        : cc
cc_narrative.writer    : cognition:defer_honored
cc_narrative.what      : "Operator deferred: wait for price buffer. Under desk@v5
                          (defensive_observe): concentration/disposition on SCHD.
                          Fire=weight_17.6pct. …"
```

The read-back a later wake performs:

```json
{"plan_id": "plan_79fe9e72f2d4",
 "next_eligible_at": "2026-09-06T02:34:32.326342+00:00",
 "symbol": "SCHD", "event_fired": false, "material": true}
```

The plan_id survives on the record. This is the exact thing that was lost before
Slice A: attaching the turn to the plan alone meant the plan closed and the
disposition went with it.

---

## 4. Cash letter excerpt

As stored on `SLEEVE:CASH` (not surfaced in the CC — see check 2):

```json
{
  "what": "Cash sleeve 630784.82.",
  "thesis_fit": "Cash is intentional optionality under the desk thesis.",
  "recommendation_option_id": "hold_cash",
  "writer": "migration:deterministic",
  "as_of": "2026-08-30T02:34:32.327723+00:00"
}
```

The CC's own cash prose is a different object and comes from a different
producer — `earmark_narrative`: *"$630,785 of current cash is earmarked from
prior exits/redeploy; it is not new capital. Prospective raise is $168,440 from
trims/exits not yet cash. Recommended deploy $541,944 is bounded by investable
free cash plus prospective raise only."* Both describe the same $630,784.82; only
the second one reaches the operator. Cash is correctly modelled as
`SLEEVE:CASH`, never as a holding.

---

## 5. Cognition apply — before / after `next_research_question`

`HELD:NOC`, driven through `apply_after_cycle` with a rejected artifact.
In-memory only; nothing persisted (store row count 129 before and after).

| field | BEFORE | AFTER |
|-------|--------|-------|
| `next_research_question` | `None` | `Prior research was refused (rejected). What INDEPENDENT evidence would settle this without restating it?` |
| `next_eligible_at` | `None` | `2026-08-30T00:00:00+00:00` |
| `last_outcome` | `None` | `rejected` |
| `research_blocked` | unset | `True` |
| changed fields | — | `['next_research_question', 'next_eligible_at']` |

The reframe is the point: re-asking a prompt that already failed closed is how a
desk burns a research budget learning nothing.

---

## 6. MBI evidence — behaviour refused, cognition required

`MBI_BEHAVIOR=0` — a size cannot travel through cognition:

```
>>> apply_cognition(rec, recommended_delta_usd=25000)
BehaviorWriteRefused: MBI_BEHAVIOR=0: cognition may not carry ['recommended_delta_usd']

>>> apply_cognition(rec, size_usd=1, shares=10)
BehaviorWriteRefused: MBI_BEHAVIOR=0: cognition may not carry ['shares', 'size_usd']
```

Refused outright rather than filtered — a silently dropped size field looks like
it was honoured.

`MBI_COGNITION=1` — a write that moves nothing is a FAILED persist, not a no-op:

```
>>> apply_cognition(rec, notify_priority=rec['notify_priority'])
CognitionNoOp: HELD:NOC: nothing in ('next_research_question', 'next_eligible_at',
'notify_priority', 'cc_narrative') changed — a lesson that moves no decision is
not persisted
```

Test evidence: `tests/test_cio_instrument_record.py` (22 tests),
`tests/test_cio_rehydrate_slice_b.py` (13 tests),
`tests/test_cio_preconditions_board.py` (32 tests) — **91 passed**.

---

## 7. Live notify rails — read, not asserted

The original spine spec said "Do NOT lift INTERDICT, do NOT set
`CIO_SITUATION_NOTIFY=1`" and assumed notify was off. **That text is stale.** The
operator turned Telegram delivery on and confirmed it supersedes the pin. The
board therefore reads `/proc/<server pid>/environ` and `config/cio_llm_policy.yaml`
and prints what it finds. It changes nothing.

| rail | live value | source |
|------|-----------|--------|
| `CIO_SITUATION_NOTIFY` | `1` | `/proc/3280084/environ` |
| `CIO_TELEGRAM_INTERDICT` | `0` (interdict NOT raised) | `/proc/3280084/environ` |
| `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY` | `1` | `/proc/3280084/environ` |
| `ENABLE_TELEGRAM` | `true` | `/proc/3280084/environ` |
| `situation_notify_telegram` | `true` | `config/cio_llm_policy.yaml` |
| `notify_situation_types` | `S6_CONCENTRATION_OR_DISPOSITION` only | `config/cio_llm_policy.yaml` |
| notify enabled (derived) | **true** | env AND policy |

The bar is narrowed to S6 alone — deliberately, per the 2026-08-29 operator note
in the policy file. Widening that list is what turns a 4-message desk into a
400-message one. Bot tokens and chat IDs sit next to these flags in the same
environment; `read_server_env` collects only the keys in `NOTIFY_ENV_KEYS`, and a
test pins that no token or chat ID appears in the board output.

Nothing in this slice sent a Telegram, made a vendor/LLM call, or touched a flag.

---

## 8. What would move the two REDs

Neither RED is a defect in Slice A or B. Both are the same missing thing stated
twice: **the record has no reader.**

- **Check 2** needs a CC producer to take `cc_narrative.what` off the record for
  held subjects and off `SLEEVE:CASH` for the cash letter, in addition to (not
  instead of) the symbol-thesis field. The silent-delivery half already passes.
- **Check 3** needs the critique lane to route its verdict through
  `apply_after_cycle(artifact=…)`. The reject branch exists and is tested; it has
  never been handed a live artifact.
- **Check 1's caveat** dissolves the moment either of the above lands, because
  both require a wake that reads a record.

---

## Provenance

- Board: `scripts/cio_preconditions_board.py`, `scripts/lib/cio_preconditions_board.py`
- Tests: `tests/test_cio_preconditions_board.py` — 32 tests
- Read-only: no `--apply` exists. The board reads the record store, one HTTP
  payload, the policy file and the server environment. `test_the_board_writes_
  nothing_to_the_store` pins the store bytes across two full board builds.
- `NO_CONSUMER_REASON` declared on the CLI; `scripts/check_dark_contracts.py`
  reports 0 new unexplained zero-consumer schemas.
