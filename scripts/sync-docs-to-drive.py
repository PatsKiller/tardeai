#!/usr/bin/env python3
"""Trade AI docs → Google Drive sync via gog, preserving folder hierarchy."""
import hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

SRC_ROOT = Path('/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild')
# NOTE: the PRODUCTION hourly Drive sync is scripts/sync-docs-to-drive.sh (cron :05) → the same canonical
# Trade_AI_Docs_v2 folder below. This .py is a manual/secondary tool that targets the SAME folder so it can
# never create a duplicate. resolve_root_folder() validates the canonical id first and only falls back to a
# by-name lookup / create if it has truly been removed (self-healing without forking a new folder).
ROOT_FOLDER_NAME = 'Trade_AI_Docs_v2'
ROOT_FOLDER_ID = '1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR'  # canonical, shared with sync-docs-to-drive.sh; re-validated each run
ACCOUNT = 'john@jwwhiting.com'
MANIFEST = Path('/home/johnclaw/.local/state/drive-sync-manifest.json')
FOLDER_CACHE = Path('/home/johnclaw/.local/state/drive-folder-cache.json')
LOG = Path('/home/johnclaw/logs/drive-docs-sync.log')

os.environ['GOG_KEYRING_PASSWORD'] = Path('/home/johnclaw/.openclaw/credentials/gog_keyring_password').read_text().strip()
GOG_BIN = '/home/johnclaw/.local/bin/gog'

SYNC_ROOTS = [(SRC_ROOT / 'docs', 'docs'), (SRC_ROOT / 'config' / 'strategies', 'config-strategies')]
EXTRA_FILES = [(SRC_ROOT / '.env.example', None)]

EXCLUDE = [r'/state/', r'/\.git/', r'__pycache__', r'\.pyc$', r'\.log$', r'\.sql$',
           r'\.tar\.gz$', r'\.tgz$', r'\.zip$', r'\.env[^.]', r'^\.env$', r'/\.env$',
           r'\.key$', r'\.pem$', r'\.token$', r'credentials', r'secret', r'password',
           r'holdings.*\.json$', r'portfolio.*\.json$',
           r'morning_brief', r'/_trash/', r'/_archive/',
           r'docs/[^/]*_20\d{6}_', r'CLAUDE_CODE_',
           r'/hermes/phase3b_dryrun/', r'hermes_auto_.*_payload\.json$',
           r'/hermes/backlog_health/.*\.json$', r'/hermes/.*latest_.*_summary\.json$']
SENSITIVE = [rb'sk-[a-zA-Z0-9]{20,}', rb'AKIA[A-Z0-9]{16}', rb'ghp_[a-zA-Z0-9]{36}',
             rb'[0-9]{8,10}:[a-zA-Z0-9_-]{30,}']

def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line); open(LOG, 'a').write(line + '\n')

def is_excluded(p): return any(re.search(pat, str(p)) for pat in EXCLUDE)
def has_secrets(p):
    try:
        head = open(p, 'rb').read(8192)
        return any(re.search(pat, head) for pat in SENSITIVE)
    except: return True

def file_hash(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''): h.update(chunk)
    return h.hexdigest()

def load_json(p, default):
    try: return json.load(open(p)) if p.exists() else default
    except: return default

def save_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    json.dump(data, open(tmp, 'w'), indent=2)
    os.replace(tmp, p)

def gog(*args):
    r = subprocess.run([GOG_BIN] + list(args) + ['--account', ACCOUNT, '--no-input'],
                       capture_output=True, text=True, timeout=30)
    return r.returncode == 0, r.stdout.strip(), r.stderr.strip()

def gog_mkdir(parent_id, name):
    ok, out, err = gog('drive', 'mkdir', name, '--parent', parent_id, '-j')
    if ok:
        d = json.loads(out)
        return d.get('folder', {}).get('id') or d.get('id', '')
    raise RuntimeError(f"mkdir failed: {err}")

def gog_upload(local_path, parent_id):
    ok, out, err = gog('drive', 'upload', str(local_path), '--parent', parent_id, '-j')
    if not ok:
        raise RuntimeError(f"upload failed: {err[:200]}")
    return True

def gog_ls(parent_id):
    ok, out, _ = gog('drive', 'ls', '--parent', parent_id, '-j')
    if ok and out:
        return json.loads(out).get('files', [])
    return []

def gog_delete(file_id):
    gog('drive', 'delete', file_id, '--force')

def resolve_root_folder():
    """Resolve the canonical sync root folder, preferring the known ROOT_FOLDER_ID (shared with the .sh
    cron) so we never fork a duplicate. Order: (1) validate ROOT_FOLDER_ID is live; (2) fall back to the
    OLDEST by-name match at the Drive root (the canonical one, not a freshly-created dup); (3) only create
    if none exists. Returns the folder id."""
    # 1. Canonical id still alive?
    ok, out, _ = gog('drive', 'get', ROOT_FOLDER_ID, '-j')
    if ok and out:
        try:
            d = json.loads(out)
            if not d.get('trashed') and 'folder' in d.get('mimeType', ''):
                return ROOT_FOLDER_ID
        except Exception:
            pass
    # 2. By-name fallback — pick the earliest-created match so a stray duplicate can't win.
    q = (f"name = '{ROOT_FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
         "and trashed = false and 'root' in parents")
    ok, out, _ = gog('drive', 'search', q, '-j')
    if ok and out:
        try:
            folders = [f for f in json.loads(out).get('files', []) if 'folder' in f.get('mimeType', '')]
            folders.sort(key=lambda f: f.get('createdTime', f.get('modifiedTime', '')))
            if folders:
                return folders[0]['id']
        except Exception:
            pass
    # 3. Nothing exists — create it.
    ok, out, err = gog('drive', 'mkdir', ROOT_FOLDER_NAME, '-j')
    if ok:
        d = json.loads(out)
        return d.get('folder', {}).get('id') or d.get('id', '')
    raise RuntimeError(f"could not resolve or create root folder '{ROOT_FOLDER_NAME}': {err}")


