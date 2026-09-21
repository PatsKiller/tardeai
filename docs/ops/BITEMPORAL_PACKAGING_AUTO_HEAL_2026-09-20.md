# Bitemporal v2 packaging auto-heal

```
Status: ACTIVE
as_of: 2026-09-20T21:25:00-04:00
Measured at: tradeai-m2-shadow-v2 :55432; init_bitemporal_db.sh skip/apply/skip; pytest packaging heal cases
Canonical repo path: docs/ops/BITEMPORAL_PACKAGING_AUTO_HEAL_2026-09-20.md
Authority: isolated M2 only — production :5432 refused
See also: docs/STAGING_VS_V2_BITEMPORAL_STATUS_REPORT.md; PR #1158 gap
```

## What it fixes

Destructive `sql/r10_m2_isolated_benchmark.sql` rebuilds recreate base tables but strip
`sql/trade-ai-bitemporal-schema-v2.sql` packaging (views `@v1/@v2`,
`save_bitemporal_fact_version`, `trg_block_fact_manipulation`).

## How to run

```bash
export M2_DSN='postgresql://m2:m2shadow@127.0.0.1:55432/m2_shadow'
bash scripts/init_bitemporal_db.sh          # heal if needed
bash scripts/init_bitemporal_db.sh          # second call → HEALTHY skip
```

Python: `scripts.lib.bitemporal_schema_heal.ensure_bitemporal_packaging_v2(conn)`.

## Wired automatically

- `memory_m2_benchmark.apply_schema` / `memory_m2_v2.apply_schema` after r10
- Correctness fixture already uses `apply_bitemporal_schema_v2`; tests assert heal after r10-only rebuild

## Explicitly NOT wired

| surface | why |
|---|---|
| `portfolio-server.service` ExecStartPre | production path; §17 DEFERRED |
| `cio-governed-bridge.service` ExecStartPre | same |
| Default DSN `localhost:5432` | refused — sample prompt DSN was unsafe |

Optional: shadow container entrypoint may call `init_bitemporal_db.sh` with `M2_DSN` on `:55432` only.
