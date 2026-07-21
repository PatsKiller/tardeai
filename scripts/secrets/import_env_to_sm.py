#!/usr/bin/env python3
"""S2: one-time import of live .env keys into Bitwarden Secrets Manager project.

- Names preserved EXACTLY from .env
- SKIP any key matching BWS_* (Rule 1 — tokens never enter SM)
- Empty values + known scaffold blanks (e.g. ALPACA_IRA_*) stored as EMPTY_SENTINEL
  (SM rejects truly empty strings); render decodes back to ""
- Idempotent: skip-if-exists with value-hash compare; never silently overwrite
- Prints counts only — never secret values
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

from empty_sentinel import (  # noqa: E402
    BLANK_SCAFFOLD_KEYS,
    EMPTY_SENTINEL,
    encode_empty,
)

BWS = os.environ.get("BWS_BIN") or str(Path.home() / ".local/bin/bws")
READ_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_read_token"
WRITE_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_write_token"
PROJECT_NAME = "trade-ai-prod"
BWS_SKIP_RE = re.compile(r"^BWS_", re.I)


def _token(path: Path) -> str:
    return path.read_text().strip()


def _bws(args: list[str], token: str, timeout: int = 90) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BWS_ACCESS_TOKEN"] = token
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    return subprocess.run(
        [BWS, *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in line:
            continue
        # keep raw line partition (don't strip key only)
        k, _, v = line.partition("=")
        k = k.strip()
        if not k:
            continue
        v = v.strip().strip("'\"")
        out[k] = v
    return out


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode("utf-8")).hexdigest()


def _project_id(token: str) -> str:
    r = _bws(["project", "list", "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"project list failed: {(r.stderr or r.stdout)[:200]}")
    data = json.loads(r.stdout or "[]")
    for item in data if isinstance(data, list) else []:
        if item.get("name") == PROJECT_NAME:
            return str(item["id"])
    raise RuntimeError(f"project {PROJECT_NAME!r} not found")


def _list_secrets(token: str, project_id: str) -> dict[str, dict]:
    """key name → secret metadata (id, value hash of current SM value)."""
    r = _bws(["secret", "list", project_id, "--output", "json"], token)
    if r.returncode != 0:
        # fallback: list all accessible
        r = _bws(["secret", "list", "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"secret list failed: {(r.stderr or r.stdout)[:200]}")
    data = json.loads(r.stdout or "[]")
    by_key: dict[str, dict] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        k = item.get("key") or item.get("name")
        if not k:
            continue
        # filter to project if present
        if item.get("projectId") and str(item.get("projectId")) != project_id:
            continue
        by_key[str(k)] = item
    return by_key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", type=Path, default=None,
                    help="env file (default: .env then .env.pre-sm-migration)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sync-blanks", action="store_true", default=True,
                    help="store empty/scaffold keys as EMPTY_SENTINEL (default on)")
    ap.add_argument("--no-sync-blanks", action="store_true")
    args = ap.parse_args()
    sync_blanks = args.sync_blanks and not args.no_sync_blanks

    if not WRITE_TOKEN.is_file() or not READ_TOKEN.is_file():
        print("FAIL: bws token files missing", file=sys.stderr)
        return 1
    env_path = args.env
    if env_path is None:
        for cand in (ROOT / ".env", ROOT / ".env.pre-sm-migration"):
            if cand.is_file():
                env_path = cand
                break
    if not env_path or not env_path.is_file():
        print("FAIL: env missing (.env or .env.pre-sm-migration)", file=sys.stderr)
        return 1

    write_tok = _token(WRITE_TOKEN)
    read_tok = _token(READ_TOKEN)
    env_map = _parse_env(env_path)

    # Rule 1: strip BWS_*
    skipped_bws = sorted(k for k in env_map if BWS_SKIP_RE.match(k))
    to_import = {k: v for k, v in env_map.items() if not BWS_SKIP_RE.match(k)}

    # Scaffold blanks (IRA, paper slots, etc.) even if absent from env file
    blank_scaffolds_added = 0
    if sync_blanks:
        for k in BLANK_SCAFFOLD_KEYS:
            if BWS_SKIP_RE.match(k):
                continue
            if k not in to_import:
                to_import[k] = ""
                blank_scaffolds_added += 1

    project_id = _project_id(read_tok)
    existing = _list_secrets(read_tok, project_id)

    created = skipped_exists_same = skipped_exists_diff = failed = 0
    fail_names: list[str] = []
    blanks_synced = 0

    for key in sorted(to_import.keys()):
        raw_val = to_import[key]
        is_blank = raw_val == ""
        if is_blank and not sync_blanks:
            print(f"SKIP_EMPTY {key}")
            continue
        # SM cannot store empty — encode blanks
        val = encode_empty(raw_val)
        if is_blank:
            blanks_synced += 1
        if key in existing:
            # value-hash compare — need SM value
            sm_val = existing[key].get("value")
            if sm_val is None:
                # list may redact? try get by id
                sid = existing[key].get("id")
                if sid:
                    g = _bws(["secret", "get", str(sid), "--output", "json"], read_tok)
                    if g.returncode == 0:
                        try:
                            sm_val = json.loads(g.stdout).get("value")
                        except Exception:
                            sm_val = None
            # Compare using encoded form so empty env matches EMPTY_SENTINEL in SM
            sm_cmp = encode_empty(str(sm_val)) if sm_val is not None else None
            if sm_cmp is not None and _hash(sm_cmp) == _hash(val):
                skipped_exists_same += 1
                continue
            # Allow upgrade: existing SM missing but we now want blank scaffold — only if
            # operator force... keep no silent overwrite of non-empty SM values.
            if sm_val is not None and str(sm_val) not in ("", EMPTY_SENTINEL) and is_blank:
                skipped_exists_diff += 1
                print(f"SKIP_DIFF exists non-empty (not blanking): {key}")
                continue
            if sm_val is not None and str(sm_val) not in ("", EMPTY_SENTINEL) and not is_blank:
                skipped_exists_diff += 1
                print(f"SKIP_DIFF exists (not overwriting): {key}")
                continue
            # SM has empty/sentinel and we have blank — treat as same
            if sm_val is not None and str(sm_val) in ("", EMPTY_SENTINEL) and is_blank:
                skipped_exists_same += 1
                continue
            # unknown SM value — skip to avoid overwrite
            skipped_exists_diff += 1
            print(f"SKIP_EXISTS no-hash: {key}")
            continue

        if args.dry_run:
            created += 1
            continue

        # bws secret create — use "--" so values starting with "-" are not parsed as flags.
        # Rate-limit: Bitwarden SM returns 429 if we create too fast; backoff + retry.
        ok_create = False
        last_err = ""
        for attempt in range(1, 8):
            r = _bws(
                ["secret", "create", "--output", "json", "--", key, val, project_id],
                write_tok,
                timeout=120,
            )
            if r.returncode == 0:
                ok_create = True
                break
            err = (r.stderr or r.stdout or "").replace(val, "[REDACTED]")[:200]
            last_err = err
            if "429" in err or "Too Many" in err or "Slow down" in err:
                wait = min(2 ** attempt, 60)
                print(f"RATE_LIMIT {key} attempt={attempt} sleep={wait}s")
                time.sleep(wait)
                continue
            break
        if not ok_create:
            failed += 1
            fail_names.append(key)
            print(f"FAIL create {key}: {last_err[:160]}")
            continue
        created += 1
        time.sleep(1.2)  # pace under SM rate limit

    # post parity
    existing2 = _list_secrets(read_tok, project_id)
    env_names = set(to_import.keys())
    sm_names = set(existing2.keys())
    missing_in_sm = sorted(env_names - sm_names)
    extra_in_sm = sorted(sm_names - env_names)

    print("=== S2 import report (counts only) ===")
    print(f"env_path={env_path}")
    print(f"env_total_keys={len(env_map)}")
    print(f"skipped_BWS_={len(skipped_bws)} names={skipped_bws}")
    print(f"import_candidates={len(to_import)}")
    print(f"blank_scaffolds_added={blank_scaffolds_added}")
    print(f"blanks_synced={blanks_synced}")
    print(f"created={created}")
    print(f"skip_same_hash={skipped_exists_same}")
    print(f"skip_exists_diff_or_unknown={skipped_exists_diff}")
    print(f"failed={failed} fail_names={fail_names}")
    print(f"sm_secret_count={len(sm_names)}")
    missing = sorted(set(to_import.keys()) - sm_names)
    print(f"missing_in_sm={len(missing)} {missing[:20]}")
    print(f"extra_in_sm={len(extra_in_sm)} (ok if pre-existing)")
    parity = not missing
    print(f"parity_all_candidates_in_sm={parity}")
    print(f"empty_sentinel={EMPTY_SENTINEL}")
    print(f"dry_run={args.dry_run}")
    print(f"project_id_present={bool(project_id)}")

    # Rule 1 post-check SM has no BWS_*
    bws_in_sm = [k for k in sm_names if BWS_SKIP_RE.match(k)]
    print(f"BWS_in_sm={len(bws_in_sm)} (must be 0)")
    if bws_in_sm or failed or missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
