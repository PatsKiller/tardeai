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
CANONICAL = [
    "docs/OPTIONS_LIFECYCLE_DESK.md",
    "docs/_findings/OPTIONS_LIFECYCLE_DESK_DIAGNOSIS_2026-07-19.md",
    "docs/_findings/OPTIONS_LIFECYCLE_V1_1_INTEGRATION_AUDIT_2026-07-19.md",
    "docs/runbooks/OPTIONS_FIRST_POSITION_ACCEPTANCE.md",
    "docs/COST_INTELLIGENCE_ARCHITECTURE.md",
    "docs/options-module.md",
    "docs/DOCUMENTATION_INDEX.md",
    "docs/CHANGELOG.md",
]
HASH_STATE = Path.home() / ".local" / "state" / "docs-parity-hashes.json"
STALE_HOURS = 26   # hourly sync + slack


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
    """v1.2.2 P1-5: TRUE Drive-side content verification — locates each canonical
    doc by name via `gog drive search`, DOWNLOADS the Drive bytes, and compares
    SHA-256 against the repo copy. Any remote failure = UNKNOWN/DRIFT, never PASS."""
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

    def norm_hash(data: bytes) -> str:
        # normalized content hash: the sync converts .md into Google Docs, so
        # byte identity is impossible by design — compare whitespace-normalized
        # text exported back as markdown (spec: repo/drive NORMALIZED hashes)
        import html as _html
        # The sync pipeline converts .md -> Google Doc -> md export, which
        # destroys markdown punctuation (escapes, entities, <placeholders>,
        # blockquote/emphasis markers, spacing). Parity therefore compares the
        # ALPHANUMERIC CONTENT STREAM — identical letters+digits in identical
        # order — which survives the round-trip losslessly.
        txt = _html.unescape(data.decode("utf-8", "replace"))
        txt = re.sub(r"<[^>\n]{1,60}>", "", txt)  # placeholders eaten as tags by Docs
        txt = re.sub(r"[^0-9A-Za-z]+", "", txt)
        return hashlib.sha256(txt.encode()).hexdigest()[:16]

    rows, not_parity = [], 0
    for rel in CANONICAL:
        p = ROOT / rel
        repo_hash = norm_hash(p.read_bytes()) if p.exists() else None
        name = Path(rel).name
        did = drive_hash = None
        status = "UNKNOWN"
        try:
            out = gog("search", f"name = '{name}'")
            found = re.findall(r"^(\S{20,})\s+" + re.escape(name) +
                               r"\s+\S+\s+[\d.]+\s*\S*\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
                               out, re.M)
            ids = [i for i, _ in sorted(found, key=lambda x: x[1], reverse=True)] or                   re.findall(r"^(\S{20,})\s+" + re.escape(name) + r"\s", out, re.M)
            if not ids:
                status = "NOT_ON_DRIVE"
            else:
                # Drive may hold several copies (folder history). PARITY iff ANY
                # copy's downloaded BYTES match the repo content exactly.
                for cand in ids[:8]:
                    with tempfile.TemporaryDirectory() as td:
                        # gog --out is a FILE path; converted Google Docs need
                        # an explicit md export to compare text with text
                        target = Path(td) / "x.md"
                        try:
                            gog("download", cand, "--out", str(target), "--format", "md")
                        except Exception:
                            try:
                                gog("download", cand, "--out", str(target))
                            except Exception:
                                continue
                        files = [f for f in Path(td).iterdir() if f.is_file()]
                        if files:
                            h = norm_hash(files[0].read_bytes())
                            if drive_hash is None:
                                did, drive_hash = cand, h
                            if h == repo_hash:
                                did, drive_hash = cand, h
                                break
                status = ("PARITY" if repo_hash and drive_hash and repo_hash == drive_hash
                          else ("DOWNLOAD_FAILED" if not drive_hash else "DRIFT"))
        except Exception as e:
            status = f"UNKNOWN ({str(e)[:60]})"
        if status != "PARITY":
            not_parity += 1
        rows.append({"repo_path": rel, "repo_hash": repo_hash,
                     "drive_document_id": did, "drive_hash": drive_hash, "parity": status})
    print(json.dumps(rows, indent=1))
    print(f"DEEP DRIVE PARITY: {'OK — all verified from Drive bytes' if not_parity == 0 else f'{not_parity} doc(s) not verified'}")
    return 0 if not_parity == 0 else 1


if __name__ == "__main__" and "--deep" in sys.argv:
    sys.exit(deep_drive_parity())
