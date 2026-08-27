# Instrument identity contract

`identity.resolve` input and output contract.

## Input (one of)

```json
{
  "ticker": "BRK.B",
  "exchange": "NYSE",          // optional
  "security_type": "Common Stock", // optional
  "cusip": "...",              // optional
  "isin": "...",               // optional
  "figi": "..."                // optional
}
```

## Output

```json
{
  "identity": {
    "instrument_id": "...",
    "figi": "...",
    "ticker": "...",
    "identity_status": "RESOLVED | AMBIGUOUS | NOT_FOUND | CONFLICT | NOT_CONFIGURED",
    "identity_confidence": 0.9,
    "source_refs": ["openfigi"],
    "as_of": "..."
  }
}
```

## Guarantees

- No guessing: `AMBIGUOUS` is a first-class result.
- `identity_status != RESOLVED` maps to `PARTIAL` / `CONFLICT` at the envelope
  level with an explicit warning.
