# CC runtime harness fixtures

Hermetic fixtures for `scripts/cc_runtime_harness`.

- `positive/` — consistent synthetic envelopes (matching position counts, dated clocks)
- `negative/` — reserved for on-disk negative snapshots (logic also in `negatives.py`)
- `scenarios/` — timezone / session boundary notes
- `route_ledger.json` — produced/committed route + required API contract

Never point the harness at production. Use `--mode hermetic` or supply
`CC_RUNTIME_PREVIEW_BASE_URL` with `CC_RUNTIME_ALLOW_LIVE_READONLY=1` only when
explicitly authorized for read-only preview sweeps.
