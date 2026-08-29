#!/usr/bin/env python3
"""check_docs_drive_parity.py — v1.1 P9: alert when canonical lifecycle docs are
missing or stale in the Drive sync manifest. Piggybacks the hourly
sync-docs-to-drive.sh (gog) manifest — read-only; exit 1 + stderr line on drift
so the health surface can alarm."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path.home() / ".local" / "state" / "drive-sync-manifest.txt"
# sync-docs-to-drive.sh (is_runtime_dump_excluded) never uploads these trees —
# "dead Drive parents / scratch shots". A CANONICAL entry under one of them can
# never appear in the manifest, so it reports DRIFT forever. Two
# docs/_findings/ entries did exactly that from 2026-07-19 until 2026-08-29,
# which also meant a real drift would have been lost in the standing alarm.
SYNC_EXCLUDED_PREFIXES = ("docs/_archive/", "docs/_trash/", "docs/_findings/")

CANONICAL = [
    "docs/OPTIONS_LIFECYCLE_DESK.md",
    "docs/runbooks/OPTIONS_FIRST_POSITION_ACCEPTANCE.md",
    "docs/COST_INTELLIGENCE_ARCHITECTURE.md",
    "docs/options-module.md",
    "docs/architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md",
    "docs/COMMAND_CENTER_V3_WATCHLIST.md",
    "docs/brokers/trading-environments.md",
    "docs/brokers/paper-trading.md",
    "docs/brokers/paca-accounts.md",
    "docs/brokers/ALPACA_DUE_DILIGENCE_AUDIT_2026-07-21.md",
    "docs/DOCUMENTATION_INDEX.md",
    "docs/CHANGELOG.md",
]
HASH_STATE = Path.home() / ".local" / "state" / "docs-parity-hashes.json"
STALE_HOURS = 26   # hourly sync + slack

# Fail fast rather than alarm forever if an unsyncable path is ever added back.
_unsyncable = [d for d in CANONICAL if d.startswith(SYNC_EXCLUDED_PREFIXES)]
if _unsyncable:
    raise SystemExit(
        "check_docs_drive_parity: CANONICAL lists paths sync-docs-to-drive.sh "
        "never uploads, so they can never reach parity: "
        + ", ".join(_unsyncable)
    )


def main() -> int:
    import hashlib, json
    problems = []
    manifest = MANIFEST.read_text() if MANIFEST.exists() else ""
    manifest_mtime = MANIFEST.stat().st_mtime if MANIFEST.exists() else 0
    state = json.loads(HASH_STATE.read_text()) if HASH_STATE.exists() else {}
    for rel in CANONICAL:
        p = ROOT / rel
        if not p.exists():
            problems.append(f"MISSING IN REPO: {rel}")
            continue
        if Path(rel).name not in manifest:
            problems.append(f"NOT IN DRIVE MANIFEST yet: {rel} (next hourly sync should pick it up; "
                            "alarm only if this persists)")
            continue
        # CONTENT parity: hash recorded when the doc was last covered by a sync
        # (manifest newer than the file). A doc changed after the last sync =
        # content drift until the next sync re-covers it.
        cur_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if p.stat().st_mtime <= manifest_mtime:
            state[rel] = {"hash": cur_hash, "synced_hash_at": manifest_mtime}
        else:
            rec = state.get(rel, {})
            if rec.get("hash") != cur_hash:
                problems.append(f"CONTENT DRIFT since last sync: {rel} "
                                f"(local {cur_hash} vs synced {rec.get('hash', 'never')})")
    try:
        HASH_STATE.write_text(json.dumps(state, indent=1))
    except Exception:
        pass
    if MANIFEST.exists():
        age_h = (time.time() - MANIFEST.stat().st_mtime) / 3600
        if age_h > STALE_HOURS:
            problems.append(f"Drive sync manifest {age_h:.0f}h old (> {STALE_HOURS}h) — sync cron may be dead")
    else:
        problems.append("Drive sync manifest absent — sync has never run on this host?")
    if problems:
        print("DOCS↔DRIVE PARITY: DRIFT", file=sys.stderr)
        for x in problems:
            print(" -", x)
        return 1
    print(f"DOCS↔DRIVE PARITY: OK ({len(CANONICAL)} canonical docs tracked)")
    return 0


if __name__ == "__main__" and "--deep" not in sys.argv:
    sys.exit(main())


def deep_drive_parity() -> int:
    """v1.2.3 P0-2: ID-BOUND verification from config/drive_parity_manifest.json.
    Canonical docs are raw .md on Drive → parity = SHA-256(repo bytes) ==
    SHA-256(Drive bytes) (LF/CRLF normalization ONLY if the transport changed
    line endings — documented). No filename discovery; duplicate filenames are
    surfaced as warnings and can never satisfy parity. Remote failure is never
    PASS. States: BYTE_PARITY | SEMANTIC_PARITY | STRUCTURAL_DRIFT |
    CONTENT_DRIFT | DOWNLOAD_FAILED | DUPLICATE_IDENTITY | NOT_ON_DRIVE."""
    import hashlib, json, os, re, subprocess, tempfile
    env = dict(os.environ)
    kp = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
    if kp.exists():
        env["GOG_KEYRING_PASSWORD"] = kp.read_text().strip()

    def gog(*args):
        r = subprocess.run(["gog", "drive", *args, "--account", "john@jwwhiting.com"],
                           capture_output=True, text=True, timeout=180, env=env)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[:150])
        return r.stdout

    manifest = json.loads((ROOT / "config" / "drive_parity_manifest.json").read_text())
    rows, not_ok = [], 0
    for doc in manifest["documents"]:
        rel, fid = doc["repo_path"], doc.get("drive_file_id")
        p = ROOT / rel
        repo_hash = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        status, drive_hash, warn = "NOT_ON_DRIVE", None, None
        if fid:
            try:
                with tempfile.TemporaryDirectory() as td:
                    tgt = Path(td) / "x"
                    gog("download", fid, "--out", str(tgt))
                    files = [f for f in Path(td).iterdir() if f.is_file()]
                    if not files:
                        status = "DOWNLOAD_FAILED"
                    else:
                        data = files[0].read_bytes()
                        drive_hash = hashlib.sha256(data).hexdigest()
                        if drive_hash == repo_hash:
                            status = "BYTE_PARITY"
                        elif hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == \
                                hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest():
                            status = "BYTE_PARITY"   # documented LF/CRLF-only normalization
                        elif doc.get("sync_mode") == "native_gdoc":
                            from drive_semantic_compare import compare
                            status = compare(data.decode("utf-8", "replace"),
                                             p.read_text())
                        else:
                            status = "CONTENT_DRIFT"
            except Exception as e:
                status = f"DOWNLOAD_FAILED ({str(e)[:50]})"
        # duplicate identity check — warning only, never satisfies parity
        try:
            name = Path(rel).name
            out = gog("search", f"name = '{name}'")
            copies = len(re.findall(r"^\S{20,}\s+" + re.escape(name), out, re.M))
            if copies > 1:
                warn = f"DUPLICATE_IDENTITY: {copies - 1} extra Drive cop(ies) with this name"
        except Exception:
            pass
        ok = status in ("BYTE_PARITY", "SEMANTIC_PARITY")
        if not ok:
            not_ok += 1
        rows.append({"repo_path": rel, "drive_file_id": fid, "repo_sha256": repo_hash,
                     "drive_sha256": drive_hash, "parity": status, "warning": warn})
    print(json.dumps(rows, indent=1))
    print(f"DEEP DRIVE PARITY (ID-bound): {'ALL VERIFIED' if not_ok == 0 else f'{not_ok} doc(s) not verified'}")
    return 0 if not_ok == 0 else 1


if __name__ == "__main__" and "--deep" in sys.argv:
    sys.exit(deep_drive_parity())
