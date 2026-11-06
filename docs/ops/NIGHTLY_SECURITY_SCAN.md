# Free security scanning that replaces CodeQL

Operator, 2026-11-02: "remove CodeQL completely. Ruff and Gitleaks run on every change... Semgrep and
the package audits run every night and message you if they find anything."

## Per change (fast)

| Tool | Where | What it does |
|---|---|---|
| **ruff** `S` (flake8-bandit) | `scripts/check_ruff_security.py`, driven by `tests/test_security_scans_20261102.py` in CI | Static security rules over `scripts/`, `apps/`, `lib/`. A baseline (`config/ruff_security_baseline.json`, taken 2026-11-02) allows current findings only; a new finding, or one that grows, fails. The baseline can only shrink: `--update-baseline` removes paid debt. |
| **gitleaks** | `.github/workflows/secret-scan.yml` (already) | Credential scanning on every new commit of a PR, pinned and sha256-verified. Unchanged. |

Ruff version: recorded at adoption as **0.16.2** (`.venv/bin/python -m ruff --version`). Tests are
excluded from the S scan on purpose: a test's own `assert` is not a security finding, and a new test
file would otherwise fail on every assertion it contains.

## Nightly

`scripts/nightly_security_scan.py` runs three free tools and messages the operator only about
findings absent from the previous night's receipt:

| Tool | Install | Notes |
|---|---|---|
| **semgrep OSS** | `pipx install semgrep` | rulesets `p/python` and `p/javascript`; version recorded in each receipt |
| **pip-audit** | `pipx install pip-audit` | Python dependency CVEs, JSON output |
| **npm audit** | ships with Node (npm 10.9.8 on this host) | `--omit dev`; JSON output |

Config: `config/nightly_security_scan.json` (argv per tool, install hint, `alert_priority`,
`timeout_s`, receipt path). Nothing is hardcoded in the script and no version is assumed: the receipt
stores whatever `--version` reports. A tool that is not installed is recorded as `tool_missing` with
its install command — never silently skipped.

Receipt: `${TRADEAI_STATE_ROOT:-~/trade-ai-releases/persistent-state}/data/runtime/security_scan/last.json`.
Alert path: the house Telegram chokepoint (`telegram_alert.send_telegram_outcome`, priority from
config) — the same one every other operator page uses. Dedupe is by finding id against the previous
receipt, so a known finding is messaged once.

**Delivery is confirmed, not assumed.** `send_telegram_outcome` returns a structured outcome, and a
finding is settled only when delivery is *confirmed* — `delivered: true` and no `partial_failure`. An
accepted-but-unconfirmed send, a partial chunk failure, or a sender error leaves the ids in the
receipt's `pending_alert_ids`; the next `--apply` retries them alongside any new findings. `--apply`
exits `1` while any pending id remains, so a run that could not deliver is never reported as clean.

**Bounded runs.** A scan uses `timeout_s` from config and, on timeout, kills the whole process group
(descendants included) and records rc `124`; a cleanup that cannot be confirmed is named in the
receipt. Tool `--version` queries are capped at 10 s so a hung tool cannot stall the receipt. A tool
that exits outside `{0, 1}` — including one killed by a signal (negative rc) — is `tool_failed_or_empty_output`,
not a clean scan.

Run it by hand:

    .venv/bin/python scripts/nightly_security_scan.py           # dry run: print, send nothing
    .venv/bin/python scripts/nightly_security_scan.py --apply    # write receipt, alert on new findings

## Schedule

`config/lane_registry.json` row `nightly-security-scan` is **PROPOSED, NOT INSTALLED**. Installing the
timer is operator-only (AGENTS.md §17); the coordinator installs it after this merges.

## Authority

READ_ONLY_ADVISORY. The scanners read code and dependency manifests; they never edit code, install a
package, open a PR or touch a broker, order, stop or secret path.
