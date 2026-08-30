# CIO Residual Web Lane — live hop runbook

Status: **lane built, gated, and STUBBED. The live vendor hop has NOT been taken.**
Schema: `ResidualWebLane@v1` · Authority: `READ_ONLY_ADVISORY` · `MBI_BEHAVIOR=0`, `MBI_COGNITION=1`

This document is the runbook for the single billed call the operator sequences
separately. Everything above the receipt section is already merged and tested;
the receipt section is empty by design and is filled in by running one hop.

---

## 1. The ladder, and which rung this is

The ladder is unchanged. It still has exactly seven rungs and
`ResearchNeedDecision@v2` still routes them in the same order:

```
skip → reuse → corpus_hit → flash → pro → [residual] → grok_critique
```

**The residual rung is the existing token `openai`.** It was already the
residual step before this work:

- `cio_research_gate.decide()` has always returned it for
  `pro_unresolved_and_material`;
- `cio_research_templates` has always carried its prompt skeleton —
  *"OPENAI — residual only, the questions Pro left open, JSON schema out"* —
  and its output schema, which is the only one with a `still_unresolved` field.

So the operator's conditional ("reuse `openai` if that is already the residual
step") resolves to **reuse**. No eighth rung was invented, and the wire token
did not change.

`residual_web` is the name of the **lane that executes** that rung. The gate
names the rung; the lane names the executor. The mapping is explicit:

```python
cio_research_gate.RESIDUAL_DECISION = "openai"
cio_research_gate.RESIDUAL_LANE     = "residual_web"
cio_research_gate.LANE_FOR          = {..., "openai": "residual_web", ...}
```

Every gate decision now carries a `lane` key. That is reporting only — it
changes no routing.

### Why the token was not renamed

Renaming `openai` → `residual_web` would have touched, silently in most cases:

| Site | Breakage |
|---|---|
| `cio_research_templates._SYSTEM["openai"]`, `_OUTPUT_SCHEMA["openai"]`, `GATES` | prompt + schema lookups return empty |
| `cio_specialist_artifact.PROVIDERS` | `build()` **raises** on an unknown provider |
| `cio_research_gate_report` duplicate collapse | a re-listed literal set; would stop covering the renamed token |
| ~8 ban-list tests asserting `"openai" not in source` | start passing **vacuously** |

The rung is a stable contract with four consumers. The lane is the new thing,
so the lane got the new name.

---

## 2. When a residual web hop is legal

`cio_residual_web.legality()` returns a decision-shaped dict — never a bare
bool — so a refusal is loggable and a quiet day reads as a quiet day. **All
eight conditions must hold:**

| # | Check | Refusal id |
|---|---|---|
| 1 | The gate **already** routed this subject to the residual rung | `gate_routed_to_residual` |
| 2 | Material | `material` |
| 3 | Free-first miss — no `reuse`, no A/B corpus close | `free_first_miss` |
| 4 | `next_eligible_at` due **OR** a price/weight/earnings/analyst hash moved | `due_or_hash_changed` |
| 5 | Prior outcome ≠ `execution_language`, and not `research_blocked` | `no_execution_language_history` |
| 6 | Subject kind ∈ HELD / EXIT / WATCH / SECTOR / SLEEVE | `eligible_kind` |
| 7 | Not dust, not TEST, not cash-as-a-ticker (`is_mintable`) | `not_dust_test_or_cash_ticker` |
| 8 | Under one hop per subject per day | `under_daily_subject_cap` |

Two properties worth stating out loud:

- **This lane never promotes a subject the gate did not send.** Condition 1 is
  not a formality — it is the whole reason the faucet is safe to open. The gate
  is not deleted, widened, or re-decided.
- **An UNSET hash is not a change** (`cio_instrument_record.hash_changed`).
  First contact means there is no prior belief to contradict. This matters
  today: all 40 live records have `hashes = {price: null, weight: null,
  earnings: null, analyst: null}`, so **no subject currently qualifies via the
  hash-change path.** A hash change overrides SKIP_FRESH and nothing else.

