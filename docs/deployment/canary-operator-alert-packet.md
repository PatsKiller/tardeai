# Communications Gateway — Wave B Canary Packet: `operator_alert` cohort

```
Status: PROPOSED (operator sign-off required before any ownership widening)
as_of: 2026-09-05T15:05:00-04:00
Measured at: worktree HEAD 614744cc6 (branch wt/comms-gateway-wave-a-attest);
             served build faf8c05d9 (live, unchanged)
```

This packet proposes widening gateway delivery ownership to the `operator_alert`
cohort. **No allowlist, mode, or code change described here has been applied or
deployed.** It is a proposal that stops at the operator gate (§17).

---

## 1. The finding that changes the ladder `[VERIFIED]`

The rollout plan (Stage 2) lists `operator_alert` as the *first* canary class, on
the assumption it is a narrow, low-risk slice. Measurement refutes that assumption:

| Metric | Value | Command |
|---|---|---|
| `send_telegram` call sites using the **default** `message_class` (= `operator_alert`) | **254** across **147 files** | `rg 'send_telegram\(' scripts/ --glob '*.py'` + parse for absent `message_class` |
| Explicit `message_class=` values in the tree | `ops` 40, `approval` 2, `report` 2, `protection_incident` 1, `proposal` 1 | same parse |

`operator_alert` is the **default parameter of `send_telegram`**, not a distinct
class. "Canarying `operator_alert`" is therefore a fleet-wide cutover of the
entire operational-alert surface — the exact "never all Telegram in one step"
anti-pattern the rollout plan forbids. The `ops` canary that preceded it was a
genuine narrow class (40 explicit sites); this one is 254 implicit sites.

## 2. The correct change is one line, and its blast radius is the problem

Wave A F3 canonicalized the **ledger**: `publish_communication` now normalizes
`operator_alert` → `ops`. The **ownership** gate was not touched, so two
producers sending the same concept diverge on delivery ownership:

- `send_telegram(..., message_class="ops")` → gateway-owned (40 sites).
- `send_telegram(...)` (default `operator_alert`) → legacy + best-effort (254 sites).

The fix is to normalize at the gate so ownership and ledger agree:

```python
# scripts/lib/comms/channel_adapters.py
def telegram_class_allowed(mode: str, message_class: str) -> bool:
    mc = normalize_message_class(message_class)   # <- add this import + line
    if not mc:
        return False
    return mc in set(telegram_owned_classes(mode))
```

This is correct, minimal, and covered by `normalize_message_class` semantics
(unknown classes pass through unchanged; protected classes never alias away).
But deploying it with the live `COMMS_GATEWAY_ACTIVE_CLASSES=ops` would fold all
254 sites into gateway ownership at once.

## 3. Proposed bounded rollout

Reuse the mechanism that bounded the `ops` canary: **CANARY mode + chat allowlist**.

| Stage | State | Scope |
|---|---|---|
| 0 | OFF (current) | legacy delivery, ledger normalized to `ops`, stubs settled `LEGACY_DELIVERED` |
| 1 | SHADOW | `COMMS_GATEWAY_MODE=SHADOW` on a single host; record legacy-vs-gateway parity on `subject_key`/`severity`/`route_intent` via `shadow_compare.py` |
| 2 | CANARY | `COMMS_GATEWAY_MODE=CANARY` + `COMMS_GATEWAY_CANARY_CLASSES=ops` + `COMMS_GATEWAY_CANARY_CHATS=<bounded chat id set>`; ownership gate normalization **deployed** |
| 3 | ACTIVE | after soak: `COMMS_GATEWAY_ACTIVE_CLASSES=ops` (unchanged) with the normalization live → `operator_alert` defaults fold in |

Stage 2 is the safety valve: `_provider_send_telegram` already filters targets to
`COMMS_GATEWAY_CANARY_CHATS` when mode is CANARY (`channel_adapters.py:160-164`).
The fleet stays on legacy until the operator widens chats.

## 4. Evidence required before sign-off

1. **SHADOW compare** for the 254-site cohort: `subject_key` / `severity` /
   `route_intent` parity ≥ threshold, mismatch triage per field.
2. **CANARY soak** over the operator chat subset: gateway `SENT` rows with
   `provider_message_id`, zero `delivery_blocked_*` for owned defaults, zero
   dual-send.
3. **Negative controls**: replay denial, unauthorized-chat denial (CANARY_CHATS),
   duplicate suppression, protected-fact class never aliased into `ops`.
4. **Rollback drill** (below) executed and recorded.

## 5. Rollback

Identical to `docs/deployment/rollback-plan.md`: `COMMS_GATEWAY_MODE=OFF` → restart
gateway consumers → confirm `delivery_owner == "legacy_or_none"`. Ledger rows stay.
The ownership-gate normalization is inert at OFF/SHADOW (mode gate rejects first),
so a revert is a mode flip, not a code revert.

## 6. Not done without sign-off

- Not committing the `telegram_class_allowed` normalization (shown as a diff only).
- Not deploying anything.
- Not touching `COMMS_GATEWAY_ACTIVE_CLASSES` / `CANARY_CLASSES` / `CANARY_CHATS`.
- Not backfilling historical `operator_alert` ledger rows (a live-DB mutation).

## 7. Decision needed

The subdivision strategy is operator-owned. Three options follow.
