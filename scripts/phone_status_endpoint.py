#!/usr/bin/env python3
"""Read-only phone status endpoint, reachable only over Tailscale (docs/ops/PHONE_OPS_20261009.md).

GET /phone/status returns one small JSON summary (<= 2 KB) built only from receipts and ledgers that
other jobs already write. It fetches nothing, calls no gateway, runs no command, approves nothing.

Why a separate unit and not a route on scripts/n8n_run_relay.py: the relay's guard_bind admits only
loopback and the docker bridge gateway (172.16-31.x.1). Widening it to the tailnet would widen the
one listener n8n may reach. This endpoint has its own guard_bind that admits ONLY this host's
Tailscale IPv4 (100.64.0.0/10, and equal to `tailscale ip -4`), never 0.0.0.0, never loopback.

Auth (every request): headers X-Phone-Ts (unix seconds), X-Phone-Nonce, X-Phone-Sig and optional
X-Phone-Alg over the canonical message "<ts>\n<nonce>\nGET\n<path>":
  * hmac-sha256 (default): hex HMAC-SHA256(key, message)  -- curl/openssl, Scriptable, a laptop
  * sha256-envelope: hex SHA-256(key + "\n" + message + "\n" + key) -- Apple Shortcuts has a native
    "Generate Hash" action but no HMAC; the envelope is what a Shortcut can compute. The message is
    fixed-format and re-derived server-side, so a length-extension forgery cannot produce a valid one.
Key: TRADEAI_PHONE_STATUS_HMAC_KEY (Bitwarden SM -> render_env -> %t/tradeai/env), with
TRADEAI_PHONE_STATUS_HMAC_KEY_PREVIOUS accepted during rotation. +-60 s window, single-use nonce,
per-client and global rate limits, peer must be a tailnet address.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_coordination_projection import ledger_path, project_runs  # noqa: E402
from scripts.n8n_coordination_gateway import BLOCKED_PORTS  # noqa: E402

NO_CONSUMER_REASON = (
    "Entrypoint of config/systemd/user/tradeai-phone-status.service; installed by the operator only "
    "under a config-write grant. The operator's iPhone Shortcut is the consumer."
)

SCHEMA = "PhoneStatus@v1"
KEY_ENV = "TRADEAI_PHONE_STATUS_HMAC_KEY"
KEY_PREVIOUS_ENV = "TRADEAI_PHONE_STATUS_HMAC_KEY_PREVIOUS"
STATUS_PATH = "/phone/status"
DEFAULT_PORT = 18093
MIN_KEY_BYTES = 32
MAX_PAYLOAD = 2048
WINDOW_S = 60
NONCE_CAP = 4096
PER_CLIENT_PER_MIN = 20
GLOBAL_PER_MIN = 60
CACHE_S = 20
WATCHDOG_STALE_S = 900
MAX_LANES = 8
TAILNET = ipaddress.ip_network("100.64.0.0/10")
ALGS = ("hmac-sha256", "sha256-envelope")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TS_RE = re.compile(r"^[0-9]{9,11}$")
_SIG_RE = re.compile(r"^[0-9a-f]{64}$")
REFUSALS = frozenset(
    {
        "phone_bad_path",
        "phone_bad_method",
        "phone_bad_peer",
        "phone_rate_limited",
        "phone_bad_auth",
        "phone_stale_ts",
        "phone_replay",
        "phone_nonce_cache_full",
        "phone_missing_secret",
        "phone_bad_bind",
        "phone_payload_too_large",
    }
)


# ---------------------------------------------------------------------------------------------- bind


def tailscale_ipv4(run: Callable[..., Any] = subprocess.run) -> str | None:
    """This host's Tailscale IPv4 from `tailscale ip -4`, or None. Never raises."""
    try:
        proc = run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    lines = [x.strip() for x in str(proc.stdout or "").splitlines() if x.strip()]
    return lines[0] if lines else None


def guard_bind(host: str, port: int, tailscale_ip: str | None) -> None:
    """Refuse any bind that is not exactly this host's Tailscale IPv4 on an unprivileged, unblocked port."""
    if port < 1024 or port > 65535 or port in BLOCKED_PORTS:
        raise ValueError("phone_bad_bind")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("phone_bad_bind") from exc
    if addr.version != 4 or addr not in TAILNET:
        raise ValueError("phone_bad_bind")
    if not tailscale_ip or str(addr) != tailscale_ip.strip():
        raise ValueError("phone_bad_bind")