Dust / TEST / cash-ticker exclusion is delegated to
`cio_instrument_record.is_mintable`, not re-listed. There are already three
divergent cash/TEST vocabularies in this repo (`NON_INSTRUMENT_SYMBOLS`,
`holdings_universe.CASH_SYMBOLS`, `cio_s0_operator_loop._CASH`); a fourth was
not added.

---

## 3. Subject selection and budget

```
DAILY_SUBJECT_BUDGET        = 3      # subjects per day
MAX_HOPS_PER_SUBJECT_PER_DAY = 1     # one model class per subject per day
```

`select_daily()` ranks deterministically (ties break on `subject_key`, so two
runs on the same input agree):

1. HELD whose event hash moved ← preferred
2. `SLEEVE:CASH` if due ← the operator's stated fallback
3. any other HELD
4. everything else

**The cash sleeve outranks a quiet HELD name deliberately.** An earlier draft
put plain HELD at tier 2, which looked harmless and was caught only by running
the selector against the real book: 15 HELD records with no moved hash fill a
budget of 3 every single day, and `SLEEVE:CASH` is never reached. Two tests
now lock the ordering.

### Live dry run (read-only, 2026-08-29)

Run from CURRENT so the relative-path stores resolve correctly:

```
store path  : /home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl
records     : 40  {HELD: 15, EXIT: 24, SLEEVE: 1}
all-hashes-unset records : 39 of 40
selected    : ['SLEEVE:CASH', 'HELD:AMANX', 'HELD:ARKX']
stub hop    : provider=stub  cost_usd=0.0  paid_dispatch_entered=0
```

(The legality call above supplies `material=True` and a residual-routed gate
decision for every record, so "39 legal" is a *hypothetical* upper bound on the
selector, not a claim that 39 subjects are genuinely due. In production
condition 1 — the gate must already have routed the subject — does most of the
filtering, and no gate-driven worker exists yet to produce those routings.)

### Intended subject for the first live hop

> **`SLEEVE:CASH`** — the one $630k cash question, due, one hop.

Tier 1 is empty (no hash has ever been recorded, so nothing can have moved), so
the sleeve is first. It is also the cheapest possible proof: a sleeve, not a
holding, so nothing about it can be mistaken for a position directive.

The 36 open S5 cash plans do **not** re-expand into 36 calls. That collapse is
now a tested function, `cio_research_gate.collapse_same_day_duplicates()`,
lifted out of `cio_research_gate_report` (where it was previously inline and
had **no** test coverage at all). It collapses on `(kind, symbol, day)` **and**
on `(research_id, day)` — keying on `research_id` alone re-expands them, since
all 36 carry distinct research_ids.

Worker note: `--max` must not drain the warehouse. The existing `--max` lives
on `scripts/hermes_cio_worker.py --drain` and is a *separate* pipeline that
does not import the gate at all. **No gate-driven worker loop exists yet** —
that wiring gap is real and is not closed by this PR.

---

## 4. The call site

- **Helper:** the existing `llm_lane.generate(...)` → `llm_consumption.gate_and_generate`. No second harness.
- **Web fetch:** the existing shared `searxng_client.searx_search(...)`. Pass `searx_url` explicitly — `DEFAULT_SEARXNG` is port 8080 while every real caller uses 18888.
- **process_id:** `hermes_external_research` — already registered, `default_mode: automated`, `daily_cost_cap_usd: 0.30`, `lane_policy: deepseek_only`.
- **We did NOT invent `grok_execution_review`.** A test asserts that string never appears as a value in the lane module.
- **No new process was registered.** An unregistered `process_id` fails closed by design (`get_process_config` → `allowed_lanes=[]`), and that property is worth keeping.
- **Ledger:** `cost_usd` on that process, via `llm_consumption.log_call(...)` / the reservation pair, plus the FinOps event log.

