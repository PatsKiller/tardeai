#!/usr/bin/env python3
"""PACKET F — Moomoo Stage 0 foundation (PREPARE-ONLY / DEFAULT-DISABLED).

Read-plane only: config preflight + optional OpenD TCP probe + optional
read-path health registration. NEVER places orders, unlocks trading, enables
agent timers, or marks agents OPERATIONAL. Never logs secret values or DSNs.

Exit codes: 0 ok · 2 usage/gate · 3 prepare-only · 4 preflight fail
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ACK_TOKEN = "APPLY-MOOMOO-STAGE0"
PACKET = "F"
STAGE = 0

_REPO_ROOT = Path(__file__).resolve().parents[2]


class PacketFError(RuntimeError):
    pass


def _ensure_path() -> None:
    scripts = str(_REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _print_disabled(reason: str) -> None:
    print(f"=== PACKET {PACKET} === PREPARE-ONLY / DEFAULT-DISABLED ===")
    print(f"[F] {reason}")
    print(
        f"[F] usage: {os.path.basename(sys.argv[0])} --preflight "
        f"--ack {ACK_TOKEN} [--config PATH] [--probe-opend]"
    )
    print(
        f"[F]         {os.path.basename(sys.argv[0])} --execute "
        f"--ack {ACK_TOKEN} [--config PATH]   # read-path health only"
    )
    print(f"[F]         {os.path.basename(sys.argv[0])} --self-check")
    print(
        "[F] Stage 0 read-plane only. NO order routing. NO trade unlock. "
        "NO agent OPERATIONAL. NO schedule enable. Secrets never logged."
    )


def require_ack(ack: str) -> None:
    if ack != ACK_TOKEN:
        raise PacketFError(f"--ack must equal {ACK_TOKEN}")


def self_check() -> dict[str, Any]:
    _ensure_path()
    from moomoo.client import MoomooAuthorityError, MoomooClient, MoomooUnavailable, StubTransport
    from moomoo.config import load_stage0_config
    from moomoo.preflight import run_preflight

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            raise PacketFError(f"self-check failed: {name}: {detail}")

    # missing ack
    try:
        require_ack("")
        check("missing_ack_refuses", False)
    except PacketFError:
        check("missing_ack_refuses", True)

    try:
        require_ack("WRONG")
        check("wrong_ack_refuses", False)
    except PacketFError:
        check("wrong_ack_refuses", True)

    cfg = load_stage0_config(_REPO_ROOT / "config" / "moomoo.stage0.example.yaml")
    check("example_config_loads", cfg.read_only and cfg.stage == 0)

    client = MoomooClient(cfg, transport=StubTransport(force_up=False))
    try:
        client.get_quote("SPY")
        check("fail_closed_when_down", False, "should raise")
    except MoomooUnavailable:
        check("fail_closed_when_down", True)

    try:
        client.place_order()
        check("order_path_refused", False)
    except MoomooAuthorityError:
        check("order_path_refused", True)

    report = run_preflight(
        config_path=cfg.path,
        probe_opend=False,  # no network in self-check / CI
    )
    check("preflight_no_network_ok", bool(report.get("ok")), str(report.get("failures")))
    check("preflight_order_routing_false", report.get("order_routing") is False)
    check("preflight_no_operational", report.get("agents_marked_operational") == 0)

    return {
        "packet": PACKET,
        "stage": STAGE,
        "self_check": "OK",
        "checks": checks,
        "order_routing": False,
        "agents_marked_operational": 0,
        "note": "default-disabled; missing ack refuses; fail-closed; no order path",
    }


def run_execute(
    *,
    config_path: str | Path | None = None,
    probe_opend: bool = False,
    health_path: Path | None = None,
) -> dict[str, Any]:
    """Execute: re-run preflight; on success write read-path health only."""
    _ensure_path()
    from moomoo.config import load_stage0_config
    from moomoo.health_registry import build_health_record, write_health_registry
    from moomoo.preflight import run_preflight

    pre = run_preflight(config_path=config_path, probe_opend=probe_opend)
    if not pre.get("ok"):
        raise PacketFError("preflight failed: " + "; ".join(pre.get("failures") or []))

    cfg = load_stage0_config(config_path)
    record = build_health_record(cfg, pre)
    dest = health_path or cfg.health_registry_path
    path = write_health_registry(record, dest)

    rel = str(path)
    try:
        rel = str(path.relative_to(_REPO_ROOT))
    except ValueError:
        pass

    return {
        "packet": PACKET,
        "stage": STAGE,
        "action": "execute",
        "ok": True,
        "preflight": pre,
        "health_registry": rel,
        "order_routing": False,
        "trade_unlock": False,
        "agents_marked_operational": 0,
        "schedule_enabled": False,
        "note": (
            "Stage 0 execute wrote read-path health registration only. "
            "NO order routing. NO trade unlock. NO agent OPERATIONAL. "
            "NO schedule enable."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Packet F Moomoo Stage 0 (prepare-only; read-plane only)",
    )
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--ack", default="")
    p.add_argument("--config", default="")
    p.add_argument(
        "--probe-opend",
        action="store_true",
        help="optional TCP probe (not for CI)",
    )
    p.add_argument(
        "--health-path",
        default="",
        help="override health registry path (tests)",
    )
    p.add_argument("--report-json", default="")
    args = p.parse_args(argv)

    if args.self_check:
        try:
            out = self_check()
        except PacketFError as exc:
            print(f"[F][SELF-CHECK FAILED] {exc}", file=sys.stderr)
            return 4
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    if not args.preflight and not args.execute:
        _print_disabled("refused: neither --preflight nor --execute (default-disabled).")
        return 3

    try:
        require_ack(args.ack)
    except PacketFError as exc:
        _print_disabled(f"refused: {exc}")
        return 2

    # Never print DSN / secret env values even if present
    for key in ("SHADOW_DSN", "LAB_DSN", "MOOMOO_OPEND_LOGIN_PWD", "DATABASE_URL"):
        if key in os.environ:
            pass  # presence ok; do not log

    cfg_path = args.config or None
    try:
        if args.execute:
            out = run_execute(
                config_path=cfg_path,
                probe_opend=bool(args.probe_opend),
                health_path=Path(args.health_path) if args.health_path else None,
            )
            text = json.dumps(out, indent=2, sort_keys=True)
            print(text)
            if args.report_json:
                Path(args.report_json).write_text(text + "\n", encoding="utf-8")
            print(
                "[F] Read-path health registered only — "
                "no order routing, no trade unlock, no OPERATIONAL."
            )
            return 0

        _ensure_path()
        from moomoo.preflight import run_preflight

        out = run_preflight(
            config_path=cfg_path,
            probe_opend=bool(args.probe_opend),
        )
        text = json.dumps(out, indent=2, sort_keys=True)
        print(text)
        if args.report_json:
            Path(args.report_json).write_text(text + "\n", encoding="utf-8")
        return 0 if out.get("ok") else 4
    except PacketFError as exc:
        print(f"[F][REFUSED] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[F][ERROR] {type(exc).__name__}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
