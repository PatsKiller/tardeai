#!/usr/bin/env python3
"""archive_offbox_sync.py — encrypted, incremental off-box copy of the retention archives to Google Drive.

Operator ruling D9 = (a), 2026-10-21: copy the archives off-box to Google Drive over the existing Drive path.
The archives (``<state>/archive/``: archive/db_retention/<table>/*.jsonl.gz with their manifests and
TRIPWIRE.jsonl, archive/db_trim/<stamp>/, archive/file_prune/<id>/, comms_lifecycle/ and the one-off areas) sit on
the same disk as the database. This lane puts a second copy somewhere else. It is a COPIER, not a mover:

* **Never deletes.** The local archive stays authoritative and tripwired (AGENTS.md §0 rule 6). This script opens
  each archive file read-only, hashes it and hands it to gpg; it never unlinks, renames, truncates or rewrites one.
  The only file it removes is its own temporary ciphertext. It never deletes anything on Drive either (no prune:
  retention on Drive is a separate operator decision).
* **Same mechanism as ``scripts/backup_secrets_state.sh``.** ``gog drive`` with the same account and the same
  ``Trade_AI_Backups`` folder id; the gog keyring password and the gpg passphrase are passed by FILE PATH, never
  read into this process or printed: gpg reads ``--passphrase-file`` itself, and gog gets its keyring password from
  a ``bash -c`` wrapper that does ``$(cat <file>)`` in the child. gpg ``--cipher-algo AES256 -c`` (symmetric),
  so a file restores with the backup runbook's command:
  ``gpg --batch --passphrase-file <pass> -d <file>.gpg > <file>``.
* **Incremental.** ``<state>/data/runtime/archive_offbox_manifest.json`` (``ArchiveOffboxManifest@v1``) holds, per
  archive file (path relative to ``<state>/archive``): sha256, size, mtime_ns, uploaded_at, Drive id/name/folder,
  ciphertext size and md5. A file whose size and mtime match its entry is done; a file whose bytes changed (an
  appended TRIPWIRE.jsonl) is uploaded again as a new version under a sha-suffixed name; the previous version is
  kept in ``versions``.
* **Verified.** After each upload the Drive file's metadata is read back (``gog drive get``). Its size must equal
  the local ciphertext size, and its md5Checksum, when Drive reports one, must equal the local ciphertext md5.
  A file that cannot be verified is a failure and is NOT recorded as uploaded. It is retried next run.
* **Bounded and resumable.** ``--max-bytes`` (plaintext bytes, default 1 GiB) and ``--max-files`` per run. Files
  are taken in path order and the run stops at the first that does not fit (except the first file, so a file larger
  than the bound still goes). The rest is ``deferred`` and the next run picks it up. Files modified in the last
  ``--min-age-minutes`` (default 15) are skipped as possibly in flight. Symlinks are skipped, never followed.
* **One failure never stops the rest.** Each failure is recorded as {path, stage, error type} in the receipt
  summary; the exit is 1 when any file failed.
* **Dry run by default.** Lists what it would upload with total bytes and writes nothing: no manifest, no receipt,
  no lock, no temp file, no gog or gpg call, no credential path opened. ``--apply`` uploads.
* **Receipt.** A real run writes ``<state>/data/runtime/archive-offbox-sync_last.json`` (LaneRunReceipt@v2:
  produced_count = files uploaded and verified). Exit code 0 is not the proof; the receipt and the manifest are.

Drive layout: ``Trade_AI_Backups/archive/<area>/<YYYYMM of the file's mtime>/<path within area, '/'->'__'>.gpg``.

Scheduler: proposed systemd user timer, daily 03:30 America/New_York
(``docs/ops/packets/archive-offbox-20261021/``). Host job, not n8n: it uses credentials and egress.

Authority: MBI_BEHAVIOR = 0. No broker, no DB, no send. Egress: encrypted archive blobs to the operator's own Drive
only (AGENTS.md §2A: plaintext never leaves the box).

Usage:
    python3 scripts/archive_offbox_sync.py                      # dry run (default)
    python3 scripts/archive_offbox_sync.py --list               # dry run, every pending path
    python3 scripts/archive_offbox_sync.py --apply              # upload, verify, record
    python3 scripts/archive_offbox_sync.py --apply --max-files 3   # first observed run
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from scripts.lib import lane_last_receipt as lr
    from scripts.lib.atomic_json_store import atomic_write_json
except ImportError:  # scripts/ on sys.path, repo root not
    from lib import lane_last_receipt as lr  # type: ignore[no-redef]
    from lib.atomic_json_store import atomic_write_json  # type: ignore[no-redef]

LANE_ID = "archive-offbox-sync"
MANIFEST_SCHEMA = "ArchiveOffboxManifest@v1"
MANIFEST_NAME = "archive_offbox_manifest.json"

# --- the existing Drive mechanism (scripts/backup_secrets_state.sh; a test pins these to that script) ----------
HOME = Path.home()
DRIVE_ROOT_FOLDER_ID = "1GYbZyM8nTfwuh-h2EsWTxbMpXlEUA6Qi"  # Trade_AI_Backups
DRIVE_ROOT_NAME = "Trade_AI_Backups"
DRIVE_ACCOUNT = "john@jwwhiting.com"
GOG = HOME / ".local" / "bin" / "gog"
PASS_FILE = HOME / ".openclaw" / "credentials" / "env_data_backup.pass"
GOG_KEYRING_PW_FILE = HOME / ".openclaw" / "credentials" / "gog_keyring_password"
GPG_ARGS = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--cipher-algo", "AES256", "-c"]
DRIVE_SUBFOLDER = "archive"
FOLDER_MIME = "application/vnd.google-apps.folder"

DEFAULT_MAX_BYTES = 1 << 30  # 1 GiB of plaintext per run (~0.9 GB backlog today; growth <= ~2 GB/month)
DEFAULT_MAX_FILES = 1500  # ~2 gog calls per file; keeps a run inside the unit timeout
DEFAULT_MIN_AGE_MIN = 15
DEFAULT_LOCK = Path("/tmp/archive_offbox_sync.lock")
SAVE_EVERY = 25
MAX_FAILURES_IN_RECEIPT = 50
CMD_TIMEOUT_S = 900


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_md5(path: Path) -> tuple[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def default_archive_root() -> Path:
    return lr.runtime_dir().parent.parent / "archive"


def default_manifest_path() -> Path:
    return lr.runtime_dir() / MANIFEST_NAME


# --- encryption and upload (real implementations; tests inject fakes) ------------------------------------------


class GpgEncryptor:
    """gpg AES-256 symmetric, passphrase by file (gpg reads it; this process never does)."""

    def __init__(self, pass_file: Path = PASS_FILE) -> None:
        self.pass_file = Path(pass_file)

    def encrypt(self, src: Path, dst: Path) -> None:
        cmd = GPG_ARGS[:-1] + ["--passphrase-file", str(self.pass_file), "-c", "-o", str(dst), str(src)]
        proc = subprocess.run(cmd, capture_output=True, timeout=CMD_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"gpg rc={proc.returncode}")


def _find_key(obj: Any, key: str) -> Any:
    """First value for ``key`` anywhere in a JSON document (gog wraps results in an envelope)."""
    if isinstance(obj, Mapping):
        if key in obj:
            return obj[key]
        for v in obj.values():
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    return None


class GogUploader:
    """``gog drive`` as backup_secrets_state.sh calls it. The keyring password reaches gog through a bash wrapper
    that reads the file in the child (``GOG_KEYRING_PASSWORD="$(cat "$1")"``); it is never in this process,
    an argv, a log or the receipt."""

    def __init__(self, *, gog: Path = GOG, account: str = DRIVE_ACCOUNT, root_folder_id: str = DRIVE_ROOT_FOLDER_ID,
                 keyring_pw_file: Path = GOG_KEYRING_PW_FILE) -> None:
        self.gog, self.account, self.root = Path(gog), account, root_folder_id
        self.keyring_pw_file = Path(keyring_pw_file)

    def _gog(self, *args: str) -> Any:
        wrapper = 'GOG_KEYRING_PASSWORD="$(cat "$1")"; export GOG_KEYRING_PASSWORD; shift; exec "$@"'
        cmd = ["bash", "-c", wrapper, "gog-wrapper", str(self.keyring_pw_file), str(self.gog), "drive", *args,
               "-a", self.account, "-j", "--no-input"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CMD_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"gog drive {args[0]} rc={proc.returncode}")
        try:
            return json.loads(proc.stdout or "null")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gog drive {args[0]} returned non-JSON") from exc

    def ensure_folder(self, parts: list[str], cache: dict[str, str]) -> str:
        parent, walked = self.root, []
        for part in parts:
            walked.append(part)
            key = "/".join(walked)
            if key in cache:
                parent = cache[key]
                continue
            q = f"name = '{part}' and mimeType = '{FOLDER_MIME}' and trashed = false"
            listing = self._gog("ls", "--parent", parent, "--query", q, "--max", "5")
            files = _find_key(listing, "files")
            found = None
            if isinstance(files, list):
                found = next((f.get("id") for f in files if isinstance(f, Mapping) and f.get("name") == part), None)
            if not found:
                found = _find_key(self._gog("mkdir", part, "--parent", parent), "id")
            if not found:
                raise RuntimeError("folder id missing")
            cache[key] = parent = str(found)
        return parent

    def upload(self, local: Path, name: str, parent_id: str) -> dict:
        fid = _find_key(self._gog("upload", str(local), "--parent", parent_id, "--name", name), "id")
        if not fid:
            raise RuntimeError("upload returned no id")
        return {"id": str(fid)}

    def stat(self, file_id: str) -> dict:
        meta = self._gog("get", file_id)
        size = _find_key(meta, "size")
        return {"size": int(size) if size not in (None, "") else None, "md5": _find_key(meta, "md5Checksum")}


# --- planning ---------------------------------------------------------------------------------------------------


def load_manifest(path: Path, archive_root: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("schema") == MANIFEST_SCHEMA:
            doc.setdefault("files", {})
            doc.setdefault("drive_folders", {})
            return doc
        raise ValueError("unexpected manifest schema")
    except FileNotFoundError:
        return {"schema": MANIFEST_SCHEMA, "archive_root": str(archive_root),
                "drive_root": f"{DRIVE_ROOT_NAME}/{DRIVE_SUBFOLDER}", "files": {}, "drive_folders": {}}


def _area(rel: str) -> str:
    return rel.split("/", 1)[0] if "/" in rel else "_root"


def drive_name(rel: str, sha: Optional[str] = None) -> str:
    area = _area(rel)
    inner = rel[len(area) + 1:] if area != "_root" else rel
    base = inner.replace("/", "__")
    return f"{base}.{sha[:12]}.gpg" if sha else f"{base}.gpg"


def scan(archive_root: Path, manifest: dict, *, now: float, min_age_s: float, areas: Optional[Iterable[str]],
         rehash: bool) -> tuple[list[dict], dict[str, int], int]:
    """Pending items in path order, skip counts, and the count already uploaded. Reads only."""
    wanted = set(areas) if areas else None
    pending: list[dict] = []
    skipped: dict[str, int] = {}
    done = 0
    for p in sorted(archive_root.rglob("*")):
        rel = p.relative_to(archive_root).as_posix()
        if wanted is not None and _area(rel) not in wanted:
            continue
        if p.is_symlink() or (p.exists() and not p.is_dir() and not p.is_file()):
            skipped["not_regular_file"] = skipped.get("not_regular_file", 0) + 1
            continue
        if not p.is_file():
            continue
        st = p.stat()
        if now - st.st_mtime < min_age_s:
            skipped["too_new"] = skipped.get("too_new", 0) + 1
            continue
        entry = manifest["files"].get(rel)
        item = {"rel": rel, "path": p, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "area": _area(rel),
                "reason": "new", "sha256": None, "md5": None}
        if entry:
            if not rehash and entry.get("size") == st.st_size and entry.get("mtime_ns") == st.st_mtime_ns:
                done += 1
                continue
            sha, md5 = _sha256_md5(p)
            if sha == entry.get("sha256"):
                done += 1
                item["touch_only"] = True  # bytes unchanged, mtime moved: refresh the entry, no upload
                item["sha256"], item["md5"] = sha, md5
                pending.append(item)
                continue
            item.update(reason="changed", sha256=sha, md5=md5)
        pending.append(item)
    return pending, skipped, done


def select(pending: list[dict], *, max_bytes: int, max_files: int) -> tuple[list[dict], list[dict]]:
    """Bounded batch in order; stop at the first that does not fit (the first file always fits)."""
    chosen: list[dict] = []
    used = 0
    uploads = [i for i in pending if not i.get("touch_only")]
    for n, item in enumerate(uploads):
        if chosen and (used + item["size"] > max_bytes or len(chosen) >= max_files):
            return chosen, uploads[n:]
        chosen.append(item)
        used += item["size"]
    return chosen, []


# --- run --------------------------------------------------------------------------------------------------------


def _by_area(items: list[dict]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for i in items:
        a = out.setdefault(i["area"], {"files": 0, "bytes": 0})
        a["files"] += 1
        a["bytes"] += i["size"]
    return dict(sorted(out.items()))


def _gib(n: int) -> str:
    return f"{n / (1 << 30):.3f} GiB"


def _upload_one(item: dict, manifest: dict, uploader: Any, encryptor: Any, tmp_dir: Path) -> dict:
    """Encrypt, upload, verify one file. Returns the manifest entry. Raises _StageError on any failure."""
    src: Path = item["path"]
    stage = "hash"
    enc: Optional[Path] = None
    try:
        if not item.get("sha256"):
            item["sha256"], item["md5"] = _sha256_md5(src)
        stage = "encrypt"
        fd, enc_name = tempfile.mkstemp(prefix="offbox-", suffix=".gpg", dir=str(tmp_dir))
        os.close(fd)
        enc = Path(enc_name)
        encryptor.encrypt(src, enc)
        st = src.stat()
        if (st.st_size, st.st_mtime_ns) != (item["size"], item["mtime_ns"]):
            stage = "changed_during_upload"
            raise RuntimeError("source changed while encrypting")
        enc_size = enc.stat().st_size
        _, enc_md5 = _sha256_md5(enc)
        stage = "folder"
        yyyymm = datetime.fromtimestamp(item["mtime_ns"] / 1e9, tz=timezone.utc).strftime("%Y%m")
        parts = [DRIVE_SUBFOLDER, item["area"], yyyymm]
        folder_id = uploader.ensure_folder(parts, manifest["drive_folders"])
        stage = "upload"
        prev = manifest["files"].get(item["rel"])
        name = drive_name(item["rel"], item["sha256"] if prev else None)
        res = uploader.upload(enc, name, folder_id)
        file_id = str(res["id"])
        stage = "verify"
        remote = uploader.stat(file_id)
        r_size, r_md5 = remote.get("size"), remote.get("md5")
        if r_size is None and not r_md5:
            raise RuntimeError("Drive reported neither size nor md5")
        if r_size is not None and int(r_size) != enc_size:
            raise RuntimeError("size mismatch")
        if r_md5 and str(r_md5) != enc_md5:
            raise RuntimeError("md5 mismatch")
        entry = {
            "path": item["rel"], "sha256": item["sha256"], "size": item["size"], "mtime_ns": item["mtime_ns"],
            "uploaded_at": _now_iso(), "drive_file_id": file_id, "drive_name": name,
            "drive_folder": "/".join([DRIVE_ROOT_NAME, *parts]), "enc_size": enc_size, "enc_md5": enc_md5,
            "verified": True, "verified_by": "size+md5" if (r_size is not None and r_md5) else
            ("size" if r_size is not None else "md5"),
            "versions": [],
        }
        if prev:
            history = list(prev.get("versions") or [])
            history.append({k: v for k, v in prev.items() if k != "versions"})
            entry["versions"] = history
        return entry
    except Exception as exc:  # noqa: BLE001 -- one file's failure is recorded, the run continues
        raise _StageError(stage, type(exc).__name__) from exc
    finally:
        if enc is not None:
            enc.unlink(missing_ok=True)  # our own temporary ciphertext, never an archive file


class _StageError(Exception):
    def __init__(self, stage: str, error: str) -> None:
        super().__init__(stage)
        self.stage, self.error = stage, error


def run(*, archive_root: Path, manifest_path: Path, apply: bool, uploader: Any = None, encryptor: Any = None,
        max_bytes: int = DEFAULT_MAX_BYTES, max_files: int = DEFAULT_MAX_FILES,
        min_age_s: float = DEFAULT_MIN_AGE_MIN * 60, areas: Optional[list[str]] = None,
        receipt_path: Optional[Path] = None, tmp_dir: Optional[Path] = None, rehash: bool = False,
        list_all: bool = False, now: Optional[float] = None, out: Callable[[str], Any] = print) -> dict:
    started = _now_iso()
    archive_root = Path(archive_root)
    if not archive_root.is_dir():
        out(f"[{LANE_ID}] archive root missing: {archive_root}")
        return {"exit": 2, "mode": "apply" if apply else "dry_run", "error": "archive_root_missing"}
    manifest = load_manifest(Path(manifest_path), archive_root)
    pending, skipped, done = scan(archive_root, manifest, now=time.time() if now is None else now,
                                  min_age_s=min_age_s, areas=areas, rehash=rehash)
    uploads = [i for i in pending if not i.get("touch_only")]
    chosen, deferred = select(pending, max_bytes=max_bytes, max_files=max_files)
    res: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "archive_root": str(archive_root),
        "manifest": str(manifest_path),
        "drive_root": f"{DRIVE_ROOT_NAME}/{DRIVE_SUBFOLDER}",
        "already_uploaded_files": done,
        "pending_files": len(uploads),
        "pending_bytes": sum(i["size"] for i in uploads),
        "pending_new": sum(1 for i in uploads if i["reason"] == "new"),
        "pending_changed": sum(1 for i in uploads if i["reason"] == "changed"),
        "by_area": _by_area(uploads),
        "would_upload_files": len(chosen),
        "would_upload_bytes": sum(i["size"] for i in chosen),
        "deferred_files": len(deferred),
        "skipped_reasons": dict(sorted(skipped.items())),
        "max_bytes": max_bytes,
        "max_files": max_files,
    }

    if not apply:
        out(f"[{LANE_ID}] DRY RUN — nothing uploaded, nothing written. archive={archive_root}")
        out(f"[{LANE_ID}] already uploaded: {done} file(s); pending: {res['pending_files']} file(s), "
            f"{res['pending_bytes']} bytes ({_gib(res['pending_bytes'])}); new {res['pending_new']}, "
            f"changed {res['pending_changed']}")
        for area, v in res["by_area"].items():
            out(f"[{LANE_ID}]   {area:<36} {v['files']:>6} file(s) {v['bytes']:>14} bytes")
        out(f"[{LANE_ID}] would upload this run (bound {max_bytes} bytes / {max_files} files): "
            f"{res['would_upload_files']} file(s), {res['would_upload_bytes']} bytes "
            f"({_gib(res['would_upload_bytes'])}); deferred to later runs: {res['deferred_files']}")
        if skipped:
            out(f"[{LANE_ID}] skipped: {res['skipped_reasons']}")
        shown = chosen if list_all else chosen[:10]
        for i in shown:
            yyyymm = datetime.fromtimestamp(i["mtime_ns"] / 1e9, tz=timezone.utc).strftime("%Y%m")
            out(f"[{LANE_ID}]   would upload {i['rel']} ({i['size']} B, {i['reason']}) -> "
                f"{DRIVE_ROOT_NAME}/{DRIVE_SUBFOLDER}/{i['area']}/{yyyymm}/{drive_name(i['rel'])}")
        if len(chosen) > len(shown):
            out(f"[{LANE_ID}]   ... {len(chosen) - len(shown)} more (use --list)")
        res["exit"] = 0
        return res

    assert uploader is not None and encryptor is not None, "apply needs an uploader and an encryptor"
    tmp = Path(tmp_dir) if tmp_dir else Path(tempfile.gettempdir())
    tmp.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    uploaded: list[str] = []
    uploaded_bytes = 0

    def _save() -> None:
        manifest["updated_at"] = _now_iso()
        atomic_write_json(Path(manifest_path), manifest, indent=1)

    for item in pending:  # bytes unchanged, mtime moved: refresh the stored mtime so it is not re-hashed nightly
        if item.get("touch_only"):
            manifest["files"][item["rel"]]["mtime_ns"] = item["mtime_ns"]
    try:
        for n, item in enumerate(chosen, 1):
            try:
                manifest["files"][item["rel"]] = _upload_one(item, manifest, uploader, encryptor, tmp)
                uploaded.append(item["rel"])
                uploaded_bytes += item["size"]
            except _StageError as exc:
                failures.append({"path": item["rel"], "stage": exc.stage, "error": exc.error})
                out(f"[{LANE_ID}] FAILED {item['rel']} at {exc.stage}: {exc.error}")
            if n % SAVE_EVERY == 0:
                _save()
    finally:  # a unit timeout (SIGTERM -> SystemExit in main) still records what was verified
        _save()

    res.update({
        "uploaded_files": len(uploaded),
        "uploaded_bytes": uploaded_bytes,
        "failures": failures,
        "pending_after": len(uploads) - len(uploaded),
        "exit": 1 if failures else 0,
    })
    out(f"[{LANE_ID}] uploaded+verified {len(uploaded)} file(s), {uploaded_bytes} bytes; failed {len(failures)}; "
        f"deferred {len(deferred)}; manifest {manifest_path}")
    summary = {k: res[k] for k in ("uploaded_files", "uploaded_bytes", "pending_files", "pending_bytes",
                                   "pending_after", "deferred_files", "already_uploaded_files", "drive_root")}
    summary["failed_files"] = len(failures)
    summary["failures"] = failures[:MAX_FAILURES_IN_RECEIPT]
    skip_reasons = dict(skipped)
    if deferred:
        skip_reasons["deferred_by_bound"] = len(deferred)
    if failures:
        skip_reasons["failed"] = len(failures)
    lr.write_lane_receipt(
        LANE_ID, ok=not failures, exit_code=res["exit"], started_at=started, script="scripts/archive_offbox_sync.py",
        summary=summary, path=receipt_path, produced_count=len(uploaded), attempted_count=len(chosen),
        skipped_reasons=skip_reasons,
        output_evidence=[{"manifest": str(manifest_path), "uploaded_bytes": uploaded_bytes,
                          "drive_root": res["drive_root"]}],
        empty_reason=None if uploaded else ("nothing_pending" if not chosen else "all_failed"),
    )
    return res


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true", help="upload (default: dry run, writes nothing)")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="plaintext bytes per run")
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    ap.add_argument("--min-age-minutes", type=float, default=DEFAULT_MIN_AGE_MIN,
                    help="skip files modified more recently (possibly still being written)")
    ap.add_argument("--area", action="append", default=None, help="limit to an archive area (repeatable)")
    ap.add_argument("--rehash", action="store_true", help="re-hash files already recorded, not only changed ones")
    ap.add_argument("--list", action="store_true", help="dry run: print every path it would upload")
    ap.add_argument("--archive-root", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--tmp-dir", type=Path, default=None, help="where the temporary ciphertext is written")
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    return ap


def _on_sigterm(signum: int, frame: Any) -> None:
    raise SystemExit(143)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    archive_root = args.archive_root or default_archive_root()
    manifest_path = args.manifest or default_manifest_path()
    common = dict(archive_root=archive_root, manifest_path=manifest_path, max_bytes=args.max_bytes,
                  max_files=args.max_files, min_age_s=args.min_age_minutes * 60, areas=args.area,
                  rehash=args.rehash, tmp_dir=args.tmp_dir, list_all=args.list)
    if not args.apply:
        res = run(apply=False, **common)
        lr.dry_run_report(LANE_ID, {k: v for k, v in res.items() if k != "by_area"},
                          would_write=[str(manifest_path)])
        return int(res.get("exit", 0))
    for need, what in ((GOG, "gog"), (PASS_FILE, "gpg passphrase file"), (GOG_KEYRING_PW_FILE, "gog keyring file")):
        if not Path(need).exists():  # existence only; the contents are never read here
            print(f"[{LANE_ID}] FATAL: {what} missing: {need}", file=sys.stderr)
            return 2
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with open(args.lock, "w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{LANE_ID}] another run holds {args.lock}; exiting", file=sys.stderr)
            return 0
        signal.signal(signal.SIGTERM, _on_sigterm)
        res = run(apply=True, uploader=GogUploader(), encryptor=GpgEncryptor(), **common)
    return int(res.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
