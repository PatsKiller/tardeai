#!/usr/bin/env python3
"""S3: render Bitwarden SM secrets → tmpfs env cache (source-of-truth-plus-cache).

- Read token only (ms01-render)
- Atomic write to /run/user/<uid>/tradeai/env (dir 700, file 600)
- Hash manifest for drift (hashes only, never values)
- On Bitwarden failure: keep last-known-good cache; never delete it
- Staleness >6h → Telegram both chat IDs (no secret values in message)
- --now forces immediate render
- After a successful SM render, keys that already exist in disk repo .env are
  dual-written (quoted) so legacy cron that only sources .env stays aligned.
  Bitwarden SM remains source of truth.

Operator (after SM UI edit of FINVIZ_COOKIE etc.):
  python scripts/secrets/render_env.py --now
  python scripts/secret_validators.py FINVIZ_COOKIE
  # validator uses resolve_secret (tmpfs → env → disk); never prints values
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))
from empty_sentinel import decode_empty  # noqa: E402

BWS = os.environ.get("BWS_BIN") or str(Path.home() / ".local" / "bin" / "bws")
READ_TOKEN = Path.home() / ".openclaw" / "credentials" / "bws_read_token"
PROJECT_NAME = "trade-ai-prod"
BWS_SKIP_RE = re.compile(r"^BWS_", re.I)
# bash `source` / `export` only accept [A-Za-z_][A-Za-z0-9_]* — SM keys with
# slashes (e.g. openclaw/providers/...) must not be written into the env file.
SHELL_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
STALE_HOURS = 6

UID = os.getuid()
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{UID}") / "tradeai"
RENDER_PATH = RUNTIME_DIR / "env"
MANIFEST_PATH = RUNTIME_DIR / "env.manifest.json"
STATE_PATH = ROOT / "data" / "runtime" / "sm_render_state.json"
DISK_ENV = ROOT / ".env"


def _token() -> str:
    return READ_TOKEN.read_text().strip()


def _bws(args: list[str], token: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BWS_ACCESS_TOKEN"] = token
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    return subprocess.run([BWS, *args], env=env, capture_output=True, text=True, timeout=120)


def _project_id(token: str) -> str:
    r = _bws(["project", "list", "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"project list failed: {(r.stderr or '')[:160]}")
    for item in json.loads(r.stdout or "[]"):
        if item.get("name") == PROJECT_NAME:
            return str(item["id"])
    raise RuntimeError(f"{PROJECT_NAME} not found")


def _fetch_secrets(token: str) -> dict[str, str]:
    pid = _project_id(token)
    r = _bws(["secret", "list", pid, "--output", "json"], token)
    if r.returncode != 0:
        r = _bws(["secret", "list", "--output", "json"], token)
    if r.returncode != 0:
        raise RuntimeError(f"secret list failed: {(r.stderr or '')[:160]}")
    data = json.loads(r.stdout or "[]")
    out: dict[str, str] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        k = item.get("key")
        if not k or BWS_SKIP_RE.match(str(k)):
            continue
        if item.get("projectId") and str(item.get("projectId")) != pid:
            continue
        v = item.get("value")
        if v is None:
            # fetch full secret
            sid = item.get("id")
            if not sid:
                continue
            g = _bws(["secret", "get", str(sid), "--output", "json"], token)
            if g.returncode == 0:
                try:
                    v = json.loads(g.stdout).get("value")
                except Exception:
                    v = None
        if v is None:
            continue
        # Decode EMPTY_SENTINEL → "" so blank scaffolds render as KEY=
        out[str(k)] = decode_empty(str(v))
    return out


def _shell_exportable(secrets: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Split SM secrets into shell-sourceable keys vs non-shell names (keys only)."""
    ok: dict[str, str] = {}
    skipped: list[str] = []
    for k, v in secrets.items():
        if SHELL_VAR_RE.match(k):
            ok[k] = v
        else:
            skipped.append(k)
    return ok, sorted(skipped)


