# Stop/Trailing/Time-Stop Gap Register

## P0 — Safety / Data Integrity
1. **Stop changes NOT recorded** — APPS $6.54→$6.17 has zero audit trail
2. **unified_stop_supervisor updates stop_loss without logging previous value**
3. **No structural way to detect unapproved stop changes**

## P1 — Operator Actionability
4. **Trailing policy not visible** — operator cannot see current tier, next tier, or R thresholds
5. **Stop proof unverified** — stop_order_id exists but broker verification not yet run
6. **Time-stop overdue positions** — currently 0 (all income/position family), but no auto-alert
7. **TOS_PAPER / no-adapter rows** mixed with Alpaca-managed rows in some views

## P2 — UX / Design
8. **No stop-change history panel** — operator has no visibility into when/why stops changed
9. **Trailing tier thresholds not visible** — need to read Python code to understand policy
10. **Time-stop review separate from stop management** — should be unified

## P3 — Cleanup
11. **Trailing policy hardcoded** — not in config YAML, not operator-editable
12. **Strategy family mapping hardcoded** — duplicated in multiple scripts
