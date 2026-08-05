# CECO quarantine — final disposition

**Status:** PRESERVED / EXCLUDED  
**Date:** 2026-08-05  
**Policy:** Do not reclassify as authorized COMPLETE.

## Artifacts

| Agent | Path | Disposition |
|-------|------|-------------|
| Maria | `data/runtime/watchlist_intelligence/quarantine/CECO_maria.json` | QUARANTINED |
| CIO | `data/runtime/watchlist_intelligence/quarantine/CECO_cio.json` | QUARANTINED |

## Reason

Paid DeepSeek calls produced reservations and consumption log rows, but **no durable
operator-authorization ledger** (policy + child execution authorization) existed.

`operator_approved=true` inside an artifact is **not** authorization.

Display reason (unchanged):

```text
status=NOT_RUN
reason_code=UNVERIFIED_OPERATOR_AUTHORIZATION
artifact_disposition=QUARANTINED
```

## Future CECO reviews

Only after:

1. Durable recurring policy `watch_intel_maria_cio_mwf_v1` is ACTIVE;
2. A **new** input snapshot / input hash is built;
3. A **new** child `execution_authorization_id` is issued and validated before reservation;
4. Reservation + settlement + full provenance fields are present.

Old quarantine files must not be moved back to `artifacts/` or displayed as COMPLETE.
