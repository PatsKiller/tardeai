# Command Center Replacement Matrix

Initial inventory is intentionally conservative. Existing routes are retained while
the R20-R24 control-plane routes are built and compared. Each row must be updated with
actual route, data source, parity result, and retirement condition before cutover.

| Old route | New route | Disposition | Parity | Retirement condition |
|---|---|---|---|---|
| Existing operational dashboards | `/control-plane/*` | DEFER | UNMEASURED | operator review + audit + rollback proof |

No old route is retired by this program's initial implementation.
