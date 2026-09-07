# Communications Gateway — `operator_alert` Canary Runbook (Wave B)

```
Status: PROPOSED (operator-only — the widening steps below are not applied)
as_of: 2026-09-05T15:15:00-04:00
Companion: canary-operator-alert-packet.md (finding + rationale)
```

This is the concrete cutover sequence for the operator. **Status update
(2026-09-05T13:56:00-04:00):** the deployment precondition is now met (PR #871 merged,
served SHA `f88853e89`, mode reverted to CANARY `ops`), but the §1–§3 widening steps are
**still pending** and require operator sign-off (§17). The ownership-gate normalization
the runbook depends on is **still not committed/deployed**.

---

## 0. Preconditions

- [x] **DONE** — Deploy the branch at `wt/comms-gateway-wave-a-attest` HEAD
      (release-governed; exact SHA resolved at deploy time). Merged as PR #871
      (`47576f7fa`) and superseded by #872/#873; served SHA is now `f88853e89`. This
      carried F1 and F3. **The ownership-gate normalization (§2 of the packet) is NOT
      in the deployed tree — still pending.**
- [x] **DONE (changed)** — Confirm the live `32-comms-gateway-mode.conf` drop-in. It no
      longer sets `MODE=ACTIVE`; it now sets `MODE=CANARY` + `CANARY_CLASSES=ops` +
      `CANARY_CHATS=6993102664,8797974247` (the ACTIVE posture was reverted).
- [x] **DONE** — Choose a **bounded canary chat-id set**. Recorded and applied:

  ```
  COMMS_GATEWAY_CANARY_CHATS=6993102664,8797974247
  ```

  > Without `CANARY_CHATS`, CANARY mode applies **no chat filter** — the canary
  > would reach every chat `TELEGRAM_CHAT_ID` resolves to (see
  > `test_canary_without_chat_allowlist_does_not_filter`). This is now set.

## 1. SHADOW stage (parity evidence, no ownership) — **STILL PENDING**

Drop-in change (same file):

```
COMMS_GATEWAY_MODE=SHADOW
# CANARY/ACTIVE_CLASSES ignored in SHADOW; leave them set for the next step
```

Restart gateway consumers → collect `shadow_report()` parity on
`subject_key` / `severity` / `route_intent` for the 254-site cohort. Archive the
JSON under `~/.local/state/cio-phase2-exact-main/comms-shadow-evidence/`.

**Exit:** match rate ≥ 0.99 or every mismatch triaged + waived per field.

## 2. CANARY stage (bounded ownership) — **STILL PENDING** (current CANARY is `ops`, not the `operator_alert` cohort)

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

## 3. ACTIVE stage (the allowlist is unchanged — `ops`) — **STILL PENDING**

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
