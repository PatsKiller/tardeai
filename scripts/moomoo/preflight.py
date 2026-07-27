#!/usr/bin/env python3
"""Moomoo Stage 0 health / preflight CLI.

Probes config presence and optional OpenD TCP reachability.
Never logs secret values or DSNs. Exit codes: 0 ok · 2 usage · 4 fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import MoomooClient, StubTransport, tcp_reachable
from .config import ConfigError, load_stage0_config, secret_presence


def run_preflight(
    *,
    config_path: str | Path | None = None,
    probe_opend: bool = False,
    transport_up: bool | None = None,
) -> dict[str, Any]:
    """Evaluate Stage 0 gates. ``probe_opend`` may open a TCP socket (opt-in)."""
    gates: list[dict[str, Any]] = []
    fails: list[str] = []

    def gate(name: str, ok: bool, detail: str) -> None:
        gates.append({"gate": name, "ok": ok, "detail": detail})
        if not ok:
            fails.append(f"{name}: {detail}")

    try:
        cfg = load_stage0_config(config_path)
    except ConfigError as exc:
        return {
            "ok": False,
            "stage": 0,
            "gates": [{"gate": "config_load", "ok": False, "detail": str(exc)}],
            "failures": [f"config_load: {exc}"],
            "order_routing": False,
        }

    gate("config_present", True, f"path={cfg.path.name}")
    gate("schema_stage0", cfg.stage == 0 and cfg.schema_version.startswith("moomoo-stage0"),
         f"schema={cfg.schema_version} stage={cfg.stage}")
    gate("read_only_mode", cfg.read_only, f"mode={cfg.mode}")
    gate("order_routing_off", not cfg.order_routing, "order_routing must be false")
    gate("trade_unlock_off", not cfg.trade_unlock, "trade_unlock must be false")

    presence = secret_presence(cfg.required_secret_names)
    missing = [n for n, set_ in presence.items() if not set_]
    # Never include values — only names
    if missing and not cfg.allow_missing_secrets:
        gate("secrets_present", False, f"missing_names={missing}")
    else:
        gate(
            "secrets_present",
            True,
            f"required_names={list(cfg.required_secret_names)} "
            f"missing_allowed={cfg.allow_missing_secrets} missing={missing}",
        )

    opend_up = False
    if probe_opend:
        opend_up = tcp_reachable(cfg.host, cfg.port, cfg.connect_timeout_seconds)
        if not opend_up and not cfg.allow_missing_opend and cfg.require_reachable_for_live_probe:
            gate("opend_reachable", False, f"{cfg.host}:{cfg.port} unreachable")
        else:
            gate(
                "opend_reachable",
                True if opend_up or cfg.allow_missing_opend else opend_up,
                f"reachable={opend_up} allow_missing={cfg.allow_missing_opend}",
            )
    else:
        gate("opend_reachable", True, "skipped (no --probe-opend; CI default)")

    # Fail-closed client scaffold
    client = MoomooClient(
        cfg,
        transport=StubTransport(force_up=bool(transport_up) if transport_up is not None else opend_up),
        opend_up=transport_up if transport_up is not None else (opend_up if probe_opend else None),
    )
    # When not probing and no override, force stub down to prove fail-closed path is wired
    if transport_up is None and not probe_opend:
        client.mark_opend(False)

    fail_closed_ok = True
    try:
        if client.config.fail_closed and not client.opend_up:
            try:
                client.get_quote("TEST")
                fail_closed_ok = False
            except Exception:
                fail_closed_ok = True
        gate("client_fail_closed", fail_closed_ok, "get_quote refused when OpenD down")
    except Exception as exc:
        gate("client_fail_closed", False, type(exc).__name__)

    # Authority: place_order must raise
    try:
        client.place_order(symbol="TEST")
        gate("order_path_refused", False, "place_order did not raise")
    except Exception:
        gate("order_path_refused", True, "place_order refused")

    ok = not fails
    return {
        "ok": ok,
        "stage": 0,
        "mode": cfg.mode,
        "config": str(cfg.path),
        "opend": {"host": cfg.host, "port": cfg.port, "probed": probe_opend, "up": opend_up},
        "secret_names_checked": list(cfg.required_secret_names),
        "gates": gates,
        "failures": fails,
        "order_routing": False,
        "trade_unlock": False,
        "agents_marked_operational": 0,
        "note": "Stage 0 preflight — read-plane only; never logs secret values",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Moomoo Stage 0 preflight (read-plane only)")
    p.add_argument("--config", default="", help="path to stage0 yaml")
    p.add_argument(
        "--probe-opend",
        action="store_true",
        help="optional TCP reachability probe (not used in CI)",
    )
    p.add_argument("--json", action="store_true", help="print JSON report")
    args = p.parse_args(argv)
    try:
        report = run_preflight(
            config_path=args.config or None,
            probe_opend=bool(args.probe_opend),
        )
    except Exception as exc:
        print(f"[moomoo-stage0] ERROR {type(exc).__name__}", file=sys.stderr)
        return 4
    if args.json or True:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 4


if __name__ == "__main__":
    # Allow `python -m moomoo.preflight` and direct path execution
    raise SystemExit(main())