---

## 5. Librarian-lite

Every URL becomes a typed `WebSourceRef@v1` before it may influence anything:

```
source_id | grade A–D | as_of | stale_after_days
```

The grade **law** is not re-implemented — `cio_corpus_index.CLOSING_GRADES`
(`{A, B}`) and `CONTEXT_ONLY_GRADES` (`{C, D}`) are imported by identity, and a
test asserts they are the same objects. What this PR adds is the axis that was
genuinely missing: **age**.

```
may_close(ref)  ==  grade ∈ {A, B}  AND  not stale
```

- **Grade C/D cannot corpus_hit.** They attach as challenge context only.
- **A stale A cannot corpus_hit either.** An A-grade filing is still an A-grade
  filing at 14 months, and still the wrong answer to "what is priced in now."
- **An undated source is stale** — fail closed.
- **Grades come from what a source IS, not what it says.** Official primary
  record (SEC, Fed, FRED, BLS, Treasury, issuer IR) → A. Blog / forum / social
  → D. Everything else → C. **B is never auto-assigned** — "independently
  reproduced with usable N" is a judgement a critique pass makes, not something
  a hostname earns.
- **A blog cannot be promoted to a closing grade by asserting one.** Passing
  `grade="A"` for a substack returns D. That laundering is exactly what this
  lane exists to prevent.

Default staleness: A 180d · B 45d · C 21d · D 7d (overridable per ref).

Entity questions may use official pages, not blogs —
`admissible_for_entity_question()`.

**Discovery** is re-exported, not rebuilt: `cio_source_discovery.discover()`
already caps proposals at **3 CANDIDATE per entity per week**, already refuses
to grade a candidate (`evidence_grade: None`, `is_fact: False`), and already
downloads nothing. No ingest farm.

---

## 6. What gets written back

**On VALID / PARTIAL** — `apply_hop()` writes, as cognition:

- `artifact_id`
- `source_urls[]` and every source's grade, `as_of`, `stale_after_days`
  (into `cc_narrative.evidence_refs`)
- `next_research_question` — and it **must differ from the prompt just used**;
  if it would collide it is suffixed `(reframed)`
- `cc_narrative` patch — **FACTS ONLY**
- `last_event_hash`, refreshed observable hashes
- `next_eligible_at` (+7d)

**On REJECT / execution_language:**

- `research_blocked = True`
- **no attach** — `last_artifact_id` stays `None`
- **no narrative at all** — `cc_narrative` is `None`, not prose that got
  filtered
- a reframed next question, `next_eligible_at` +1d

A narrative carrying execution language is **refused, not filtered**
(`ResidualWebRefused`). The check uses the one shared matcher,
`execution_language.find_imperative` — never a second word list. The matcher
already catches the operator's phrase:

```
find_imperative("do not add until price action confirms") == "do not add"
```

That was verified against the merged matcher and locked in with a test. The
matcher itself was **not** rewritten.

`MBI_BEHAVIOR=0` throughout: `apply_cognition` raises `BehaviorWriteRefused` on
any size/delta/order field, and `CognitionNoOp` when a write moved nothing.

---

## 7. CC + notify

- CC binds the **updated** `cc_narrative` via `cc_binding()`.
- `notify_priority` may rise to `cc` or `digest` on a hash change. **`immediate`
  is not reachable from this lane** — an existing `immediate_candidate` is
  preserved, never created. A rejected hop never raises the volume.
- Receipt stamped; dedupe by `subject_key` + day (reusing
  `cio_delivery_receipt.dedupe_key`).
- `telegram_sent: False` and `would_send: False` are constants in the CC block,
  exactly as in `cio_command_center`. **This lane adds no send site.**

---

## 8. Proof the stub path makes zero vendor calls

`run_hop(..., apply=False)` is the **default**, so the safe path is the one you
get by accident. Four independent proofs, all tested:

