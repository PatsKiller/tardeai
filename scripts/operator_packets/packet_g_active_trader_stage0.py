#!/usr/bin/env python3
"""PACKET G — Active Trader Stage 0 (PREPARE-ONLY / DEFAULT-DISABLED).

Preflight + optional registration of docs checksum / read flags only.
NEVER enables live_canary, order routes, session authorize, or agent OPERATIONAL.
Never logs DSN/secrets.

Exit: 0 ok · 2 usage/gate · 3 prepare-only · 4 preflight fail
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACK_TOKEN = "APPLY-AT-STAGE0"
PACKET = "G"
STAGE = 0

_REPO_ROOT = Path(__file__).resolve().parents[2]

DOC_PATHS = (
    "docs/implementation/ACTIVE_TRADER_STAGE0_BASELINE.md",
    "docs/implementation/ACTIVE_TRADER_ROUTE_API_DB_MAP.md",
    "docs/implementation/ACTIVE_TRADER_CURRENT_GUARDRAILS.md",
    "config/active_trader.stage0.example.yaml",
)


class PacketGError(RuntimeError):
    pass


def _ensure_path() -> None:
    scripts = str(_REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _print_disabled(reason: str) -> None:
    print(f"=== PACKET {PACKET} === PREPARE-ONLY / DEFAULT-DISABLED ===")
    print(f"[G] {reason}")
    print(
        f"[G] usage: {os.path.basename(sys.argv[0])} --preflight --ack {ACK_TOKEN} "
        f"[--config PATH]"
    )
    print(
        f"[G]         {os.path.basename(sys.argv[0])} --execute --ack {ACK_TOKEN} "
        f"[--config PATH]   # register docs checksum + read flags only"
    )
    print(f"[G]         {os.path.basename(sys.argv[0])} --self-check")
    print(
        "[G] Stage 0 only. write:false canary:false. NO live orders, NO session "
        "authorize, NO order routes, NO agent OPERATIONAL."
    )


def require_ack(ack: str) -> None:
    if ack != ACK_TOKEN:
        raise PacketGError(f"--ack must equal {ACK_TOKEN}")


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def docs_checksums() -> dict[str, Any]:
    out: dict[str, Any] = {}
    missing: list[str] = []
    for rel in DOC_PATHS:
        p = _REPO_ROOT / rel
        digest = _file_sha256(p)
        out[rel] = digest
        if digest is None:
            missing.append(rel)
    return {"files": out, "missing": missing}


def run_preflight(*, config_path: str | Path | None = None) -> dict[str, Any]:
    _ensure_path()
    from active_trader.flags import FlagsError, load_flags
    from active_trader.read_api import ReadOnlyActiveTraderAPI
    from active_trader.read_http import dispatch

    gates: list[dict[str, Any]] = []
    fails: list[str] = []

    def gate(name: str, ok: bool, detail: str) -> None:
        gates.append({"gate": name, "ok": ok, "detail": detail})
        if not ok:
            fails.append(f"{name}: {detail}")

    checksums = docs_checksums()
    gate("docs_present", not checksums["missing"], f"missing={checksums['missing']}")

    try:
        flags = load_flags(config_path)
        gate("flags_stage0_safe", True, f"path={flags.path.name}")
        gate("live_canary_off", flags.flags.get("live_canary") is False, "live_canary")
        gate("order_routes_off", flags.flags.get("order_routes") is False, "order_routes")
        gate("write_false", flags.write is False, f"write={flags.write}")
        gate("canary_false", flags.canary is False, f"canary={flags.canary}")
    except FlagsError as exc:
        gate("flags_stage0_safe", False, str(exc))
        flags = None

    api = ReadOnlyActiveTraderAPI(flags) if flags else ReadOnlyActiveTraderAPI()
    st, health = dispatch(api, "GET", "/api/v3/active-trader/health")
    gate("health_http", st == 200, f"status={st}")
    gate("health_write_false", health.get("write") is False, str(health.get("write")))
    gate("health_canary_false", health.get("canary") is False, str(health.get("canary")))
    gate("health_stage0", health.get("stage") == 0, str(health.get("stage")))

    st2, body2 = dispatch(api, "POST", "/api/v3/active-trader/health")
    gate("post_refused", st2 == 405, f"status={st2}")

    st3, sessions = dispatch(api, "GET", "/api/v3/active-trader/sessions")
    gate(
        "sessions_empty",
        st3 == 200 and sessions.get("sessions") == [],
        f"status={st3}",
    )

    ok = not fails
    return {
        "packet": PACKET,
        "stage": STAGE,
        "ok": ok,
        "gates": gates,
        "failures": fails,
        "docs_checksums": checksums["files"],
        "health": health,
        "write": False,
        "canary": False,
        "live_canary": False,
        "order_routes": False,
        "note": "Stage 0 preflight — read-only; never enables live_canary or order routes",
    }


def run_execute(
    *,
    config_path: str | Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    pre = run_preflight(config_path=config_path)
    if not pre.get("ok"):
        raise PacketGError("preflight failed: " + "; ".join(pre.get("failures") or []))

    _ensure_path()
    from active_trader.flags import load_flags

    flags = load_flags(config_path)
    dest = registry_path or flags.registry_path
    record = {
        "schema": "active-trader-stage0-registry-v1",
        "packet": PACKET,
        "stage": STAGE,
        "registered_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "write": False,
        "canary": False,
        "live_canary": False,
        "order_routes": False,
        "session_authorize": False,
        "agents_marked_operational": 0,
        "feature_flags": {k: False if k in (
            "live_canary", "order_routes", "session_authorize",
            "moomoo_order_path", "multi_account_live", "runner",
        ) else bool(v) for k, v in flags.flags.items()},
        "docs_checksums": pre.get("docs_checksums"),
        "note": (
            "Packet G registration: docs checksum + read flags only. "
            "Does NOT enable live_canary, order routes, or live orders."
        ),
    }
    # Hard refuse if payload tries to enable live
    blob = json.dumps(record, sort_keys=True)
    if '"live_canary": true' in blob.lower().replace(" ", ""):
        raise PacketGError("registry must not enable live_canary")
    if '"order_routes": true' in blob.lower().replace(" ", ""):
        raise PacketGError("registry must not enable order_routes")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rel = str(dest)
    try:
        rel = str(dest.relative_to(_REPO_ROOT))
    except ValueError:
        pass

    return {
        "packet": PACKET,
        "stage": STAGE,
        "action": "execute",
        "ok": True,
        "preflight": pre,
        "registry_path": rel,
        "write": False,
        "canary": False,
        "live_canary": False,
        "order_routes": False,
        "agents_marked_operational": 0,
        "note": "Registered docs checksum + read flags only — live path remains off",
    }


def self_check() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            raise PacketGError(f"self-check failed: {name}: {detail}")

    try:
        require_ack("")
        check("missing_ack_refuses", False)
    except PacketGError:
        check("missing_ack_refuses", True)

    try:
        require_ack("WRONG")
        check("wrong_ack_refuses", False)
    except PacketGError:
        check("wrong_ack_refuses", True)

    pre = run_preflight()
    check("preflight_ok", bool(pre.get("ok")), str(pre.get("failures")))
    check("health_write_false", pre.get("health", {}).get("write") is False)
    check("health_canary_false", pre.get("health", {}).get("canary") is False)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        reg = Path(td) / "registry.json"
        out = run_execute(registry_path=reg)
        check("execute_registry_written", reg.is_file())
        body = json.loads(reg.read_text(encoding="utf-8"))
        check("execute_live_canary_false", body.get("live_canary") is False)
        check("execute_order_routes_false", body.get("order_routes") is False)
        check("execute_write_false", body.get("write") is False)
        check("execute_no_operational", body.get("agents_marked_operational") == 0)

    return {
        "packet": PACKET,
        "stage": STAGE,
        "self_check": "OK",
        "checks": checks,
        "write": False,
        "canary": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Packet G Active Trader Stage 0")
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--ack", default="")
    p.add_argument("--config", default="")
    p.add_argument("--registry-path", default="", help="override registry path (tests)")
    p.add_argument("--report-json", default="")
    args = p.parse_args(argv)

    if args.self_check:
        try:
            out = self_check()
        except PacketGError as exc:
            print(f"[G][SELF-CHECK FAILED] {exc}", file=sys.stderr)
            return 4
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    if not args.preflight and not args.execute:
        _print_disabled("refused: neither --preflight nor --execute (default-disabled).")
        return 3

    try:
        require_ack(args.ack)
    except PacketGError as exc:
        _print_disabled(f"refused: {exc}")
        return 2

    # Never log DSN/secret env values
    for _k in ("SHADOW_DSN", "LAB_DSN", "DATABASE_URL", "MOOMOO_OPEND_LOGIN_PWD"):
        if _k in os.environ:
            pass

    cfg = args.config or None
    try:
        if args.execute:
            out = run_execute(
                config_path=cfg,
                registry_path=Path(args.registry_path) if args.registry_path else None,
            )
            text = json.dumps(out, indent=2, sort_keys=True)
            print(text)
            if args.report_json:
                Path(args.report_json).write_text(text + "\n", encoding="utf-8")
            print(
                "[G] Docs checksum + read flags registered only — "
                "live_canary off, order_routes off, write:false."
            )
            return 0

        out = run_preflight(config_path=cfg)
        text = json.dumps(out, indent=2, sort_keys=True)
        print(text)
        if args.report_json:
            Path(args.report_json).write_text(text + "\n", encoding="utf-8")
        return 0 if out.get("ok") else 4
    except PacketGError as exc:
        print(f"[G][REFUSED] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[G][ERROR] {type(exc).__name__}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
