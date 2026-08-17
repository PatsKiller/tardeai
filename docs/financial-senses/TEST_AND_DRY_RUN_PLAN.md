# Test and dry-run plan

## Unit / contract / failure / security (offline)

```bash
python3 -m pytest tests/financial_senses/ -q
```

243 tests, all offline (SEC/FRED/OpenFIGI/LLM mocked, live DB + network blocked
by `tests/financial_senses/conftest.py`).

Coverage:

- **Provider contract** — schema, provenance required, authority fixed,
  malformed response rejected, timeout → `UNAVAILABLE`, `NOT_CONFIGURED`.
- **SEC** — resolve/recent/form4/13f/company facts/metadata/diff/decision
  evidence; 429/timeout/malformed/DB-down adversarial.
- **Filing diff** — change computation, sign flip, unit mismatch, unmapped tags.
- **Macro** — vintage protection, revision delta, `NOT_CONFIGURED`, malformed.
- **Identity** — GOOG/GOOGL, BRK.B/BRK-B, ADR, ambiguity, unknown, conflict.
- **Stress** — all-cash, single equity, mixed, partial coverage, shorts,
  no-double-count, unsourced beta unmodeled.
- **Factor** — holdings overlap, correlation, sector overlap, factor similarity,
  insufficient history.
- **Evidence graph** — fact provenance, claim support, contradiction, stale,
  cycle, duplicate.
- **Critic** — golden cases, shadow flags.
- **Security** — read-only surface, no arbitrary URL/shell/write, no
  inference-as-fact.

## Existing SEC regression

`tests/test_sec_form4_momentum_context.py` — 17/17 pass, unchanged.

## Live read-only smoke (opt-in)

`FINANCIAL_SENSES_LIVE_READ_TEST=1` (only with safe credentials/network). GET
public read-only data only; no DB writes, no Telegram, no service restarts.
Not run in this branch (no credentials required to prove contracts).

## Dry financial-advisory replay

Deterministic replay over fixture data (no live Telegram, no production state).
See `IMPLEMENTATION_LOG.md` for replay evidence.
