#!/usr/bin/env python3
"""send_advice_digest.py — the 10:00 / 15:00 / 17:00 ET advice digests (operator 2026-10-08).

    python3 scripts/send_advice_digest.py --slot 10            # dry run: prints the HTML messages
    python3 scripts/send_advice_digest.py --slot 17 --send     # deliver, then mark + advance

Window: everything since the previous digest's cut-off (watermark under the persistent state root, so every
checkout shares it); a first run looks back 24 h. The 17:00 digest also reports what moved today.

Delivery bypasses the router (a digest of deferred messages must not itself be deferred — p1_digest_sender's
lesson). Only after a confirmed send: held CIO advisory notes are marked delivered with the digest's message id,
the folded P1 archive watermark advances, and the digest watermark moves. A failed send loses nothing.
Receipt: data/runtime/advice_digest_latest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

RECEIPT = ROOT / "data" / "runtime" / "advice_digest_latest.json"


def _state_path() -> Path:
    base = os.getenv("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(base) / "state" / "advice_digest_watermark.json"


def _db(sql, params=None, fetch="all"):
    from db_adapter import _execute

    return _execute(sql, params, fetch=fetch)


def read_watermark() -> datetime | None:
    try:
        return datetime.fromisoformat(json.loads(_state_path().read_text(encoding="utf-8"))["until"])
    except Exception:
        return None


def write_watermark(until: datetime, slot: str, sent: int) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"until": until.isoformat(), "slot": slot, "messages": sent,
                             "written_at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n", encoding="utf-8")


def universe() -> list[str]:
    """Held + active watchlist + the CIO's top-ranked names (the movers scope)."""
    syms: set[str] = set()
    try:
        from lib.data_broker.watch_domains import membership_held

        syms |= set(membership_held()[0])
    except Exception:
        pass
    for r in _db("SELECT DISTINCT upper(symbol) AS s FROM watchlist_items WHERE status = 'active'") or []:
        syms.add(r["s"])
    try:
        from scripts.lib.cio_opportunity_store import CIOOpportunityStore

        items = CIOOpportunityStore().read_projection().get("items") or {}
        syms |= {s for s, a in items.items() if a.get("rank") and a["rank"] <= 150}
    except Exception:
        pass
    return sorted(syms)


def build(slot: str, now: datetime) -> dict:
    from scripts.lib import advice_digest as ad
    from scripts.lib.cio_notification_outbox import NotificationOutbox

    cfg = ad.load_config()
    since = read_watermark() or (now - timedelta(hours=24))
    sections = ad.collect_comms(_db, since, now)
    outbox = NotificationOutbox()
    held = ad.collect_held_cio(outbox, since) if ad.hold("cio_advisory_outbox") else []
    syms = {it["symbol"] for v in sections.values() for it in v} | {h["symbol"] for h in held if h.get("symbol")}
    want_movers = bool(((cfg.get("slots") or {}).get(str(slot)) or {}).get("movers"))
    uni = universe() if want_movers else []
    movers = ad.collect_movers(_db, now.astimezone(ad._et()).date(), uni, None) if want_movers else None
    if movers:
        for k in ("price", "ratings", "conviction", "catalysts"):
            syms |= {m["symbol"] for m in movers.get(k) or []}
    facts = ad.enrich(_db, sorted(syms))
    hours = max(1, int((now - since).total_seconds() // 3600) + 1)
    other = ad.collect_other(since_hours=hours)
    msgs = ad.render(slot, sections, held, facts, movers, other, now)
    return {"slot": slot, "since": since.isoformat(), "until": now.isoformat(), "messages": msgs,
            "counts": {k: len(v) for k, v in sections.items()} | {"cio_held": len(held),
                                                                   "other": len(other.get("rows") or [])}
            | ({f"movers_{k}": len(v) for k, v in movers.items()} if movers else {}),
            "held": held, "other": other, "outbox": outbox}


def deliver(messages: list[str]) -> list[str | None]:
    from telegram_alert import send_telegram_with_id

    ids = []
    for m in messages:
        r = send_telegram_with_id(m, bypass_router=True, message_class="report",
                                  link_preview_options={"is_disabled": True})
        if not r.get("accepted"):
            raise RuntimeError("digest message not accepted by the transport")
        ids.append(r.get("message_id"))
    return ids


def mark_held_delivered(outbox, held: list[dict], message_id: str | None) -> int:
    n = 0
    for h in held:
        nid = h.get("notification_id")
        if not nid:
            continue
        try:
            token = str(uuid.uuid4())
            outbox.claim(nid, "telegram", "advice_digest", token)
            outbox.confirm(nid, "telegram", token, "advice_digest", f"digest:{message_id or ''}",
                           hashlib.sha256(f"{nid}:digest:{message_id}".encode()).hexdigest())
            n += 1
        except Exception:
            continue
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slot", required=True, choices=["10", "15", "17", "auto"],
                    help="auto = the current ET hour (one cron line: 0 10,15,17 * * 1-5)")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args(argv)
    from scripts.lib import advice_digest as ad

    if not ad.load_config().get("enabled"):
        print("advice digest disabled (config/advice_digest.yaml)")
        return 0
    now = datetime.now(timezone.utc)
    if a.slot == "auto":
        a.slot = str(now.astimezone(ad._et()).hour)
        if a.slot not in (ad.load_config().get("slots") or {}):
            print(f"no digest slot at {a.slot}:00 ET")
            return 0
    b = build(a.slot, now)
    receipt = {"mode": "SEND" if a.send else "DRY-RUN", "slot": a.slot, "since": b["since"], "until": b["until"],
               "counts": b["counts"], "messages": len(b["messages"]), "chars": [len(m) for m in b["messages"]]}
    if not a.send:
        print(json.dumps(receipt, indent=1))
        for m in b["messages"]:
            print("\n----- message -----\n" + m)
        return 0
    try:
        ids = deliver(b["messages"])
    except Exception as e:  # noqa: BLE001
        print(f"ADVICE DIGEST NOT DELIVERED ({e}) — nothing marked, watermarks unchanged", file=sys.stderr)
        return 1
    receipt["message_ids"] = ids
    receipt["cio_notes_marked"] = mark_held_delivered(b["outbox"], b["held"], ids[0] if ids else None)
    rows = b["other"].get("rows") or []
    if rows:
        try:
            import p1_digest_sender as p1

            p1.write_watermark(max(r[0] for r in rows), len(rows))
        except Exception:
            pass
    write_watermark(datetime.fromisoformat(b["until"]), a.slot, len(ids))
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=1, default=str), encoding="utf-8")
    print(json.dumps(receipt, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
