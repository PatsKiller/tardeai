# Manifest sidecar — how to check this package is what it says it is

Campaign `trade-ai-maturity-overnight-20260912`.

## Verifying the package

```bash
cd /home/johnclaw/trade-ai-campaigns/trade-ai-maturity-overnight-20260912
sha256sum -c final/MANIFEST.sha256          # every listed file, byte for byte
python3 -m json.tool final/MANIFEST.json    # the machine-readable index
```

Then reopen the archive and recompute every member independently, rather than
trusting the seal:

```bash
tar tzf final/<archive>.tar.gz | head
mkdir -p /tmp/verify && tar xzf final/<archive>.tar.gz -C /tmp/verify
cd /tmp/verify && sha256sum -c MANIFEST.sha256
```

A manifest that only checks itself proves nothing; the point of the member
manifest is that each file inside the archive is hashed separately, so a
resealed archive with one substituted member fails on that member alone.

## What the documents may and may not be used for

- The **scorecard** carries measurements, each against the bar it was compared
  to. Where a bar was not met, the number is the one that missed it.
- **AS-IS** describes only what was observed during the window, with an explicit
  status per claim. `OBSERVED_PRIOR_EPOCH` is never upgraded to
  `OBSERVED_CURRENT` by proximity.
- **MVL counters were measured on the producer plane**, which is 16 days ahead of
  the served plane on the relevant files. They are therefore an upper bound on
  what the served system can show, not the served numbers. Any auditor reading
  them as served figures would be reading them wrong, and the state-root split is
  why the two differ.
- **Nothing in the package awards a maturity level.** Where this lane and a
  validator lane disagree, both positions are recorded with their evidence
  (see `VALIDATION_HANDOFF.json`, `GR-020` vs `GG-018`).

## Provenance of the numbers

Every figure traces to `evidence/LIVE_TRACE_MATRIX_20260912.md`, which names the
file, table or command consulted for each clause. Nothing in the documents was
copied from a prior campaign's package: the previous campaign's counters describe
a closed epoch and carrying them forward would be evidence splicing.

## Known incompleteness, stated rather than omitted

- `known_bad_regression_fixtures` (an MVL clause) was **not located**; it is
  recorded UNVERIFIED, not assumed absent and not assumed met.
- The Sentinel false-positive rate is **not measurable** — 4 FAIL verdicts exist
  with no adjudication path, so only a fail rate can be stated.
- The Drive mirror is **not reconciled** by this lane; Drive memorialization runs
  through the operator's own Google auth and guard exposes no Drive scope.