def resolve_host(host: str, tailscale_ip: str | None) -> str:
    if host == "auto":
        if not tailscale_ip:
            raise ValueError("phone_bad_bind")
        return tailscale_ip.strip()
    return host


# ---------------------------------------------------------------------------------------------- auth


def canonical(ts: str, nonce: str, method: str, path: str) -> bytes:
    return f"{ts}\n{nonce}\n{method}\n{path}".encode()


def sign(key: bytes, ts: str, nonce: str, path: str, alg: str = "hmac-sha256", method: str = "GET") -> str:
    message = canonical(ts, nonce, method, path)
    if alg == "hmac-sha256":
        return hmac.new(key, message, hashlib.sha256).hexdigest()
    if alg == "sha256-envelope":
        return hashlib.sha256(key + b"\n" + message + b"\n" + key).hexdigest()
    raise ValueError("phone_bad_auth")


def _key(environ: dict[str, str], name: str, required: bool) -> bytes | None:
    raw = environ.get(name, "")
    if raw == "" and not required:
        return None
    value = raw.encode()
    if len(value) < MIN_KEY_BYTES:
        raise ValueError("phone_missing_secret")
    return value


class Guard:
    """Window, single-use nonce and rate limits. Thread-safe; clock injectable."""

    def __init__(self, keys: tuple[bytes, ...], clock: Callable[[], float] = time.time) -> None:
        self.keys = keys
        self.clock = clock
        self.nonces: dict[str, float] = {}
        self.hits: dict[str, list[float]] = {}
        self.global_hits: list[float] = []
        self._lock = threading.Lock()

    def _rate_ok(self, client: str, now: float) -> bool:
        cutoff = now - 60
        self.global_hits = [t for t in self.global_hits if t > cutoff]
        mine = [t for t in self.hits.get(client, []) if t > cutoff]
        if len(mine) >= PER_CLIENT_PER_MIN or len(self.global_hits) >= GLOBAL_PER_MIN:
            self.hits[client] = mine
            return False
        mine.append(now)
        self.hits[client] = mine
        self.global_hits.append(now)
        if len(self.hits) > 256:  # bound the table; tailnet peers are few
            self.hits = {k: v for k, v in self.hits.items() if v}
        return True

    def check(self, client: str, path: str, headers: Any) -> str | None:
        """None when the request may be served, else a refusal reason. Every attempt counts toward rate."""
        now = self.clock()
        with self._lock:
            if not self._rate_ok(client, now):
                return "phone_rate_limited"
            ts = str(headers.get("X-Phone-Ts") or "")
            nonce = str(headers.get("X-Phone-Nonce") or "")
            sig = str(headers.get("X-Phone-Sig") or "").lower()
            alg = str(headers.get("X-Phone-Alg") or "hmac-sha256").lower()
            if not (_TS_RE.fullmatch(ts) and _NONCE_RE.fullmatch(nonce) and _SIG_RE.fullmatch(sig) and alg in ALGS):
                return "phone_bad_auth"
            if abs(now - int(ts)) > WINDOW_S:
                return "phone_stale_ts"
            if not any(hmac.compare_digest(sign(k, ts, nonce, path, alg), sig) for k in self.keys):
                return "phone_bad_auth"
            # Nonces are recorded only after a valid signature, so an unauthenticated peer cannot fill the cache.
            self.nonces = {n: t for n, t in self.nonces.items() if t > now - 2 * WINDOW_S}
            if nonce in self.nonces:
                return "phone_replay"
            if len(self.nonces) >= NONCE_CAP:
                return "phone_nonce_cache_full"
            self.nonces[nonce] = now
            return None


# ------------------------------------------------------------------------------------------- summary


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _age_s(iso: Any, now: datetime) -> int | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int((now - ts).total_seconds())


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class Sources:
    """Where each existing receipt/ledger lives. Every path is overridable for tests."""

    def __init__(self, environ: dict[str, str], release_root: Path | None = None) -> None:
        state = Path(environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))
        self.state_root = state
        runtime = state / "data" / "runtime"
        self.watchdog = runtime / "n8n_lab_watchdog_last.json"
        self.incidents = runtime / "n8n_incident_fanin_last.json"
        self.coordination_ledger = ledger_path(environ)
        self.release_root = release_root or ROOT
        self.lane_registry = self.release_root / "config" / "lane_registry.json"
        self.build_sha = self.release_root / "BUILD_SHA"
        approvals = environ.get("GUARD_APPROVALS_DIR") or str(Path.home() / ".cursor" / "approvals")
        self.guard_requests = Path(approvals) / "remote_requests.json"


