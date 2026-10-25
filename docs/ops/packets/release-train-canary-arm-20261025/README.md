# Release train: arm the schedule with no per-release grant (2026-10-25)

```
Status:    PR #2099 (shared-infra). Protected surfaces: ships by the manual release path (arming packet L.1), never by a train.
Operator:  "It needs to work without grant. It's a perpetual grant."
           "I need it to run at around 12:00 p.m. and the schedule on the weekend should be different. It should run if
            there's something in the queue every three hours because the weekend will be the heaviest development."
           "On the weekends, on Saturdays and Sundays, starting at 6:00 a.m., releases should be every three hours. If
            there's nothing there, then nothing gets released."
           "Yes, it can run overnight until 3:00 a.m. Sunday morning. The market does not open until 6:00 a.m. in the US."
Packet:    docs/ops/packets/release-train-arming-20261021/README.md I.3, I.4 PR 3, §K, J
Authority: MBI_BEHAVIOR = 0. No broker, order or credential path. Broker / Active Trader code stays held.
```

## Schedule (America/New_York)

| Day | Windows |
|---|---|
| Mon–Fri | 12:00, 18:00 |
| Saturday | 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 |
| Sunday | 00:00, 03:00 (the Saturday-night overnight), 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 |

Not scheduled: Saturday 00:00/03:00 (Friday night), Monday 00:00/03:00, any 08:00, weekday 00:00/03:00/06:00/09:00/
15:00/21:00. A window releases only when something is `eligible`; an empty selection is a quiet `NO_OP` (no alert, no
message: `ALERT_PRIORITY` has no NO_OP entry, and the host timers do not notify).

**Who owns what.** The repo policy (`config/release_train_policy.json` `windows[].days`) is the schedule. The host
delegation authorizes the slot ids (all nine, every day). A live train needs both, plus `armed: true`, the accepted
delegation digest, an ACTIVE delegation and no STOP. Later schedule changes inside the nine slots are a reviewed policy
PR only; no delegation change.

## What the PR changes

| Gate | Before | After |
|---|---|---|
| `CAPABILITY_BINDING_STATUS` (§K) | `PROPOSED`: train `prepare`/`promote` need a guard `release-write` grant | `ACTIVE`: a `release-train-<id>` campaign is accepted on the signed RESERVED capability; guard ledger not consumed |
| Controller `_cap_effect` | never wrote the reservation token | writes `trains/<id>/capability/{prepare,promote}_release.rcap` (mode 600, live only); removed when the train ends |
| Promote artifact binding (F4) | none | the deploy passes `--release-dir`; the preflight computes the artifact digest; the capability path refuses a promote without it |
| Unreleased commits on main (F2) | not checked | a live train NO_OPs (`BASE_HAS_UNRELEASED_<class>` / `BASE_UNRELEASED_UNKNOWN`) unless CURRENT…main is all `eligible` |
| Policy | `PROPOSED`, unarmed, 4 windows disabled | `ACTIVE`, armed, the schedule above (9 windows with `days`) |
| Controller + claimer (F5) | delegation only | a live train / live request also needs the policy armed and the slot scheduled that day |
| 06:00 drain rule | every 06:00 | weekday 06:00 only (market days) |
| Slot vocabulary | 0000 0600 0800 1800 | + 0300 0900 1200 1500 2100 (delegation, request/receipt/candidate/outcome schemas, relay, CLI) |

The n8n allowlist, lane registry and workflow are unchanged (the workflow is not imported; new n8n lanes need REVIEWED
health contracts, and the disk-standing packet pins those files). The host timers below are what go live.

## Host steps (after the PR is released; in this order)

1. **Delegation (operator, once):** `bash update-delegation-windows.sh` (preview: diff of the windows section only),
   then `--apply` (type `ACK-TRAIN-WINDOWS`; archives the old record; then `release_control_cli.py change-scope`, type
   its phrase). Until this runs, only 18:00 can go live (the controller refuses other slots `REFUSED_OFF_WINDOW`).
2. **Timers and drop-ins:** `bash install.sh` (preview), then `--apply` (type `ACK-TRAIN-SCHEDULE`). It installs:
   - drop-ins removing `--shadow-only` for request@ 1800, 1200, 0000, 0300, 0600, 0900, 1500, 2100 (0800 keeps it);
   - timers request@1200 (daily), request@0300 (Sun), request@0900/1500/2100 (Sat,Sun) and census timers 20 min before.
   The existing daily 0000/0600 timers keep firing; on unscheduled days the request stays shadow.
   Rollback: `bash install.sh --rollback`.
3. Verify at the next window: `release_train_window_request.py --window <slot> --dry-run` at the window time shows
   `shadow: false`, and the receipt in `train_requests/receipts/rtw-<date>-<slot>-win.json` is `mode: live`.

STOP (`release_control_cli.py stop`) and `revoke` keep working at any time.

## Notes

- TTL (review F8): `capability_ttl_s` (delegation, 900 s in the example) must cover the deploy's `prepare` (a full
  build). If prepares run longer than the TTL, raise it in the delegation (max 3600) with the same `change-scope`.
- What still needs the operator: `needs_operator` / `held` / `blocked` changes never ride and must be released by the
  manual path first; while one is merged but unreleased, every train window is a quiet NO_OP (F2).
