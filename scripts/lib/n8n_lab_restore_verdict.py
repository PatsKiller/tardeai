#!/usr/bin/env python3
"""Verdict + receipt for scripts/n8n_lab_restore_drill.sh (N8nLabRestoreDrill@v2).

Third-party DR audit finding A (2026-10-15): the drill called a restore OK whenever the public table count
matched live, so pg_restore errors were ignored, an empty workflow_entity passed, and a false verdict still
exited 0. This module is the single place the verdict is decided. It is stdlib-only (the shell runs it with the
system python3) and it never touches a database: the shell collects the facts into a work directory, this reads
them, decides, writes the receipt and returns the exit code.

PASSED needs every check below; anything else is FAILED (exit 1) with the failing checks listed:

  restore_clean         pg_restore exit 0 AND no ``pg_restore: error`` / ``errors ignored on restore`` line
  tables_match_live     restored public table count == live public table count, and > 0
  manifest_present      the dump's manifest (``<dump>.manifest.json``, written by scripts/n8n_lab_backup.sh)
  dump_sha_matches      the dump's sha256 equals the manifest's
  workflows_nonzero     workflow_entity count >= policy min_workflows (1)
  workflows_match       workflow_entity count within the manifest's [before, after] dump-time counts
  credentials_match     credentials_entity count within the manifest's [before, after] counts
  required_ids_present  every policy required_workflow_ids id (the fabric workflows) is in the restore
  manifest_ids_present  every workflow id the manifest recorded is in the restore
  executions_restorable ``select count(*) from execution_entity`` succeeded on the restore
  credential_key_decrypts  one restored credentials_entity row decrypts with the n8n encryption key, checked
                        INSIDE the n8n app container by scripts/lib/n8n_credential_key_probe.js (prints one word:
                        KEY_OK / KEY_BAD / KEY_UNAVAILABLE / NO_CIPHERTEXT; never the key or plaintext).
                        NO_CIPHERTEXT passes only when the manifest recorded zero credentials. Policy key_check:
                        required (default) | off
  drill_db_dropped      the throwaway database was dropped (else the drill leaks a copy of the lab DB)

A missing fact (a query that failed, a file the shell never wrote) fails its check; it is never defaulted to a
passing value. The receipt keeps the v1 fields (``ok``, ``finished``, ``workflows_in_restore``...) so
scripts/lib/n8n_maturity/dims_healing.py keeps reading it, and adds ``state`` (PASSED|FAILED), ``checks`` and
``failures``. scripts/n8n_incident_fanin.py turns ``state: FAILED`` into a P1 incident (source
n8n_lab_restore_drill) that scripts/incident_notifier.py sends at once.

    python3 scripts/lib/n8n_lab_restore_verdict.py --facts DIR --policy config/n8n_lab_restore_drill.json \
        --receipt OUT.json [--manifest DUMP.manifest.json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "N8nLabRestoreDrill@v2"
# Invoked by a shell script, not imported: scripts/n8n_lab_restore_drill.sh runs it as a CLI (platform-maintenance-weekly
# step n8n_lab_restore_drill), and scripts/n8n_incident_fanin.py + scripts/lib/n8n_maturity/dims_healing.py read the
# receipt it writes.
SCHEDULED_ENTRYPOINT = "systemd: tradeai-platform-maintenance-weekly.timer -> n8n_lab_restore_drill.sh -> this CLI"
ERROR_RE = re.compile(r"(pg_restore: error|errors ignored on restore|^ERROR:|FATAL:)", re.IGNORECASE | re.MULTILINE)


def _read(facts: Path, name: str) -> str | None:
    p = facts / name
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _int(facts: Path, name: str) -> int | None:
    """An integer fact, or None when the file is absent, empty, non-numeric, or its ``<name>.rc`` is not 0."""
    rc = _read(facts, f"{name}.rc")
    if rc is not None and rc.strip() not in ("", "0"):
        return None
    raw = _read(facts, name)
    if raw is None:
        return None
    raw = raw.strip()
    return int(raw) if re.fullmatch(r"-?\d+", raw) else None


def _ids(facts: Path, name: str) -> list[str] | None:
    rc = _read(facts, f"{name}.rc")
    if rc is not None and rc.strip() not in ("", "0"):
        return None
    raw = _read(facts, name)
    if raw is None:
        return None
    return sorted({ln.strip() for ln in raw.splitlines() if ln.strip()})


def _range(manifest: dict[str, Any], key: str) -> tuple[int, int] | None:
    before = manifest.get(f"{key}_before")
    after = manifest.get(f"{key}_after")
    vals = [v for v in (before, after) if isinstance(v, int) and not isinstance(v, bool)]
    if not vals:
        v = manifest.get(key)
        vals = [v] if isinstance(v, int) and not isinstance(v, bool) else []
    return (min(vals), max(vals)) if vals else None


def decide(facts: Path, policy: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Pure over its inputs: the checks, failures and state. No I/O beyond reading ``facts``."""
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}

    rc = _int(facts, "restore_rc")
    stderr = _read(facts, "restore_stderr.txt") or ""
    errors = ERROR_RE.findall(stderr)
    m = re.search(r"errors ignored on restore:\s*(\d+)", stderr)
    detail["pg_restore_rc"] = rc
    detail["restore_error_lines"] = len(errors)
    detail["restore_errors_ignored"] = int(m.group(1)) if m else None
    detail["restore_stderr_head"] = [ln for ln in stderr.splitlines() if ln.strip()][:5]
    max_err = int(policy.get("max_restore_errors", 0))
    checks["restore_clean"] = rc == 0 and len(errors) <= max_err

    live = _int(facts, "live_tables")
    restored = _int(facts, "restored_tables")
    detail["live_tables"], detail["restored_tables"] = live, restored
    checks["tables_match_live"] = live is not None and restored is not None and restored == live and restored > 0

    checks["manifest_present"] = isinstance(manifest, dict)
    man = manifest if isinstance(manifest, dict) else {}
    dump_sha = (_read(facts, "dump_sha256") or "").strip() or None
    detail["dump_sha256"] = dump_sha
    checks["dump_sha_matches"] = bool(dump_sha) and dump_sha == man.get("sha256")

    wf = _int(facts, "workflow_count")
    detail["workflows_in_restore"] = wf
    checks["workflows_nonzero"] = wf is not None and wf >= int(policy.get("min_workflows", 1))
    wf_rng = _range(man, "workflow_count")
    detail["manifest_workflow_count"] = list(wf_rng) if wf_rng else None
    checks["workflows_match"] = wf is not None and wf_rng is not None and wf_rng[0] <= wf <= wf_rng[1]

    cred = _int(facts, "credentials_count")
    detail["credentials_in_restore"] = cred
    cred_rng = _range(man, "credentials_count")
    detail["manifest_credentials_count"] = list(cred_rng) if cred_rng else None
    checks["credentials_match"] = cred is not None and cred_rng is not None and cred_rng[0] <= cred <= cred_rng[1]

    ids = _ids(facts, "workflow_ids")
    have = set(ids or [])
    required = [str(x) for x in policy.get("required_workflow_ids") or []]
    missing_required = sorted(set(required) - have) if ids is not None else sorted(required)
    detail["required_workflow_ids_missing"] = missing_required
    checks["required_ids_present"] = ids is not None and not missing_required
    man_ids = man.get("workflow_ids")
    if isinstance(man_ids, list):
        missing_man = sorted({str(x) for x in man_ids} - have) if ids is not None else sorted(str(x) for x in man_ids)
    else:
        missing_man = None
    detail["manifest_workflow_ids_missing"] = missing_man
    checks["manifest_ids_present"] = ids is not None and missing_man is not None and not missing_man

    ex = _int(facts, "execution_count")
    detail["executions_in_restore"] = ex
    checks["executions_restorable"] = ex is not None and ex >= 0

    key_word = ((_read(facts, "key_check") or "").strip().split() or ["NOT_RUN"])[0]
    detail["key_check"] = key_word
    key_mode = str(policy.get("key_check", "required"))
    no_creds = cred == 0 and cred_rng is not None and cred_rng[1] == 0
    if key_mode == "off":
        checks["credential_key_decrypts"] = True
    else:
        checks["credential_key_decrypts"] = key_word == "KEY_OK" or (key_word == "NO_CIPHERTEXT" and no_creds)

    dropped = _int(facts, "drop_rc")
    checks["drill_db_dropped"] = dropped == 0

    failures = sorted(k for k, v in checks.items() if not v)
    return {"checks": checks, "failures": failures, "state": "FAILED" if failures else "PASSED", "detail": detail}