1. **Socket-level.** A fixture replaces `socket.socket.connect`,
   `socket.create_connection`, `http.client.HTTP(S)Connection.connect`,
   `urllib.request.urlopen` and `requests.Session.request` with a raiser. The
   stub hop runs clean under it.
2. **Probe counter.** Every result carries `paid_dispatch_entered`, read from
   `evidence_refresh_job`'s probe. It is `0`. A separate test confirms the probe
   itself still fails closed (`dispatch_paid_provider` raises
   `PAID_DISPATCH_FORBIDDEN` and increments).
3. **Structural.** `_stub_transport` is AST-checked to contain **no import
   statements**. The live transport's `searxng_client` / `llm_lane` imports are
   local to `_live_transport`, so importing the module never pulls in a network
   client. A second test greps everything above `_live_transport` for
   `requests` / `urllib` / `httpx` / `llm_lane` / `searxng_client`.
4. **Cost.** A stub hop that reports a non-zero cost raises
   `ResidualWebRefused`. `provider == "stub"` ⟹ `cost_usd == 0.0`.

The stub returns **UNAVAILABLE** rather than inventing findings — a stub that
fabricates a plausible answer is worse than one that returns nothing, because
the fabrication is what gets attached to the record.

---

## 9. LIVE HOP RECEIPT — *to be filled by the operator*

> Run exactly one hop, then paste the receipt here. Nothing below this line has
> been executed.

**Command**

```bash
# from CURRENT — the root trap is real; collectors resolve relative paths from CWD
cd ~/trade-ai-releases/portfolio-server/CURRENT
TRADEAI_ROOT=$PWD .venv/bin/python - <<'PY'
from scripts.lib.cio_residual_web import run_hop, apply_hop
hop = run_hop("SLEEVE:CASH",
              question="<the question the gate left unresolved>",
              question_ids=["<qid>"],
              apply=True)           # ← the single billed call
print(hop["cost_usd"], hop["source_urls"])
PY
```

| Field | Value |
|---|---|
| Date / time (UTC) | |
| Subject | `SLEEVE:CASH` (expected) |
| Decision token | `openai` (residual rung) |
| Lane | `residual_web` |
| process_id | `hermes_external_research` |
| **cost_usd** | |
| Outcome | VALID / PARTIAL / REJECT |
| `paid_dispatch_entered` | |

**Source URLs and grades**

| # | URL | source_id | grade | as_of | stale_after_days | may_close |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |

**Record before**

```json
```

**Record after**

```json
```

**Cognition delta** — which of `next_research_question` / `next_eligible_at` /
`notify_priority` / `cc_narrative` moved:

```
```

**Checks to confirm after the hop**

- [ ] `cost_usd` is non-zero and within the `hermes_external_research` 0.30/day cap
- [ ] the next question **differs** from the prompt just used
- [ ] no narrative text contains maintain / add / buy / sell / trim
- [ ] `telegram_sent` still False; no Telegram was sent
- [ ] exactly **one** hop for this subject today
- [ ] every URL carries a grade and an `as_of`
- [ ] on REJECT: `research_blocked=True`, `last_artifact_id` is None, `cc_narrative` is None

---

## 10. Known gaps (honest)

- **No gate-driven worker loop exists.** `cio_research_gate_report.py` is a dry
  report and the only non-test consumer of the gate; `hermes_cio_worker.py` is
  a different pipeline that never imports it. This PR builds the lane and its
  gating, not the scheduler that would call it in production.
- **The live transport has never been executed** — by design (scope limit). It
  is written but unproven against a real endpoint. The SearXNG port default
  (8080 vs 18888) is a live-path hazard flagged above.
- **No subject currently qualifies via hash-change**, because all 40 live
  records have UNSET hashes. Until an observable is recorded once, the lane
  reaches subjects only through the `due` path.
- `cost_usd` ledgering on the live path is wired to the existing consumption
  ledger but, like the transport, is unexercised here.
