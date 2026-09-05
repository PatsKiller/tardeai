# `delivery_owned` contradicts the gateway it describes

**Date:** 2026-09-05
**Found by:** the cc-header-final session, while verifying an unrelated deploy
**Owner:** comms-gateway (`wt/comms-gateway-phase0`) — **not actioned here**
**Surface:** `GET /api/v2/communications/health`
**Serving release at time of finding:** `869358d0e` (present since `f579053b8`, PR #864)
**Status:** reported, unfixed. No comms code was changed by the finder.

---

## HEADLINE

`/api/v2/communications/health` reports **`delivery_owned: false`** while the gateway
**is** delivering. It is the one question that endpoint exists to answer, and it is
answered by a constant that never reads the mode.

| source | says |
|---|---|
| serving process env | `COMMS_GATEWAY_MODE=ACTIVE`, `COMMS_GATEWAY_ACTIVE_CLASSES=ops` |
| `telegram_class_allowed('ACTIVE','ops')` | `True` — the gateway owns ops delivery |
| operator's Telegram | `[COMMS ACTIVE] gateway-owned ops notify 20260905T043104Z` |
| **`/api/v2/communications/health`** | **`delivery_owned: false`** |
| **same endpoint's banner** | **"gateway does not own delivery while OFF/SHADOW"** |

Three independent sources say the gateway owns ops delivery. The health endpoint says
it does not, and its banner asserts a mode the system is no longer in.

## WHY

`scripts/communications_portal.py:493`

```python
delivery_owned = False  # Phase 7: gateway never owns delivery while OFF/SHADOW
```

A literal. It does not read `mode`, which is fetched four lines above
(`get_gateway_mode(refresh=True)`), and it has no notion of
`COMMS_GATEWAY_ACTIVE_CLASSES`. The comment states the premise that made it true —
*while OFF/SHADOW* — and that premise expired when the mode became ACTIVE.

The banner two fields below is hardcoded the same way:

```python
"banner": "Ledger-backed · gateway does not own delivery while OFF/SHADOW",
```

## WHY IT IS WORTH A FIX RATHER THAN A SHRUG

The value is not merely stale — it is **stale in the safe-looking direction**.
`delivery_owned: false` is what an operator checks to confirm the gateway is *not*
touching their messages. It will keep saying that no matter how much traffic the
gateway owns, because nothing recomputes it.

That is the same shape as the defect the Command Center header carried for a
fortnight: `count_integrity: RECONCILED` was true, was rendered, and was read as
"fine" while `freshness_status: RUN_UNDERFILLED` sat unread on the same object. A
constant that was true once, presented as a live fact.

## REPRODUCE

```bash
curl -s localhost:7777/api/v2/communications/health \
  | python3 -c "import json,sys;d=json.load(sys.stdin)['data'];print(d['mode'], d['delivery_owned'], d['banner'])"
# ACTIVE False Ledger-backed · gateway does not own delivery while OFF/SHADOW

python3 - <<'PY'
import os, sys; sys.path.insert(0, 'scripts')
os.environ['COMMS_GATEWAY_MODE'] = 'ACTIVE'
os.environ['COMMS_GATEWAY_ACTIVE_CLASSES'] = 'ops'
from lib.comms.channel_adapters import telegram_class_allowed
print(telegram_class_allowed('ACTIVE', 'ops'))   # True
PY
```

## SUGGESTED SHAPE, NOT A PATCH

Deliberately not implemented here — the ownership predicate is the comms session's
contract, and guessing at another session's fail-closed semantics is how two sessions
corrupt one.

Roughly: derive `delivery_owned` from the same predicate delivery actually uses, and
publish *what* is owned rather than a bare boolean — a per-class map is the honest
answer once `ACTIVE_CLASSES` can be a subset. Something like:

```
delivery_owned: true                    # any class owned
owned_classes:  ["ops"]
unowned_classes: ["risk", "trade", ...] # still on the legacy path
banner: derived from mode, not literal
```

A bare boolean cannot express "ops yes, risk no", which is exactly the state the
system is in right now.

## THE GUARD WAS GREEN THE WHOLE TIME

**Correction to this finding's first version, which claimed no test existed.** One
does — `tests/test_communications_portal.py:55`:

```python
def test_health_empty_ledger_delivery_not_owned():
    h = portal.health()
    assert h["delivery_owned"] is False
    assert h["mode"] == "OFF"
```

Caught by the `tradeai-wt-final-operator-convergence-b9` session reviewing this
writeup. It is the more useful fact: the constant was not unguarded, it was
guarded by a test that only ever exercises the OFF case, so the gate stayed green
straight through cutover.

One refinement on top of that, because it changes what a fixer should expect.
This test also asserts `mode == "OFF"`, so it is scoped to OFF *by assertion*,
not merely by an unset environment. A fix that derives `delivery_owned` from the
mode would still pass it unchanged — mode is OFF in the test environment, so a
correct derivation yields `False` there too. **The fixer does not have to weaken
this assertion**, which removes the obvious reason to hesitate.

The real fail-closed contract already agrees. `tests/test_comms_enforcement_gate.py:31`:

```python
def test_delivery_owned_illegal_in_off_shadow():
    assert_delivery_not_owned_in_off_or_shadow("OFF", delivery_owned=False)
```

Mode-scoped to OFF/SHADOW, and it never required ACTIVE to be `False`. The
constant conflates that narrow contract with a global one. Nothing in the
enforcement layer is asking for the current behaviour.

All THREE assertions in that test survive a correct fix. The third pins the
banner, and is `or`-shaped:

```python
assert "OFF/SHADOW" in h["banner"] or "does not own delivery" in h["banner"]
```

Under OFF, any correct derivation still produces "does not own delivery", so it
passes unchanged too. Stated explicitly because *"will this fight the safety
tests?"* is the first question anyone opening this will ask, and the answer is
demonstrably **no, for all three**.

Supporting the per-class suggestion: `communications_portal.py` references
`COMMS_GATEWAY_ACTIVE_CLASSES` and `telegram_class_allowed` **zero** times. It
cannot express per-class ownership even in principle.

## THE MISSING TEST NEEDS NO SCAFFOLDING, AND FAILS TODAY

`tests/test_comms_telegram_canary_active.py:21` already has the harness — an
autouse fixture that clears `COMMS_GATEWAY_MODE` and
`COMMS_GATEWAY_ACTIVE_CLASSES`, resets the mode cache, and stubs `_db_conn` to
`None` on both `comms.client` and `comms.delivery`. So the ACTIVE-side test can
be written in that file with no new scaffolding and **no database**.

On the cache reset, precisely: `resolve_mode` memoises
(`scripts/lib/comms/mode.py:29-30` returns the cached value unless `refresh`),
but `health()` calls `get_gateway_mode(refresh=True)` at `:485`, so **this**
assertion reads fresh env whether or not the cache was reset. The reset is
load-bearing for cross-test isolation — the fixture is autouse because a prior
test leaves a mode cached — and for any assertion reaching the mode through a
default `refresh=False` path. Note that `telegram_class_allowed(mode, ...)` is
not such a path: it takes the mode as a parameter and never consults the cache.
The risk sits with whoever *fetches* the mode to pass in.

Also why the local failures split the way they do: the canary file stubs the DB
and `test_communications_portal.py` does not. The 7 local failures and the
missing test have the same root.

Run against that harness, the defect reproduces as a unit test:

```
mode           = ACTIVE
delivery_owned = False        <-- never reads mode
banner         = Ledger-backed · gateway does not own delivery while OFF/SHADOW

AssertionError: delivery_owned is a constant; it never reads mode
```

Confirmed not-coverage: the `"delivery_owned": True` at
`test_comms_telegram_canary_active.py:181` is a **mock return** from a stubbed
`send_via_gateway`, never an assertion against `portal.health()`. The health
endpoint has zero ACTIVE-mode coverage.

The harness discovery, the third-assertion catch and the mock/coverage
distinction are all from the `tradeai-wt-final-operator-convergence-b9` session.
The reproduction above was run here to confirm them; the probe was a scratch file
and is not committed — no comms test file was touched.

## CORRECTION: MAIN IS NOT RED

The first version of this finding said `comms_gateway_phase0` fails 7 tests on
clean `origin/main`. **That was wrong and is withdrawn.**

CI passes it: `[PASS] comms_gateway_phase0` on `869358d0e`
(cio-production-hardening-ci run 33945925701, 2026-09-05T05:02:34Z), and the
`[RUN]` line enumerates all 13 files including the two named —
`test_communications_portal.py` and `test_comms_subject_memory.py`.

My 7 local failures are environmental, almost certainly no database: the health
path calls `_events_db_conn()` and subject-memory needs storage. I compared
against a detached baseline worktree and saw the same failures there, which told
me they were not introduced by my branch — true — and I then over-read that as
"main is red", which does not follow. Both environments lacked the same thing.

Left in rather than deleted, because "the finder over-claimed once" is worth
knowing when weighing the rest of this document.

## NOT DONE HERE

- no comms code changed
- no mode or env changed
- `phase: 7` in the payload may also be stale; not investigated