def build_summary(src: Sources, now: datetime | None = None) -> dict[str, Any]:
    """Pure read of existing receipts. Missing sources are named, never guessed."""
    now = now or datetime.now(timezone.utc)
    missing: list[str] = []

    wd = _read_json(src.watchdog)
    n8n: dict[str, Any] = {"healthy": None, "age_s": None, "workflows_registered": None}
    if isinstance(wd, dict):
        age = _age_s(wd.get("checked_at"), now)
        n8n["age_s"] = age
        n8n["healthy"] = bool(wd.get("ok") is True and age is not None and age <= WATCHDOG_STALE_S)
    else:
        missing.append("n8n_watchdog")
    reg = _read_json(src.lane_registry)
    if isinstance(reg, dict) and isinstance(reg.get("lanes"), list):
        n8n["workflows_registered"] = sum(
            1
            for lane in reg["lanes"]
            if isinstance(lane, dict)
            and isinstance(lane.get("scheduler"), dict)
            and lane["scheduler"].get("kind") == "n8n"
            and lane.get("state", "ACTIVE") == "ACTIVE"
        )
    else:
        missing.append("lane_registry")

    failed: dict[str, Any] = {"count": None, "lanes": []}
    proj = project_runs(src.coordination_ledger, state="RUN_FAILED", limit=200, now=now)
    if proj.get("status") == "OK":
        recent = [i for i in proj.get("items") or [] if isinstance(i.get("age_s"), int) and i["age_s"] <= 86400]
        lanes: list[str] = []
        for item in recent:
            lane = str(item.get("lane_id") or "")[:48]
            if lane and lane not in lanes:
                lanes.append(lane)
        failed = {"count": len(recent), "lanes": lanes[:MAX_LANES]}
    else:
        missing.append("coordination_ledger")

    inc = _read_json(src.incidents)
    incidents: dict[str, Any] = {"open": None, "p1": None, "p2": None, "age_s": None}
    if isinstance(inc, dict):
        sev = inc.get("by_severity") if isinstance(inc.get("by_severity"), dict) else {}
        incidents = {
            "open": _int(inc.get("open")),
            "p1": _int(sev.get("P1")) or 0,
            "p2": _int(sev.get("P2")) or 0,
            "age_s": _age_s(inc.get("as_of"), now),
        }
    else:
        missing.append("incident_fanin")

    # Count only. Request ids, scopes, reasons and code fingerprints never leave this function.
    pending: int | None = None
    doc = _read_json(src.guard_requests)
    if isinstance(doc, dict) and isinstance(doc.get("requests"), list):
        epoch = now.timestamp()
        pending = sum(
            1
            for r in doc["requests"]
            if isinstance(r, dict)
            and r.get("status") == "PENDING"
            and isinstance(r.get("expires_at"), (int, float))
            and r["expires_at"] > epoch
        )
    else:
        missing.append("guard_requests")

    sha: str | None = None
    try:
        raw = src.build_sha.read_text(encoding="utf-8").strip()
        sha = raw[:12] if re.fullmatch(r"[0-9a-f]{7,40}", raw) else None
    except OSError:
        pass
    if sha is None:
        missing.append("build_sha")

    disk: float | None = None
    try:
        usage = shutil.disk_usage(src.state_root)
        denom = usage.used + usage.free  # df's Use%: reserved blocks are not counted as available
        disk = round(100.0 * usage.used / denom, 1) if denom else None
    except OSError:
        missing.append("disk")

    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": now.replace(microsecond=0).isoformat(),
        "n8n": n8n,
        "run_failed_24h": failed,
        "incidents": incidents,
        "guard": {"pending_requests": pending},
        "release": {"served_sha": sha},
        "disk": {"used_pct": disk},
        "missing": missing,
    }


