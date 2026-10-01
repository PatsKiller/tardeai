# CIO Completeness Measurement

`scripts/cio_completeness_measurement.py` produces
`CIOCompletenessMeasurement@v1`, including:

- produced capabilities;
- operator-visible capabilities;
- `produced_not_surfaced`;
- explicitly named surfaced-but-runtime-unproven items; and
- live, partial, unwired, dark, and unknown critical-edge counts.

The measurement does not manufacture natural-cycle evidence. Runtime-unproven
items remain visibly labelled `SOURCE_ONLY` or `UNKNOWN` in the measurement and
retain their backend state in the operator UI.

Run:

```bash
python3 scripts/cio_completeness_measurement.py --json
```
