#!/usr/bin/env python3
"""Build the conflict-engine golden replay fixture from captured, stored read models. Read-only; writes --out only.

Gap (f) 2026-10-25: the 2026-10-24 capture of the 31 live flags was never saved, so the golden replay is built
from a day's real state instead. Inputs are files the operator (or an agent) captured read-only beforehand:

  --watch PAGE.json ...    GET /api/v3/data-broker/watch-intelligence?view=all|expired&page_size=100&page=N
                           (the served Watch read model: every composed card, live and expired)
  --holdings FILE          GET /api/v2/portfolio/holdings  (CIO truth holdings and total)
  --risk FILE              GET /api/v2/risk                (CIO truth position rows: security_guid, stop state)
  --cio-shadow FILE        data/cio/cio_prospect_shadow.json (the cio-prospect-shadow build)
  --reentry-snapshot FILE  data/runtime/reentry_decision_desk_latest.json
  --state-root DIR         identity registry reads only (scripts/lib/identity_carriage.resolve_security_identity)

Every subject keeps the producer rows the resolver's adapters read (truth, card fields, re-entry row), so the replay
runs adapters + producer registry + engine exactly as scripts/conflict_resolver.py does. The output holds portfolio
facts (held symbols, accounts, weights): it is written outside the repository only (persistent-state/data/conflicts/
golden/, chmod 600) and the public fixture is its scripts/conflict_golden_anonymize.py twin. Nothing here calls a broker,
a model or a sender; nothing writes except --out. Never point --state-root at a .env or credential file.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCHEMA = "ConflictGoldenFixture@v1"
NO_CONSUMER_REASON = "operator/agent capture CLI; its private output feeds scripts/conflict_golden_anonymize.py"
CARD_FIELDS = ("symbol", "security_guid", "trade_ai_state", "trade_ai_as_of")
TRUTH_FIELDS = ("security_guid", "symbol", "canonical", "conviction", "context", "protection_inputs", "gap")


def _load(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc.get("data", doc) if isinstance(doc, dict) and set(doc) <= {"ok", "data"} else doc


def _source(path, as_of=None):
    data = Path(path).read_bytes()
    return {"file": Path(path).name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "as_of": as_of}


def card_rows(card: dict) -> dict:
    """Exactly the fields scripts/lib/conflicts/adapters.security_inputs reads from a Watch card."""
    review = card.get("cio_review") or {}
    inputs = (card.get("decision") or {}).get("inputs") or {}
    out = {k: card.get(k) for k in CARD_FIELDS if card.get(k) is not None}
    out["cio_review"] = {k: review.get(k) for k in ("status", "verdict", "completed_at", "inputs_as_of", "security_guid")
                         if review.get(k) is not None}
    out["decision"] = {"inputs": {k: inputs.get(k) for k in ("synthesis", "synthesis_at", "inputs_as_of")
                                  if inputs.get(k) is not None},
                       "status": (card.get("decision") or {}).get("status")}
    return out


def reentry_rows(snapshot: dict) -> dict:
    """watch_decision.reentry_rows mapping over the stored desk snapshot."""
    rows = {}
    for row in snapshot.get("rows") or []:
        intel = row.get("intel") or {}
        symbol = str(row.get("symbol") or "").upper()
        if symbol and intel.get("state"):
            rows[symbol] = {"state": intel.get("state"), "action": intel.get("action"),
                            "price_as_of": row.get("price_as_of"), "plan_as_of": row.get("plan_as_of"),
                            "held": bool(row.get("held"))}
    return rows


def build(*, watch_pages, holdings, risk, cio_shadow, reentry_snapshot, state_root, captured_at):
    from scripts.lib.cio_truth import security_inputs_for
    from scripts.lib.data_broker.cio_prospect import get_prospects
    from scripts.lib.identity_carriage import resolve_security_identity
    from scripts.lib.ips_policy import policy_for_security
    now = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    cards = {}
    for page in watch_pages:
        for item in _load(page).get("items") or []:
            card = item.get("card") or {}
            if card.get("symbol"):
                cards[str(card["symbol"]).upper()] = card_rows(card)
    held_doc, risk_doc = _load(holdings), _load(risk)
    document = {"portfolio": {"holdings": held_doc.get("holdings") or [], "total_usd": held_doc.get("total_value")},
                "positions": {"rows": risk_doc.get("positions") or []}}
    desk = reentry_rows(json.loads(Path(reentry_snapshot).read_text(encoding="utf-8")))
    projection = get_prospects(shadow_base=Path(cio_shadow), now=now,
                               status={"live": False, "reasons": ["golden capture reads the shadow build"]})
    subjects = []
    for symbol in sorted(set(cards) | set(desk)):
        identity = resolve_security_identity(symbol, root=state_root)
        guid = identity.get("security_guid") if identity.get("identity_status") == "CONFIRMED" else None
        truth = security_inputs_for(guid, document=document, projection=projection, now=now)
        truth["symbol"] = symbol
        truth.setdefault("context", {})["concentration_policy"] = policy_for_security(guid, document=document)
        truth = {k: truth.get(k) for k in TRUTH_FIELDS}      # what security_inputs_from_truth reads, plus the gap
        subjects.append({"symbol": symbol, "identity_status": identity.get("identity_status"), "truth": truth,
                         "card": cards.get(symbol), "reentry": desk.get(symbol)})
    return {"schema": SCHEMA, "captured_at": captured_at, "now": now.isoformat(),
            "sources": {"watch": [_source(p, _load(p).get("generated_at")) for p in watch_pages],
                        "holdings": _source(holdings, held_doc.get("as_of")), "risk": _source(risk),
                        "cio_shadow": _source(cio_shadow, projection.get("as_of")),
                        "reentry_snapshot": _source(reentry_snapshot)},
            "counts": {"subjects": len(subjects), "watch_cards": len(cards), "reentry_rows": len(desk),
                       "positions": len(document["positions"]["rows"])},
            "subjects": subjects}


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--watch", nargs="+", required=True)
    parser.add_argument("--holdings", required=True)
    parser.add_argument("--risk", required=True)
    parser.add_argument("--cio-shadow", required=True)
    parser.add_argument("--reentry-snapshot", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if out.is_relative_to(ROOT):
        raise SystemExit("the real capture holds portfolio facts: write it under persistent-state/data/conflicts/golden/, "
                         "then commit only scripts/conflict_golden_anonymize.py output")
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    doc = build(watch_pages=args.watch, holdings=args.holdings, risk=args.risk, cio_shadow=args.cio_shadow,
                reentry_snapshot=args.reentry_snapshot, state_root=args.state_root, captured_at=args.captured_at)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    out.chmod(0o600)
    print(json.dumps({"ok": True, "out": str(out), **doc["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
