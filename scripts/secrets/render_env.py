#!/usr/bin/env python3
"""S3: render Bitwarden SM secrets → tmpfs env cache (source-of-truth-plus-cache).

- Read token only (ms01-render)
- Atomic write to /run/user/<uid>/tradeai/env (dir 700, file 600)
- Hash manifest for drift (hashes only, never values)
- On Bitwarden failure: keep last-known-good cache; never delete it
- Staleness >6h → Telegram both chat IDs (no secret values in message)
- --now forces immediate render
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


def _format_env(d: dict[str, str]) -> str:
    lines = []
    for k in sorted(d.keys()):
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


def render(*, force: bool = False) -> dict:
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
        text = _format_env(secrets)
        hashes = _hashes(secrets)
        _atomic_write(RENDER_PATH, text, 0o600)
        _atomic_write(
            MANIFEST_PATH,
            json.dumps(
                {
                    "rendered_at": datetime.now(timezone.utc).isoformat(),
                    "n_keys": len(secrets),
                    "hashes": hashes,
                    "project": PROJECT_NAME,
                },
                indent=2,
            )
            + "\n",
            0o600,
        )
        st.update(
            {
                "last_ok_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "n_keys": len(secrets),
                "render_path": str(RENDER_PATH),
            }
        )
        _save_state(st)
        result.update(ok=True, source="bitwarden_sm", n_keys=len(secrets), stale_hours=0.0)
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
    r = render(force=args.now)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
