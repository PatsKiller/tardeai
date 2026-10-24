# Actual-capture registry review packet

Status: PROPOSED — review artifacts; no operative application
as_of: 2026-10-24T04:53:19Z
Design-Task: DSN-20261024-registry-reconcile-P2-T1

See [the report](../../REGISTRY_CAPTURE_REVIEW_20261024.md) for the13-ID/177-leaf explanation, authority contradictions and separated dispositions.

- `manifest.json`: source0764, delivery base68994, operator capture SHA/provenance, historical units provenance, candidate/file digests and dispositions.
- `semantic-fields.json` / `.csv`: every before/after JSON leaf with presence, cause, captured line/hash and disposition.
- `restriction-only.PROPOSED.patch`:14+/4-; two RETIRED catalyst lanes gain existing alpaca broker-word markers; requires review; no state/schedule/dispatch change.
- `provenance-only.HELD.patch`:1+/1-; current-schedule F:L213 correction; held because committed-Oct09 replay restoresL199.
- `mechanical.REJECTED.patch`:77+/103-; generated defaults lose reviewed metadata and wrapper-based IDs lose explicit no-output evidence. Never mechanically apply.
- `base-registry-0764.json.gz`: deterministic compressed copy of committed registry0764 only, for isolated fixture review; decompressed bytes bound to source hash.
- `review_packet.py`: offline byte previews with strict hashes/context/field whitelist; no host or write API. `preview("mechanical")` refuses.
- `local-validation.json`: initial frozen-input structural/fixed-point observations; the parent concurrently changed its own operative file, which this audit did not write.
- `verification.json` / `focused-tests.txt` / ratchet receipts: final checks for this independent packet.

Raw private cron commands are excluded. The operator capture hash was verified before analysis; selected captured line hashes preserve references without publishing the full runtime file. Unit data is explicitly historicalOct09, not a current-unit census.

For review only, from the repository root:

```bash
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  -m pytest -q tests/test_registry_capture_review_packet_20261024.py \
  tests/test_n8n_maturity_registry_reconcile_20261009.py \
  tests/test_ci_gates_registry_20261021.py
```

No apply command is provided for an operative registry. Test outputs write only to fixture-owned temporary paths. A preview result does not authorize a lifecycle or scheduler decision. The parent holds the shared registry claim through WP37, and a separate-branch claim was refused; this packet does not circumvent that refusal. Historical audit6dd/PR2063 is unchanged.
