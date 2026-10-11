# Broker env-name read audit — which jobs truly need broker names

Status:      BUILT, NOT ON. Log only; blocks nothing. Turned on by an operator grant (cron header + systemd drop-ins).
as_of:       2026-10-11
Ruling:      operator 2026-10-11 ~10:55 ET — step 1: for one week, LOG which process/module reads each broker env
             name; block nothing; zero behaviour change. Goal: the exact list of jobs that need broker names, so a
             deny-by-default loader can follow (steps 2–3, operator decisions).
Branch:      `n8nmat/broker-env-audit` (on top of `n8nmat/env-bootstrap-narrow`, 5d67d7a42).
Packet:      `~/n8n-maturity-verification/packets/broker-env-audit/` (cron + systemd, dry-run default; plan for steps 2–3).

## What it records

When `TRADEAI_BROKER_ENV_AUDIT=1` is set, `scripts/lib/broker_env_audit.py` swaps the class of the existing
`os.environ` object for a subclass of `os._Environ`. It does not replace the object, so identity, `from os import
environ` aliases, `putenv` and child processes are unchanged. Two places install it:

- `lib/env_bootstrap`, at import and after every `load_env`;
- `db_adapter`, which also covers processes whose `DB_PASSWORD` is already set.

A broker name is whatever `env_bootstrap.is_broker_name` matches:

- prefixes `ALPACA_`, `SCHWAB_`, `MOOMOO_`, `IBKR_`, `SNAPTRADE_`, `TRADING_`, `BROKER_`;
- the infix `_BROKER_`;
- the flag itself is excluded.

A read of a broker name through `[]`, `get`, `in` or `os.getenv` appends one JSON line to
`$TRADEAI_STATE_ROOT/data/runtime/broker_env_audit/<UTC date>.jsonl`. The fields are:

| Field | Content |
|---|---|
| `schema` | `BrokerEnvAudit@v1` |
| `ts`, `host`, `pid`, `ppid` | timestamp, host and process ids |
| `name` | the broker env name read |
| `access` | `getitem`, `get` or `contains`. `bulk` marks a whole-env copy: `dict(os.environ)`, `{**os.environ}`, `.copy()` or `items()` |
| `script` | `argv[0]` |
| `arg1` | `argv[1]`, only when it is a flag or a `.py`/`.sh` path; otherwise `<arg>` |
| `lane` | from env `TRADEAI_LANE`, `TRADEAI_LANE_ID` or `N8N_LANE_ID` |
| `unit` | from `/proc/self/cgroup` |
| `caller` | `module:function:line` of the first frame outside the stdlib |
| `caller_file` | the caller's file |
| `via` | the next frame out |
| `mode` | `audit` |

**No line ever holds a value, its length or its presence.** The record path never touches the value.

The loader's own reads are not recorded. That covers `env_bootstrap`'s `k not in os.environ` while copying.

## Guarantees (tests: `tests/test_broker_env_audit_20261011.py`)

- **Unset is a no-op.** Any value other than `"1"` counts as unset. `os.environ` keeps its stock class and nothing
  is written.
- **The audit never raises.** Recorder failures are swallowed and counted: an unwritable root, a classifier error
  or a frame error. The read returns exactly what it would without the audit.
- **Throttled output.** Each process writes one line per (pid, name, caller), up to 1000 lines. A fast pre-check
  on (pid, name, code, line) keeps hot loops cheap. A forked child logs on its own.
- **Measured cost** (2026-10-11, ms01, Python 3.14):
  - about +110 ns per read of a non-broker name;
  - about 1 µs per repeat read of a broker name after the first line;
  - zero when the flag is unset, because the class is not swapped.

## The report

```
$PY scripts/report_broker_env_audit.py --days 7 --json out.json --md out.md
```

This report is read-only and writes only the paths it is given. It produces four tables:

- **Per lane.** The lane comes from the record's `lane`, else from `lane_registry.lane_state_for_command(script)`,
  else from the systemd unit's registry row, else it is `script:<path>`. Each lane gets a verdict:
  - `needs`: it read a broker name by key;
  - `passthrough_only`: it made bulk copies only.
- **Per module:** where each read happens.
- **Per name:** each name is tagged `credential` or `config`, because the classifier also matches config knobs such
  as `BROKER_PRICE_MAX_AGE_MIN`.
- **Source scan vs runtime.** Literal broker-name reads under `scripts/`, excluding `scripts/archive/` and the broker
  execution subsystem, which is not read. Names that were never observed at runtime are flagged.

## What the week will not see

- Processes that import neither `env_bootstrap` nor `db_adapter`.
- Shell expansions of `$ALPACA_*`.
- Executor children under enforce. The flag is not in `CHILD_ENV_BASE_NAMES`; these children are broker-denied
  anyway.
- Broker-token units, which the packet excludes.
- Long-running services that are not restarted.
- Lanes that did not run in the window.

The source-scan section exists to close part of this gap. The packet's `PLAN_STEPS_2_3.md` gives the full list and
the plan for steps 2 and 3.