def _format_env(d: dict[str, str], *, skipped_keys: list[str] | None = None) -> str:
    """Write KEY=value lines that are safe for `set -a; . file; set +a`."""
    lines = [
        "# Bitwarden SM render — shell-sourceable only",
        "# Non-shell SM key names (e.g. openclaw/...) are omitted so bash source works.",
    ]
    if skipped_keys:
        # names only — never values
        lines.append(f"# skipped_nonshell_keys={len(skipped_keys)}: {', '.join(skipped_keys)}")
    for k in sorted(d.keys()):
        if not SHELL_VAR_RE.match(k):
            continue
        v = d[k]
        # empty values allowed in env file
        if v == "":
            lines.append(f"{k}=")
            continue
        # quote if needed (match secrets_admin heuristic)
        if re.search(r"[;() $&|<>!#'\"\\]", v) or " " in v or "\n" in v:
            escaped = v.replace("'", "'\"'\"'")
            lines.append(f"{k}='{escaped}'")
        else:
            lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"


def _hashes(d: dict[str, str]) -> dict[str, str]:
    return {k: hashlib.sha256(v.encode()).hexdigest() for k, v in sorted(d.items())}


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env_render_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        os.chmod(path, mode)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _previous_render_keys() -> list[str]:
    """Shell-exportable key NAMES from the last good render. Never values.

    Read from the manifest when present, else from the rendered cache itself,
    so the guard still works on a host whose manifest was cleared.
    """
    try:
        man = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        keys = man.get("shell_keys")
        if isinstance(keys, list) and keys:
            return [str(k) for k in keys]
    except Exception:
        pass
    try:
        out = []
        for line in RENDER_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k = line.split("=", 1)[0].strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            if k:
                out.append(k)
        return out
    except Exception:
        return []


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_state(st: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2) + "\n")


def _telegram(msg: str) -> None:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        # ensure env for telegram from disk/tmpfs if available
        for p in (RENDER_PATH, DISK_ENV):
            if p.is_file():
                for line in p.read_text().splitlines():
                    if "=" in line and not line.lstrip().startswith("#"):
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
        from telegram_alert import send_telegram
        send_telegram(msg, bypass_router=True)
    except Exception as e:
        print(f"telegram_fail: {e}", file=sys.stderr)


def _age_hours(path: Path) -> float | None:
    if not path.is_file():
        return None
    return (time.time() - path.stat().st_mtime) / 3600.0


