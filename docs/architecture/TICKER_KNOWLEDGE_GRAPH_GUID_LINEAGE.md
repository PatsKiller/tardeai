# Ticker Knowledge Graph GUID Lineage

Status: implemented on `feat/ticker-guid-lineage`  
Authority: `READ_ONLY_ADVISORY`

## Purpose

Hermes research is now projected into a persistent ticker-first graph with
stable identifiers. Every ticker, sector, industry, theme, catalyst, calendar
event, research artifact, and relationship can be traced without relying on a
display symbol or a mutable database row number.

## Identity contract

Identifiers are deterministic UUIDv5 values derived from a namespaced entity
kind and normalized label. Re-ingesting the same source therefore produces the
same identity. Existing `ticker_id` and `artifact_id` fields remain as
compatibility aliases; new consumers should use the explicit `*_guid` fields.

| Object | Field |
| --- | --- |
| ticker | `ticker_guid` |
| issuer | `issuer_guid` |
| sector | `sector_guid` |
| industry/subindustry | `industry_guid`, `subindustry_guid` |
| theme | `theme_guids[]` |
| catalyst | `catalyst_guids[]` |
| calendar event | `calendar_event_guids[]` |
| research item | `research_artifact_guid` |
| graph edge | `relationship_guid`, `relationship_guids[]` |
| execution lineage | `trace_guid` |

Each artifact retains its source URL, source ID, content hash, observed time,
Hermes request/research IDs, and the ticker GUID. Relationship edges preserve
direction, relationship class, and source/target GUIDs.

## Relationship classes

`LINEAR` is ticker/issuer-specific evidence. `LATERAL` covers peers and sector
relationships. `VERTICAL` covers industry and supply-chain relationships.
`MACRO` covers themes and catalysts. `CALENDAR` covers dated events.

Profiles persist relationship edges to their sector, industry, issuer, themes,
and peers. Artifacts persist GUIDs for related tickers, sectors, industries,
themes, catalysts, calendar events, and the edge that attached them.

## Legacy migration

Readers enrich older JSONL rows through `upgrade_record_guids`. To physically
persist the fields in an existing projection, run:

```bash
PYTHONPATH=. python scripts/backfill_ticker_graph_guids.py --root .
PYTHONPATH=. python scripts/backfill_ticker_graph_guids.py --root . --apply
```

`--apply` creates a timestamped `.pre-guid-*.bak` file and atomically replaces
the JSONL projection. The migration preserves existing IDs and historical rows.

## Safety

GUIDs provide lineage and retrieval context only. They do not make memory,
Hermes output, research artifacts, or graph relationships authoritative
financial truth. Broker, position, price, cash, risk, order, stop, and 2FA
systems remain outside this projection.
