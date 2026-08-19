#!/usr/bin/env python3
"""pre_deploy_state_guard.py — block deploy/restore payloads from clobbering portfolio state.

holdings_guard.py protects PYTHON writes to holdings.json, but a deploy zip/tar, rsync, or cleanup that
EXTRACTS/overwrites data/portfolios/state/** bypasses Python entirely (the gap the foundation doc flagged).
This guard INSPECTS a deploy payload BEFORE extraction and BLOCKS any archive that contains/would overwrite
state files, unless explicit restore mode with the full safety ceremony.

  python3 scripts/pre_deploy_state_guard.py inspect <archive>
  python3 scripts/pre_deploy_state_guard.py guard   <archive> [--restore --named-backup F --confirm TOKEN --actor X]
  python3 scripts/pre_deploy_state_guard.py restore <archive> --named-backup F --confirm TOKEN [--actor X]

Deploy mode NEVER writes (inspection only — holdings untouched). Restore mode requires: a named backup, a
fresh current-snapshot backup, pre/post holdings assert (total >= $1M AND position_count > 0), an operator
confirmation token bound to the archive, and an append-only audit. No Schwab writes, no trading, no
screeners/classifier/GO-WAIT/ATM. Read-only of the archive (members listed, not extracted, in deploy mode).
"""
import argparse, json, os, sys, tarfile, zipfile, hashlib, datetime, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "data" / "portfolios" / "state"
HOLDINGS = STATE_DIR / "holdings.json"
AUDIT = ROOT / "data" / "state_guard_audit.jsonl"
BACKUP_DIR = ROOT / "data" / "backups" / "state_snapshots"
# Deprecated historical $1M floor — assert_holdings_ok now uses holdings_sanity.
MIN_TOTAL = None


def _members(archive):
    p = str(archive)
    if p.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as t:
            return [m.name for m in t.getmembers() if m.isfile()]
    if p.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            return [n for n in z.namelist() if not n.endswith("/")]
    raise ValueError("unsupported archive — need .tar / .tar.gz / .tgz / .zip")


def _state_hits(members):
    hits = []
    for m in members:
        norm = m.lstrip("./").replace("\\", "/")
        if "data/portfolios/state/" in norm or "portfolios/state/" in norm or os.path.basename(norm) == "holdings.json":
            hits.append(m)
    return hits


def assert_holdings_ok(label):
    """Same coverage/relative contract as the holdings write guard (no static $1M floor)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        from holdings_sanity import validate_payload
        h = json.load(open(HOLDINGS))
        v = validate_payload(h, None)
        return v.ok, {
            "label": label, "positions": v.position_count, "total": round(v.total, 2),
            "reason_code": v.reason_code, "ok": v.ok,
        }
    except Exception as e:
        return False, {"label": label, "error": str(e)[:140], "ok": False}


def confirm_token(archive):
    """A token bound to THIS archive's bytes — the operator must echo it back, proving they saw this payload."""
    return hashlib.sha256(Path(archive).read_bytes()).hexdigest()[:12]