def ensure_folder(parts, cache):
    parent = ROOT_FOLDER_ID
    for part in parts:
        key = f"{parent}/{part}"
        if key in cache:
            parent = cache[key]; continue
        # Check if exists on Drive
        existing = [f for f in gog_ls(parent) if f['name'] == part and 'folder' in f.get('mimeType', '')]
        if existing:
            cache[key] = existing[0]['id']; parent = existing[0]['id']
        else:
            new_id = gog_mkdir(parent, part)
            cache[key] = new_id; parent = new_id
            log(f"mkdir: {'/'.join(parts[:parts.index(part)+1])}")
        save_json(FOLDER_CACHE, cache)
    return parent

def find_existing_file(parent_id, name):
    """Check if file already exists to avoid duplicates."""
    files = gog_ls(parent_id)
    for f in files:
        if f['name'] == name and 'folder' not in f.get('mimeType', ''):
            return f['id']
    return None

def main():
    global ROOT_FOLDER_ID
    log("=== sync start ===")
    ROOT_FOLDER_ID = resolve_root_folder()
    log(f"root folder '{ROOT_FOLDER_NAME}' = {ROOT_FOLDER_ID}")
    manifest = load_json(MANIFEST, {})
    folder_cache = load_json(FOLDER_CACHE, {})

    # If the root folder changed (e.g. the old one was trashed), every cached subfolder id + manifest hash
    # is stale — reset both so we recreate the tree cleanly under the live root.
    if folder_cache.get('__root__') != ROOT_FOLDER_ID:
        log(f"root changed (was {folder_cache.get('__root__')}) — resetting folder cache + manifest")
        folder_cache = {'__root__': ROOT_FOLDER_ID}
        save_json(FOLDER_CACHE, folder_cache)
        manifest = {}
        save_json(MANIFEST, manifest)

    # Collect candidates
    candidates = []
    for local_root, drive_prefix in SYNC_ROOTS:
        if not local_root.exists(): continue
        for p in local_root.rglob('*'):
            if not p.is_file() or is_excluded(p) or has_secrets(p): continue
            rel = p.relative_to(local_root)
            drive_path = f"{drive_prefix}/{rel}"
            candidates.append((p, drive_path))
    for p, sub in EXTRA_FILES:
        if p.exists() and not is_excluded(p) and not has_secrets(p):
            candidates.append((p, p.name if sub is None else f"{sub}/{p.name}"))

    log(f"{len(candidates)} candidates")
    uploaded = unchanged = failed = 0

    for local_path, drive_path in candidates:
        h = file_hash(local_path)
        if manifest.get(drive_path) == h:
            unchanged += 1; continue

        parts = drive_path.split('/')
        folder_parts, filename = parts[:-1], parts[-1]

        try:
            parent_id = ensure_folder(folder_parts, folder_cache) if folder_parts else ROOT_FOLDER_ID
            # Check for existing file to avoid duplicate
            existing_id = find_existing_file(parent_id, filename)
            if existing_id:
                gog_delete(existing_id)  # Remove old version
            gog_upload(local_path, parent_id)
            manifest[drive_path] = h
            save_json(MANIFEST, manifest)
            uploaded += 1
            if uploaded % 50 == 0:
                log(f"progress: {uploaded} uploaded, {unchanged} unchanged")
            time.sleep(0.3)
        except Exception as e:
            failed += 1
            log(f"FAILED {drive_path}: {e}")
            if failed > 20:
                log("Too many failures, stopping early")
                break

    log(f"sync done: {uploaded} uploaded, {unchanged} unchanged, {failed} failed")

    # Upload a manifest summary to Drive root so operator can see sync state from Google
    try:
        folder_cache = load_json(FOLDER_CACHE, {})
        drive_manifest = {
            "last_sync_utc": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
            "files_uploaded_this_run": uploaded,
            "files_unchanged": unchanged,
            "files_failed": failed,
            "total_files_tracked": len(manifest),
            "total_folders": len(folder_cache),
            "source": "ms01-openclaw",
            "sync_script": "scripts/sync-docs-to-drive.py",
            "files": sorted(manifest.keys()),
            "folders": sorted(set('/'.join(k.split('/')[:-1]) for k in manifest.keys() if '/' in k)),
        }
        manifest_path = Path('/tmp/drive-sync-status.json')
        manifest_path.write_text(json.dumps(drive_manifest, indent=2))
        # Delete old manifest on Drive if exists
        existing = find_existing_file(ROOT_FOLDER_ID, 'SYNC_STATUS.json')
        if existing:
            gog_delete(existing)
        gog_upload(manifest_path, ROOT_FOLDER_ID)
        # Rename on Drive isn't straightforward with gog, so upload with correct name
        # Actually gog upload uses the local filename — rename the temp file
        manifest_path2 = Path('/tmp/SYNC_STATUS.json')
        manifest_path2.write_text(json.dumps(drive_manifest, indent=2))
        existing2 = find_existing_file(ROOT_FOLDER_ID, 'SYNC_STATUS.json')
        if not existing2:
            # First upload used wrong name, delete and re-upload with right name
            wrong = find_existing_file(ROOT_FOLDER_ID, 'drive-sync-status.json')
            if wrong:
                gog_delete(wrong)
            gog_upload(manifest_path2, ROOT_FOLDER_ID)
        log("SYNC_STATUS.json uploaded to Drive root")
    except Exception as e:
        log(f"manifest upload failed (non-fatal): {e}")

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
