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

Whatever the shape: a test that sets `COMMS_GATEWAY_MODE=ACTIVE` and asserts
`delivery_owned` is `true` would have caught this, and none exists.

## NOT DONE HERE

- no comms code changed
- no mode or env changed
- `phase: 7` in the payload may also be stale; not investigated
- separately: `comms_gateway_phase0` fails 7 tests on clean `origin/main`
  (`test_communications_portal`, `test_comms_subject_memory`) — verified against a
  detached baseline worktree, and unrelated to this finding