def render(*, force: bool = False, force_shrink: bool = False) -> dict:
    result = {
        "ok": False,
        "source": None,
        "n_keys": 0,
        "path": str(RENDER_PATH),
        "stale_hours": _age_hours(RENDER_PATH),
        "error": None,
    }
    st = _load_state()
    try:
        tok = _token()
        secrets = _fetch_secrets(tok)
        tok = ""
        if not secrets:
            raise RuntimeError("SM returned zero secrets")
        shell_secrets, skipped_keys = _shell_exportable(secrets)
        if not shell_secrets:
            raise RuntimeError("SM returned zero shell-exportable secrets")

        # A DELETED secret is not a failed fetch. The zero-secret guards above
        # only catch total loss; a single key removed in the SM UI comes back
        # as a perfectly successful render that is one key short, and the
        # atomic write below would overwrite the cache and take the key with
        # it. The credential then vanishes from every consumer at once, with
        # no error anywhere.
        #
        # Same posture as a transport failure: keep last-known-good and shout.
        # A stale cache costs nothing; a silently missing key takes the system
        # down at the next call site that needs it.
        prev_keys = set(_previous_render_keys())
        now_keys = set(shell_secrets)
        dropped = sorted(prev_keys - now_keys)
        if dropped and not force_shrink:
            _telegram(
                "⚠️ SM render REFUSED: %d key(s) disappeared from Bitwarden "
                "(%s). Last-known-good cache kept. Restore in SM, or re-run "
                "with --allow-key-removal if the deletion is intended."
                % (len(dropped), ", ".join(dropped[:6])))
            raise RuntimeError(
                "SM_KEYS_DISAPPEARED: %s (cache kept; --allow-key-removal to "
                "accept)" % ", ".join(dropped[:8]))
        text = _format_env(shell_secrets, skipped_keys=skipped_keys)
        # Hash all SM keys (incl. nonshell) for drift; values never logged
        hashes = _hashes(secrets)
        _atomic_write(RENDER_PATH, text, 0o600)
        _atomic_write(
            MANIFEST_PATH,
            json.dumps(
                {
                    "rendered_at": datetime.now(timezone.utc).isoformat(),
                    "n_keys": len(shell_secrets),
                    "n_sm_keys": len(secrets),
                    # Names only — the guard above compares these, never values.
                    "shell_keys": sorted(shell_secrets),
                    "skipped_nonshell_keys": skipped_keys,
                    "hashes": hashes,
                    "project": PROJECT_NAME,
                },
                indent=2,
            )
            + "\n",
            0o600,
        )
        # Dual-write keys that already exist on disk .env (legacy cron alignment; no values logged)
        disk_mirrored = 0
        try:
            from resolve_secret import mirror_rendered_keys_to_disk
            disk_mirrored = mirror_rendered_keys_to_disk(
                shell_secrets, disk_env_path=DISK_ENV, project_root=ROOT
            )
        except Exception:
            disk_mirrored = 0
        st.update(
            {
                "last_ok_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "n_keys": len(shell_secrets),
                "n_sm_keys": len(secrets),
                "skipped_nonshell_keys": skipped_keys,
                "render_path": str(RENDER_PATH),
                "disk_mirrored_keys": disk_mirrored,
            }
        )
        _save_state(st)
        result.update(
            ok=True,
            source="bitwarden_sm",
            n_keys=len(shell_secrets),
            n_sm_keys=len(secrets),
            skipped_nonshell=len(skipped_keys),
            stale_hours=0.0,
            disk_mirrored_keys=disk_mirrored,
        )
        print(json.dumps({k: result[k] for k in result}, indent=2))
        return result
    except Exception as e:
        result["error"] = str(e)[:200]
        st["last_error"] = result["error"]
        st["last_error_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(st)
        # last-known-good: never delete cache
        if RENDER_PATH.is_file():
            result["source"] = "last_known_good"
            result["ok"] = True  # serving cache
            age = _age_hours(RENDER_PATH) or 0
            result["stale_hours"] = age
            # count keys without printing values
            try:
                n = sum(
                    1
                    for line in RENDER_PATH.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#") and "=" in line
                )
                result["n_keys"] = n
            except Exception:
                pass
            if age > STALE_HOURS or force:
                _telegram(
                    f"⚠️ SM render STALE/FAIL on MS-01: {result['error'][:120]} "
                    f"(cache age {age:.1f}h, keys={result['n_keys']}). Serving last-known-good. "
                    f"No secrets deleted."
                )
            print(json.dumps(result, indent=2))
            return result
        # no cache — bootstrap to disk .env if present
        if DISK_ENV.is_file():
            result["source"] = "disk_env_fallback"
            result["ok"] = False
            _telegram(
                "⚠️ SM render FAIL and no tmpfs cache — falling back to disk .env on MS-01. "
                f"err={result['error'][:100]}"
            )
            print(json.dumps(result, indent=2))
            return result
        result["ok"] = False
        print(json.dumps(result, indent=2))
        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true", help="force render attempt now")
    ap.add_argument(
        "--allow-key-removal",
        action="store_true",
        help=("accept a render that drops keys present in the last good "
              "render (deliberate SM deletion). Without it, a shrinking key "
              "set is refused and the last-known-good cache is kept."),
    )
    ap.add_argument("--check-stale", action="store_true", help="alert if cache >6h without re-render")
    args = ap.parse_args()
    if args.check_stale:
        age = _age_hours(RENDER_PATH)
        if age is None:
            _telegram("⚠️ SM env cache MISSING on MS-01 (/run/user/.../tradeai/env)")
            print(json.dumps({"ok": False, "error": "missing_cache"}))
            return 1
        if age > STALE_HOURS:
            _telegram(f"⚠️ SM env cache STALE on MS-01: age={age:.1f}h > {STALE_HOURS}h")
            print(json.dumps({"ok": False, "stale_hours": age}))
            return 1
        print(json.dumps({"ok": True, "stale_hours": age}))
        return 0
    r = render(force=args.now, force_shrink=args.allow_key_removal)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