def encode_bounded(summary: dict[str, Any]) -> bytes:
    """Compact JSON <= MAX_PAYLOAD; lanes are dropped before anything else."""
    body = json.dumps(summary, separators=(",", ":")).encode()
    if len(body) <= MAX_PAYLOAD:
        return body
    trimmed = json.loads(body)
    trimmed["run_failed_24h"]["lanes"] = trimmed["run_failed_24h"].get("lanes", [])[:2]
    trimmed["truncated"] = True
    body = json.dumps(trimmed, separators=(",", ":")).encode()
    if len(body) <= MAX_PAYLOAD:
        return body
    raise ValueError("phone_payload_too_large")


# -------------------------------------------------------------------------------------------- server


class PhoneStatus:
    def __init__(
        self,
        *,
        environ: dict[str, str] | None = None,
        sources: Sources | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.environ = dict(environ or os.environ)
        keys = tuple(k for k in (_key(self.environ, KEY_ENV, True), _key(self.environ, KEY_PREVIOUS_ENV, False)) if k)
        self.guard = Guard(keys, clock=clock)
        self.sources = sources or Sources(self.environ)
        self.clock = clock
        self.counts = {"served": 0, "refused": 0}
        self._cache: tuple[float, bytes] | None = None
        self._lock = threading.Lock()
        self.receipt = self.sources.state_root / "data" / "runtime" / "phone_status_last.json"

    def _note(self, outcome: str) -> None:
        with self._lock:
            self.counts["served" if outcome == "served" else "refused"] += 1
            row = {"at": datetime.now(timezone.utc).isoformat(), "last": outcome, "counts": dict(self.counts)}
            try:
                self.receipt.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.receipt.with_suffix(".tmp")
                tmp.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
                os.replace(tmp, self.receipt)
            except OSError:
                pass

    def _refuse(self, reason: str, status: int) -> tuple[int, bytes]:
        assert reason in REFUSALS
        self._note(reason)
        return status, json.dumps({"state": "REFUSED", "reason": reason}, separators=(",", ":")).encode()

    def _body(self) -> bytes:
        now = self.clock()
        with self._lock:
            if self._cache and now - self._cache[0] < CACHE_S:
                return self._cache[1]
        body = encode_bounded(build_summary(self.sources))
        with self._lock:
            self._cache = (now, body)
        return body

    def handle(self, method: str, path: str, client_ip: str, headers: Any) -> tuple[int, bytes]:
        try:
            peer = ipaddress.ip_address(client_ip)
        except ValueError:
            return self._refuse("phone_bad_peer", 403)
        if peer.version != 4 or peer not in TAILNET:
            return self._refuse("phone_bad_peer", 403)
        if method != "GET":
            return self._refuse("phone_bad_method", 405)
        if path != STATUS_PATH:
            return self._refuse("phone_bad_path", 404)
        reason = self.guard.check(client_ip, path, headers)
        if reason is not None:
            status = {"phone_rate_limited": 429, "phone_nonce_cache_full": 429}.get(reason, 401)
            return self._refuse(reason, status)
        try:
            body = self._body()
        except ValueError:
            return self._refuse("phone_payload_too_large", 500)
        self._note("served")
        return 200, body


class PhoneServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16


def handler_for(app: PhoneStatus) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 5

        def log_message(self, *_: Any) -> None:
            return

        def _send(self, method: str) -> None:
            status, body = app.handle(method, self.path, self.client_address[0], self.headers)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            self._send("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._send("POST")

        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST
        do_HEAD = do_POST

    return Handler


def main(argv: list[str] | None = None, *, tailscale: Callable[[], str | None] = tailscale_ipv4) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="auto", help="'auto' = `tailscale ip -4`; anything else must equal it")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--dry-run", action="store_true", help="check bind + key + build one summary; no listener")
    args = parser.parse_args(argv)
    try:
        ts_ip = tailscale()
        host = resolve_host(args.host, ts_ip)
        guard_bind(host, args.port, ts_ip)
        if args.dry_run:
            try:
                _key(dict(os.environ), KEY_ENV, True)
                key_present = True
            except ValueError:
                key_present = False
            body = encode_bounded(build_summary(Sources(dict(os.environ))))
            print(json.dumps({"ok": True, "dry_run": True, "host": host, "port": args.port,
                              "key_present": key_present, "bytes": len(body)}))
            return 0
        app = PhoneStatus()
        server = PhoneServer((host, args.port), handler_for(app))
    except (ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 2
    print(json.dumps({"ok": True, "host": host, "port": args.port, "authority": "READ_ONLY_ADVISORY"}), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
