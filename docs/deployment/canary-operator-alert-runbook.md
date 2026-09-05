# Communications Gateway — `operator_alert` Canary Runbook (Wave B)

```
Status: PROPOSED (operator-only — nothing here is applied)
as_of: 2026-09-05T15:15:00-04:00
Companion: canary-operator-alert-packet.md (finding + rationale)
```

This is the concrete cutover sequence for the operator. Every line is a review
artifact; **none of it has been run**. The code it depends on is committed locally
on `wt/comms-gateway-wave-a-attest` (inert at OFF/SHADOW until deployed + CANARY).

---

## 0. Preconditions

- [ ] Deploy the branch at `wt/comms-gateway-wave-a-attest` HEAD (release-governed;
      exact SHA resolved at deploy time). This carries F1, F3, and the
      ownership-gate normalization — all inert until mode = CANARY/ACTIVE.
- [ ] Confirm the live `32-comms-gateway-mode.conf` drop-in (the one that already
      sets `MODE=ACTIVE` + `ACTIVE_CLASSES=ops`) is the file being edited.
- [ ] Choose a **bounded canary chat-id set** (one or two operator chats, not the
      full operator family). Record it here:

  ```
  COMMS_GATEWAY_CANARY_CHATS=<FILL_ME: comma-separated chat ids>
  ```

  > Without `CANARY_CHATS`, CANARY mode applies **no chat filter** — the canary
  > would reach every chat `TELEGRAM_CHAT_ID` resolves to (see
  > `test_canary_without_chat_allowlist_does_not_filter`). Do not skip this.

## 1. SHADOW stage (parity evidence, no ownership)

Drop-in change (same file):

```
COMMS_GATEWAY_MODE=SHADOW
# CANARY/ACTIVE_CLASSES ignored in SHADOW; leave them set for the next step
```

Restart gateway consumers → collect `shadow_report()` parity on
`subject_key` / `severity` / `route_intent` for the 254-site cohort. Archive the
JSON under `~/.local/state/cio-phase2-exact-main/comms-shadow-evidence/`.

**Exit:** match rate ≥ 0.99 or every mismatch triaged + waived per field.

## 2. CANARY stage (bounded ownership)

Drop-in change (same file):

```
COMMS_GATEWAY_MODE=CANARY
COMMS_GATEWAY_CANARY_CLASSES=ops
COMMS_GATEWAY_CANARY_CHATS=<FILL_ME>
```

Restart → verify:

```bash
curl -s http://127.0.0.1:7777/api/v2/communications/health | python3 -m json.tool
# expect: mode=CANARY, owned_classes=["ops"], banner mentions canary
```

Soak window ≥ operator-determined. Confirm:

- gateway `SENT` rows with `provider_message_id` for owned `operator_alert` defaults,
- zero `delivery_blocked_*` for owned defaults,
- unlisted chats receive **nothing** (negative control),
- zero dual-send (ledger + observed traffic).

## 3. ACTIVE stage (the allowlist is unchanged — `ops`)

Only after the soak: revert mode to the current production value; because the
ownership-gate normalization now folds `operator_alert` → `ops`, the 254-site
default cohort joins the already-owned `ops` class with **no allowlist edit**:

```
COMMS_GATEWAY_MODE=ACTIVE
COMMS_GATEWAY_ACTIVE_CLASSES=ops
```

## 4. Rollback (any stage)

```
COMMS_GATEWAY_MODE=OFF
```

Restart → confirm `mode_diagnostics()["delivery_owner"] == "legacy_or_none"`.
Ledger rows stay. The normalization is inert at OFF/SHADOW, so rollback is a mode
flip, never a code revert.

## 5. Decision gate

Each stage advances only on operator sign-off. The artifact this runbook produces
that a later `Wave H` DoD audit will cite: SHADOW report JSON, CANARY canary row in
`canary-results.md`, rollback rehearsal receipt, and the final `owned_classes=["ops"]`
health snapshot.
