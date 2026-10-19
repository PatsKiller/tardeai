"""Guard identity and bounded authority for the reviewed legacy cutover packets.

``id`` and ``verify`` inspect the canonical guard ledger. Mutations instead use
``authorize ACTION --consume``: every required tier must name the exact action,
lane(s), workflow and packet SHA256 in its reason. Restart grants also name both
units and ``restart``. The primary ID is TRADEAI_FABRIC_GRANT; the separate service
ID is TRADEAI_FABRIC_SERVICE_GRANT. IDs are full 32-hex ledger IDs, never labels.

Uses are checked and consumed together under the existing guard transaction lock.
Nothing here issues, renews or restores grants. Refused/failed actions never refund
authority. Dry runs and read-only checks consume nothing.
Legacy scheduler/owner actions in HELD_ACTIONS refuse before ledger access until
the reviewed common transactional controller replaces their mutation paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

NO_CONSUMER_REASON = (
    "Host CLI entrypoint: bin/guard id and the need_grant functions in "
    "docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh, "
    "docs/ops/packets/hermes-feedback-cutover-20261017/cutover.sh and "
    "docs/ops/packets/hermes-tune-cutover-20261017/cutover.sh invoke this file "
    "through host Python. check_dark_contracts indexes scripts/**/*.py callers; "
    "these shell CLI callers are outside that corpus, so no Python importer "
    "is expected."
)

ROOT = Path(__file__).resolve().parents[2]
ID_RE = re.compile(r"[0-9a-f]{32}")
UNITS = ("tradeai-n8n-run-relay.service", "tradeai-n8n-coordination-gateway.service")
HELD_ACTIONS = frozenset({"hermes-tune.c2", "hermes-tune.c3", "hermes-tune.rollback",
                          "hermes-feedback.c3", "hermes-feedback.rollback"})
# Registered actions only: callers cannot select an executable or widen a tier.
ACTIONS = {}
for _name, _packet, _lane, _workflow, _steps in (
    ("comms", "comms-intent-consumer-live", "n8n-comms-intent-consumer", "tradeai-dispatcher", ("relay", "rollback")),
    ("hermes-feedback", "hermes-feedback-cutover", "hermes-learning-outcome-feedback-agent",
     "tradeai-fabric-hermes-learning", ("relay", "c3", "rollback")),
    ("hermes-tune", "hermes-tune-cutover", "hermes-learning-autonomous-self-tune",
     "tradeai-fabric-hermes-learning", ("c1", "c2", "relay", "c3", "rollback")),
):
    for _step in _steps:
        _restart = _step == "relay" or (_name == "comms" and _step == "rollback")
        ACTIONS[f"{_name}.{_step}"] = {
            "packet": f"docs/ops/packets/{_packet}-20261017/cutover.sh",
            "lanes": (_lane, "hermes-learning-pipeline-tune") if _step == "c2" else (_lane,),
            "workflow": _workflow,
            "tiers": ("config-write", "service") if _restart else ("cron",),
            "units": UNITS if _restart else (),
        }


def _guard_ledger():
    hooks = str(ROOT / ".cursor" / "hooks")
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    import guard_ledger

    return guard_ledger


def active_grants(now: float | None = None) -> dict[str, dict]:
    """Reuse canonical schema/symlink/corruption checks; never initialize a ledger."""
    now = time.time() if now is None else now
    try:
        gl = _guard_ledger()
        _, grants = gl.ledger_read()
    except Exception:
        return {}
    return {tier: row for tier, row in grants.items()
            if ID_RE.fullmatch(str(row.get("grant_id") or "").lower())
            and row["expires"] > now and (row["uses"] == -1 or row["uses"] > 0)}


def grant_id(tier: str) -> str | None:
    g = active_grants().get(tier)
    return str(g["grant_id"]) if g else None


def verify(value: str, tiers: list[str]) -> tuple[str, str] | None:
    """Identity lookup only; insufficient to authorize a mutation."""
    value = (value or "").strip().lower()
    if not ID_RE.fullmatch(value):
        return None
    hits = [(t, str(g["grant_id"])) for t, g in active_grants().items()
            if t in tiers and str(g["grant_id"]).lower() == value]
    return hits[0] if len(hits) == 1 else None


class Refused(ValueError):
    pass


def _names(reason: str, token: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_.:-])" + re.escape(token) + r"(?![A-Za-z0-9_.:-])", reason))


def authorize(action: str, *, consume: bool = False, environ=None) -> dict:
    """Check exact authority and optionally consume finite uses before the effect."""
    env = os.environ if environ is None else environ
    spec = ACTIONS.get(action)
    out = {"schema": "FabricPacketGrantCheck@v1", "ok": False, "action": action, "consumed": False}
    if not spec:
        return {**out, "reason": "unregistered packet action"}
    if action in HELD_ACTIONS:
        return {**out, "state": "held", "reason": "reviewed_common_controller_required"}
    try:
        digest = hashlib.sha256((ROOT / spec["packet"]).read_bytes()).hexdigest()
        gl = _guard_ledger()
        required = (action, *spec["lanes"], spec["workflow"], digest)
        checked = []

        def check(doc):
            checked.clear()
            now = time.time()
            for tier in spec["tiers"]:
                key = "TRADEAI_FABRIC_SERVICE_GRANT" if tier == "service" else "TRADEAI_FABRIC_GRANT"
                value = str(env.get(key) or "").strip().lower()
                row = doc.get(tier) or {}
                if not ID_RE.fullmatch(value) or value != str(row.get("grant_id") or "").lower():
                    raise Refused(f"{key} is not the full active {tier} grant id")
                if row.get("expires", 0) <= now or row.get("uses", 0) <= 0:
                    raise Refused(f"{tier} grant expired, exhausted or not finite")
                tokens = (*required, *spec["units"], "restart") if tier == "service" else required
                reason = str(row.get("reason") or "")
                missing = [token for token in tokens if not _names(reason, token)]
                if missing:
                    raise Refused(f"{tier} grant reason missing exact binding: {', '.join(missing)}")
                checked.append({"tier": tier, "grant_id": value, "expires": row["expires"],
                                "uses_left": row["uses"] - (1 if consume else 0)})

        if consume:
            def mut(doc):
                check(doc)  # Recheck IDs, bindings, expiry and uses under the canonical lock.
                for item in checked:
                    row = dict(doc[item["tier"]])
                    row["uses"] = item["uses_left"]
                    doc[item["tier"]] = row  # Exhausted rows remain inactive attribution evidence.
                return doc

            out["consumed"] = None  # A failed durable write may have an ambiguous outcome.
            gl.ledger_update_atomic(mut)
            out["consumed"] = True
            receipt = {**out, "ok": True, "consumed": True, "packet": spec["packet"],
                       "packet_sha256": digest, "lanes": spec["lanes"], "workflow_id": spec["workflow"],
                       "grants": checked, "consumption_id": uuid.uuid4().hex}
            # Audit failure holds the effect; spent uses are never reissued.
            gl.audit_append({**receipt, "event": "fabric-grant-consumed"})
            return receipt
        _, doc = gl.ledger_read()
        check(doc)
        return {**out, "ok": True, "packet": spec["packet"], "packet_sha256": digest, "grants": checked}
    except Refused as exc:
        return {**out, "consumed": False, "reason": f"Refused: {exc}"}
    except Exception as exc:  # Unavailable authority/accounting grants nothing.
        return {**out, "reason": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "id":
        gid = grant_id(argv[1])
        if not gid:
            print(f"no active {argv[1]} grant", file=sys.stderr)
            return 1
        print(gid)
        return 0
    if len(argv) == 3 and argv[0] == "verify":
        hit = verify(argv[1], argv[2].split(","))
        if not hit:
            print("not the full id of an active allowed grant", file=sys.stderr)
            return 1
        print(f"{hit[0]} {hit[1]}")
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("authorize",))
    ap.add_argument("action", choices=sorted(ACTIONS))
    ap.add_argument("--consume", action="store_true")
    args = ap.parse_args(argv)
    result = authorize(args.action, consume=args.consume)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