def build_receipt(
    facts: Path, policy: dict[str, Any], manifest: dict[str, Any] | None, now: _dt.datetime | None = None
) -> dict[str, Any]:
    v = decide(facts, policy, manifest)
    d = v["detail"]
    ok = v["state"] == "PASSED"
    return {
        "schema": SCHEMA,
        "started": (_read(facts, "started") or "").strip() or None,
        "finished": (now or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
        "dump": (_read(facts, "dump") or "").strip() or None,
        "drill_db": (_read(facts, "drill_db") or "").strip() or None,
        "aborted_at": (_read(facts, "aborted_at") or "").strip() or None,
        "state": v["state"],
        "ok": ok,
        "failures": v["failures"],
        "checks": v["checks"],
        "pg_restore_rc": d["pg_restore_rc"],
        "restore_error_lines": d["restore_error_lines"],
        "restore_errors_ignored": d["restore_errors_ignored"],
        "restore_stderr_head": d["restore_stderr_head"],
        "live_tables": d["live_tables"],
        "restored_tables": d["restored_tables"],
        "counts_equal": v["checks"]["tables_match_live"],
        "workflows_in_restore": d["workflows_in_restore"],
        "manifest_workflow_count": d["manifest_workflow_count"],
        "credentials_in_restore": d["credentials_in_restore"],
        "manifest_credentials_count": d["manifest_credentials_count"],
        "executions_in_restore": d["executions_in_restore"],
        "key_check": d["key_check"],
        "required_workflow_ids_missing": d["required_workflow_ids_missing"],
        "manifest_workflow_ids_missing": d["manifest_workflow_ids_missing"],
        "dump_sha256": d["dump_sha256"],
        "dropped_drill_db": v["checks"]["drill_db_dropped"],
        "production_postgres_touched": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--facts", required=True, type=Path)
    ap.add_argument("--policy", required=True, type=Path)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--manifest", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        policy = json.loads(a.policy.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"n8n_lab_restore_verdict: policy unreadable: {exc}", file=sys.stderr)
        policy = {"required_workflow_ids": ["<policy unreadable>"]}  # fails required_ids_present, never passes
    manifest = None
    if a.manifest is not None:
        try:
            manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
    receipt = build_receipt(a.facts, policy, manifest)
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.receipt.with_suffix(a.receipt.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    tmp.replace(a.receipt)
    print(
        json.dumps(
            {
                "state": receipt["state"],
                "ok": receipt["ok"],
                "failures": receipt["failures"],
                "live": receipt["live_tables"],
                "restored": receipt["restored_tables"],
                "workflows": receipt["workflows_in_restore"],
                "rc": receipt["pg_restore_rc"],
            }
        )
    )
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
