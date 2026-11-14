# Slice contracts
One file per slice: `<name>@<major>.md` — status PROPOSED | REVIEWED(reviewer, verdict) | OPERATOR_DECISION(decision, ts).
Required sections: fields/types/nullability/units/ids · metric version/session/horizon/TZ · source vs build clocks, lineage, freshness, expiry, failure · read-only vs mutation + auth · P&L kind (session / unrealized / realized / reconciled period) · producer (writer + n8n workflow) · consumers.
