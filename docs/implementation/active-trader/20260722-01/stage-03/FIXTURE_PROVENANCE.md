# Fixture Provenance — Stage 3

File: `tests/fixtures/active_trader_rejections.json` (24 fixtures)

| Class | Count | Meaning |
|---|---|---|
| CAPTURED_REDACTED | **0** | No captured live broker rejection text exists anywhere in the repository at this SHA (verified during Stage 0/2 audits). Nothing claims to be an exact live message. |
| SYNTHETIC | 19 | 9 Schwab + 10 Alpaca — hand-written plausible messages exercising the classifier rules. They are NOT asserted to match real broker wording. |
| SYNTHETIC_FUTURE_ADAPTER | 5 | Moomoo contract-testing fixtures for the Stage 5 adapter that does not exist yet. No SDK/OpenD installed; no credential requested. |

Provenance is a validated field on `RawBrokerEvent` — an unregistered provenance value
is rejected at construction (tested).

## Upgrade path
When Stage 10+ produces real captured rejections (or the existing production journal
surfaces one), each should be redacted, added as CAPTURED_REDACTED with a source
reference, and the corresponding SYNTHETIC fixture retired or demoted. Classifier rules
whose only coverage is SYNTHETIC must not be treated as proven against live broker
behavior — this is why capability proposals carry review expiry and why
ELECTRONIC_ENTRY_ELIGIBILITY remains formally provable only by a real broker rejection
(§16F.4, carried in the Stage 2 capability matrix).
