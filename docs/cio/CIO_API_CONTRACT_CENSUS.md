# CIO API Contract Census

`scripts/cio_api_contract_census.py` enumerates source-visible API calls from
CIO, Advisory, Agents, Hermes, and Research Intelligence. It records the
consumer, producer route family, source/composition clock fields, evidence
class, serving SHA, and error-behavior status.

The static census deliberately reports runtime response schemas, clocks,
serving-release proof, and dead-call proof as `UNKNOWN` until an exact-release
API capture is available. It must not convert a source fetch into a runtime
claim.

Run:

```bash
python3 scripts/cio_api_contract_census.py --json
```

The report is advisory and has no execution authority.