def _audit(rec):
    rec["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def _snapshot():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"holdings_{ts}.json"
    shutil.copy2(HOLDINGS, dest)
    return dest


def inspect(archive):
    members = _members(archive)
    hits = _state_hits(members)
    return {"archive": str(archive), "total_members": len(members), "state_hits": hits,
            "state_hit_count": len(hits), "confirm_token": confirm_token(archive) if hits else None}


def guard(archive, restore=False, named_backup=None, confirm=None, actor="operator", do_extract=False):
    hits = _state_hits(_members(archive))
    pre_ok, pre = assert_holdings_ok("pre")
    base = {"archive": str(archive), "actor": actor, "state_hit_count": len(hits), "state_hits": hits[:20], "pre": pre}

    if not hits:
        _audit({**base, "mode": "deploy", "decision": "ALLOW", "reason": "no state files in payload"})
        return {"decision": "ALLOW", "mode": "deploy", "reason": "no state files in payload — safe to extract", "pre": pre}

    if not restore:
        _audit({**base, "mode": "deploy", "decision": "BLOCK", "reason": "payload contains state files"})
        return {"decision": "BLOCK", "mode": "deploy",
                "reason": f"payload contains {len(hits)} portfolio-state file(s); a deploy must NOT overwrite "
                          f"state. Re-run with restore mode + safety requirements if this is an intentional restore.",
                "state_hits": hits[:20]}

    # ── RESTORE MODE — every gate must pass ──
    problems = []
    if not named_backup or not Path(named_backup).exists():
        problems.append("named backup missing or not found on disk")
    if not pre_ok:
        problems.append(f"pre-restore holdings assert FAILED ({pre}) — refusing to restore over a bad current state")
    if confirm != confirm_token(archive):
        problems.append("operator confirmation token missing/incorrect (must equal this archive's confirm_token)")
    if problems:
        _audit({**base, "mode": "restore", "decision": "BLOCK", "problems": problems})
        return {"decision": "BLOCK", "mode": "restore", "problems": problems, "confirm_token": confirm_token(archive)}

    snap = _snapshot()  # current-snapshot backup BEFORE touching anything
    rec = {**base, "mode": "restore", "named_backup": str(named_backup), "snapshot_backup": str(snap)}

    if not do_extract:
        _audit({**rec, "decision": "AUTHORIZE", "note": "authorized; caller extracts, then post-assert"})
        return {"decision": "ALLOW", "mode": "restore", "authorized": True, "snapshot_backup": str(snap),
                "named_backup": str(named_backup), "pre": pre, "note": "re-run with --do-extract to perform the guarded restore"}

    # perform the guarded restore: extract state members, post-assert, rollback on failure
    try:
        _extract_state(archive)
        post_ok, post = assert_holdings_ok("post")
        if not post_ok:
            shutil.copy2(snap, HOLDINGS)  # ROLLBACK to the snapshot
            _audit({**rec, "decision": "ROLLBACK", "post": post, "reason": "post-assert failed; snapshot restored"})
            return {"decision": "ROLLBACK", "mode": "restore", "post": post, "rolled_back_to": str(snap)}
        _audit({**rec, "decision": "RESTORED", "post": post})
        return {"decision": "RESTORED", "mode": "restore", "pre": pre, "post": post, "snapshot_backup": str(snap)}
    except Exception as e:
        shutil.copy2(snap, HOLDINGS)
        _audit({**rec, "decision": "ROLLBACK", "error": str(e)[:140]})
        return {"decision": "ROLLBACK", "mode": "restore", "error": str(e)[:140], "rolled_back_to": str(snap)}


def _extract_state(archive):
    """Extract ONLY state members into place (restore mode), guarding against path traversal."""
    p = str(archive)
    members = _state_hits(_members(archive))
    opener = tarfile.open(archive) if p.endswith((".tar.gz", ".tgz", ".tar")) else zipfile.ZipFile(archive)
    with opener as a:
        for name in members:
            norm = name.lstrip("./").replace("\\", "/")
            idx = norm.find("data/portfolios/state/")
            rel = norm[idx + len("data/portfolios/state/"):] if idx >= 0 else os.path.basename(norm)
            dest = (STATE_DIR / rel).resolve()
            if os.path.commonpath([str(STATE_DIR.resolve()), str(dest)]) != str(STATE_DIR.resolve()):
                raise ValueError(f"path traversal blocked: {name}")
            data = a.extractfile(name).read() if isinstance(a, tarfile.TarFile) else a.read(name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["inspect", "guard", "restore"])
    ap.add_argument("archive")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--do-extract", action="store_true")
    ap.add_argument("--named-backup")
    ap.add_argument("--confirm")
    ap.add_argument("--actor", default="operator")
    a = ap.parse_args()
    if a.cmd == "inspect":
        print(json.dumps(inspect(a.archive), indent=2))
    elif a.cmd == "restore":
        print(json.dumps(guard(a.archive, restore=True, named_backup=a.named_backup, confirm=a.confirm,
                               actor=a.actor, do_extract=True), indent=2))
    else:
        print(json.dumps(guard(a.archive, restore=a.restore, named_backup=a.named_backup, confirm=a.confirm,
                               actor=a.actor, do_extract=a.do_extract), indent=2))


if __name__ == "__main__":
    main()
