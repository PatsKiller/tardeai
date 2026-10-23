#!/usr/bin/env python3
"""The one governed host applier for Ops -> Controls (AGENTS.md 19.0.0 §27.2, PROPOSED). OPERATOR-ONLY.

It is the only writer of the host changes the Controls page asks for: crontab lines (pause / resume by exact text),
the n8n relay live list, operator_settings (+ history), guard grants (bin/guard), kill-switch ENGAGE (the existing
operator CLI, never modified), and release-train resume / arm (2026-10-22: the signed, fresh-passkey approval is the
operator proof the release-train library's passkey hook checks; AGENTS.md 19.0.0 §25.4). Every change: re-plan, refuse if the target moved since the preview, backup, apply,
verify, append-only audit row, Telegram notification (notification only), and an undo request the operator can make.

It applies only requests that are APPROVED in ops_applier_requests AND carry a valid HMAC approval signature (the key
is a 0600 file outside the repository that only the Command Center process and this applier read), approved at most
``applier.max_approval_age_s`` (120 s) ago. Anything else is refused and audited. While AGENTS.md 19.0.0 is not
ACTIVE it applies nothing (it heartbeats "inert"). Single writer: an exclusive flock; a second instance exits 3.

Agents never run this (§27.2): no agent calls it by CLI, unit, n8n or Telegram. The unit is installed by the operator
(config/systemd/user/tradeai-ops-applier.service; docs/ops/OPS_CONTROLS.md "Activation").

  serve [--once]                    poll the queue (2 s); --once = one pass, then exit
  preview --kind K --params JSON    dry run of one change kind (no write anywhere); prints the plan
  status                            policy, store, factors, heartbeat (read-only)
  init-hmac-key                     create the 0600 approval key if absent (TTY only)
  totp-enroll --label TEXT          create the TOTP RECOVERY secret (0600 file) and its metadata row; prints the
                                    otpauth URI once (TTY only; an existing secret is archived by rename, never deleted)
Exit: 0 ok, 2 refused, 3 another applier holds the lock / usage.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import ops_controls_api as API  # noqa: E402

A, C, S = API.A, API.C, API.S

APPLIER_ACTOR = "host:operator_controls_applier"


def _aware(v: Any) -> Optional[datetime]:
    return API._aware(v)


def write_heartbeat(cfg: dict, *, policy: str, note: str, clock: Callable[[], datetime] = C.utc_now) -> None:
    try:
        C.write_private(C.expand(cfg["applier"]["heartbeat_file"]),
                        json.dumps({"at": C.iso(clock()), "pid": os.getpid(), "policy": policy, "note": note}) + "\n")
    except OSError:
        pass


def process_once(*, cfg: dict, store: Any, hosts: C.Hosts, hmac_key: Optional[bytes],
                 agents_path: Optional[Path] = None, clock: Callable[[], datetime] = C.utc_now,
                 notify: Callable[[str, str, Optional[str]], dict] = lambda s, b, r: {"queued": False}) -> list[dict]:
    """One pass over the APPROVED applier requests. Returns one record per request touched."""
    pol = C.policy_state(agents_path)
    if pol["state"] != C.POLICY_ACTIVE:
        write_heartbeat(cfg, policy=pol["state"], note=f"inert: {pol['detail']}", clock=clock)
        return []
    st = store.tables_status()
    if st["state"] != "OK":
        write_heartbeat(cfg, policy=pol["state"], note=f"store {st['state']}", clock=clock)
        return []
    if not hmac_key:
        write_heartbeat(cfg, policy=pol["state"], note="approval HMAC key missing: refusing everything", clock=clock)
    ctx = SimpleNamespace(store=store, clock=clock, notify=notify)
    max_age = int(cfg["applier"].get("max_approval_age_s", 120))
    out = []
    for req in store.list_approved("applier", 10):
        rid = req["request_id"]
        if not A.verify_approval(hmac_key, req):
            r = store.transition(rid, ("APPROVED",), "APPLYING")
            if r:
                API.finish(ctx, r, {"outcome": "REFUSED", "code": "SIGNATURE_INVALID",
                                    "detail": "approval signature missing or invalid; nothing applied"},
                           actor=APPLIER_ACTOR)
            out.append({"request_id": rid, "outcome": "REFUSED", "code": "SIGNATURE_INVALID"})
            continue
        approved = _aware(req.get("approved_at"))
        if not approved or (clock() - approved).total_seconds() > max_age:
            store.transition(rid, ("APPROVED",), "EXPIRED")
            store.append_audit(actor=APPLIER_ACTOR, action="request.expired", kind=req["kind"], request_id=rid,
                               outcome="expired", detail={"max_age_s": max_age})
            out.append({"request_id": rid, "outcome": "EXPIRED"})
            continue
        fresh = API.SW.needs_fresh_passkey(req["kind"], req.get("params"))
        if fresh and req.get("stepup_factor") not in ("passkey", "totp"):
            # Defence in depth (sudo window, 2026-10-22): the CC refuses this at approve; the applier re-checks the
            # factor inside the signed approval, so an always-fresh kind is never applied on a window step-up.
            r = store.transition(rid, ("APPROVED",), "APPLYING")
            if r:
                API.finish(ctx, r, {"outcome": "REFUSED", "code": "FRESH_PASSKEY_REQUIRED", "detail": fresh},
                           actor=APPLIER_ACTOR)
            out.append({"request_id": rid, "outcome": "REFUSED", "code": "FRESH_PASSKEY_REQUIRED"})
            continue
        r = store.transition(rid, ("APPROVED",), "APPLYING")
        if not r:
            continue
        try:
            result = C.apply_change(r["kind"], r["params"], r.get("expected_state_digest"), hosts, store,
                                    request_id=rid, actor=r["actor"], approval=req, hmac_key=hmac_key)
        except (C.OpsError, S.StoreError) as exc:
            result = {"outcome": "REFUSED", "code": exc.code, "detail": exc.detail}
        except Exception as exc:  # noqa: BLE001 — recorded, never retried blindly
            result = {"outcome": "FAILED", "code": type(exc).__name__, "detail": str(exc)[:300]}
        API.finish(ctx, r, result, actor=r["actor"])
        out.append({"request_id": rid, "outcome": result.get("outcome"), "code": result.get("code")})
    write_heartbeat(cfg, policy=pol["state"], note=f"ok; {len(out)} request(s) this pass", clock=clock)
    return out


def _lock(cfg: dict):
    path = C.expand(cfg["applier"]["lock_file"])
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _pg_store() -> S.PgStore:
    from scripts import session13_db

    return S.PgStore(session13_db.get_conn, owned=True)


def _require_tty(what: str) -> None:
    if not sys.stdin.isatty():
        print(f"REFUSED: {what} is typed by the operator at the host terminal, never piped", file=sys.stderr)
        raise SystemExit(2)


def cmd_serve(args, cfg: dict) -> int:
    fh = _lock(cfg)
    if fh is None:
        print("REFUSED: another applier holds the lock (single writer)", file=sys.stderr)
        return 3
    store = _pg_store()
    hosts = C.Hosts(cfg)
    key_path = C.expand(cfg["secrets"]["hmac_key_file"])
    poll = float(cfg["applier"].get("poll_s", 2))
    while True:
        try:
            done = process_once(cfg=cfg, store=store, hosts=hosts, hmac_key=A.load_hmac_key(key_path),
                                notify=lambda s, b, r: API.notify_host(cfg, s, b, r))
            for d in done:
                print(json.dumps(d), flush=True)
        except Exception as exc:  # noqa: BLE001 — keep serving; the heartbeat shows the error
            write_heartbeat(cfg, policy="UNKNOWN", note=f"pass error {type(exc).__name__}: {str(exc)[:120]}")
        if args.once:
            return 0
        time.sleep(poll)


def cmd_preview(args, cfg: dict) -> int:
    try:
        params = json.loads(args.params)
    except ValueError:
        print("usage: --params must be JSON", file=sys.stderr)
        return 3
    store: Any = S.MemoryStore() if args.offline else _pg_store()
    try:
        plan = C.plan_change(args.kind, params, C.Hosts(cfg), store, request_id="opsreq_" + "0" * 20)
    except (C.OpsError, S.StoreError) as exc:
        print(json.dumps({"refused": exc.code, "detail": exc.detail}, indent=2))
        return 2
    print(json.dumps({"dry_run": True, "kind": args.kind, "params": plan.params, "digest": plan.digest,
                      **plan.public()}, indent=2, default=str))
    print("DRY RUN — nothing written", file=sys.stderr)
    return 0


def cmd_status(args, cfg: dict) -> int:
    pol = C.policy_state()
    out: dict[str, Any] = {"policy": pol,
                           "hmac_key": "present" if A.load_hmac_key(C.expand(cfg["secrets"]["hmac_key_file"]))
                           else "missing",
                           "totp_secret": "present" if A.read_private_file(
                               C.expand(cfg["secrets"]["totp_secret_file"])) else "missing",
                           "webauthn_library": A.webauthn_available()}
    try:
        out["heartbeat"] = json.loads(C.expand(cfg["applier"]["heartbeat_file"]).read_text())
    except (OSError, ValueError):
        out["heartbeat"] = None
    if not args.offline:
        out["store"] = _pg_store().tables_status()
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_init_hmac_key(args, cfg: dict) -> int:
    _require_tty("init-hmac-key")
    path = C.expand(cfg["secrets"]["hmac_key_file"])
    if path.exists():
        print(f"exists: {path} (not replaced; rotate by renaming it aside first)")
        return 0
    C.write_private(path, secrets.token_hex(32) + "\n")
    print(f"created {path} (0600). Restart portfolio-server and the applier so both read it.")
    return 0


def cmd_totp_enroll(args, cfg: dict) -> int:
    _require_tty("totp-enroll")
    pol = C.policy_state()
    if pol["state"] != C.POLICY_ACTIVE:
        print(f"REFUSED: POLICY_NOT_ACTIVE ({pol['detail']})", file=sys.stderr)
        return 2
    try:
        import pyotp
    except ImportError:
        print("REFUSED: pyotp is not installed (requirements.txt)", file=sys.stderr)
        return 2
    path = C.expand(cfg["secrets"]["totp_secret_file"])
    if path.exists():
        archived = path.with_name(f"{path.name}.archived-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        path.rename(archived)  # §0 rule 6: rename, never delete
        print(f"previous secret archived to {archived}")
    secret = pyotp.random_base32()
    C.write_private(path, secret + "\n")
    row = _pg_store().totp_enroll(label=args.label, fingerprint=A.totp_fingerprint(secret),
                                  actor=f"host:{os.getuid()}")
    uri = pyotp.TOTP(secret).provisioning_uri(name=args.label, issuer_name="Trade AI Ops Controls (recovery)")
    print("Add this to Google Authenticator now (shown once; recovery only — never a factor for a risky act):")
    print(uri)
    _pg_store().append_audit(actor=f"host:{os.getuid()}", action="totp.enrolled", kind=None, request_id=None,
                             outcome="ok", detail={"label": args.label, "id": row.get("id")})
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve")
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("preview")
    p.add_argument("--kind", required=True)
    p.add_argument("--params", default="{}")
    p.add_argument("--offline", action="store_true", help="no database (setting kinds then preview against empty)")
    p = sub.add_parser("status")
    p.add_argument("--offline", action="store_true")
    sub.add_parser("init-hmac-key")
    p = sub.add_parser("totp-enroll")
    p.add_argument("--label", required=True)
    args = ap.parse_args(argv)
    cfg = C.load_config(args.config)
    return {"serve": cmd_serve, "preview": cmd_preview, "status": cmd_status, "init-hmac-key": cmd_init_hmac_key,
            "totp-enroll": cmd_totp_enroll}[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
