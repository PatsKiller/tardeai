#!/usr/bin/env python3
"""Replay one operator question through the desk path OFFLINE. Litmus harness.

WHY
---
On 2026-09-13 three operator questions got a book dump, a false "cash is empty"
claim, and no statement of where anything came from. Each was diagnosed by hand
from Telegram screenshots. This runs `handle_operator_desk_question` -- the same
function the poller calls -- against injected snapshot / desk / holdings
fixtures, with every side effect stubbed, and prints what the operator would
have received and what it was built from:

    reply text · evidence sources · gaps · contract findings (Agent C) ·
    reply provenance (Agent A)

OFFLINE MEANS
-------------
    * no Telegram: nothing here imports a transport; the desk returns text only
    * no model: CIO_OPERATOR_INTENT_FLASH / CIO_REENTRY_FLASH /
      CIO_OPERATOR_FREEFORM_FLASH are forced to 0 and GAP_RESOLVER_LIVE is removed
    * no DB and no host data/: the snapshot, desk rows, holdings and known-symbol
      set come from the fixtures; subject research, theses, gap registration,
      Hermes enqueue and the decision payload are stubbed; the pending ledger and
      the gap-resolver receipts are redirected into a temp directory

USAGE
-----
    python scripts/replay_operator_question.py --question "Is now a good time to get back into schg"
    python scripts/replay_operator_question.py --question "..." \\
        --snapshot tests/fixtures/litmus_20260913/snapshot.json \\
        --desk tests/fixtures/litmus_20260913/desk.json \\
        --holdings tests/fixtures/litmus_20260913/holdings.json --json

    --dry-run is accepted and is the only mode: the harness never sends.

EXIT CODES
----------
    0  replayed
    2  could not run (fixture unreadable, desk raised)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

NO_CONSUMER_REASON = (
    "operator/engineer litmus tool and test harness; invoked by hand and by "
    "tests/test_operator_answer_quality_20260913.py, nothing imports it in production."
)

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "litmus_20260913"

_OFFLINE_ENV = {
    "CIO_OPERATOR_INTENT_FLASH": "0",
    "CIO_REENTRY_FLASH": "0",
    "CIO_OPERATOR_FREEFORM_FLASH": "0",
    "CIO_OPERATOR_FREEFORM_QUEUE": "0",
}


def _load(path: Optional[Path]) -> Optional[dict]:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _held_map(holdings: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in (holdings or {}).get("holdings") or []:
        if not isinstance(r, dict) or not r.get("symbol"):
            continue
        sym = str(r["symbol"]).upper()
        if sym == "CASH":
            continue
        out[sym] = {
            "shares": r.get("shares", r.get("quantity")),
            "market_value": r.get("market_value"),
            "account": r.get("account") or r.get("account_id"),
            "as_of": r.get("as_of") or r.get("updated_at"),
        }
    return out


class _Patcher:
    """Minimal setattr/env patcher that always restores (no pytest dependency)."""

    def __init__(self) -> None:
        self._attrs: list[tuple[Any, str, Any, bool]] = []
        self._env: list[tuple[str, Optional[str]]] = []

    def setattr(self, obj: Any, name: str, value: Any) -> None:
        had = hasattr(obj, name)
        self._attrs.append((obj, name, getattr(obj, name, None), had))
        setattr(obj, name, value)

    def setenv(self, key: str, value: Optional[str]) -> None:
        self._env.append((key, os.environ.get(key)))
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    def undo(self) -> None:
        for obj, name, old, had in reversed(self._attrs):
            if had:
                setattr(obj, name, old)
            else:
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass
        for key, old in reversed(self._env):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._attrs.clear()
        self._env.clear()


def _modules(*names: str) -> list[Any]:
    """The desk imports its collaborators under both spellings (lib.* and
    scripts.lib.*); patch every loaded copy so no live store is read."""
    out = []
    for n in names:
        try:
            out.append(importlib.import_module(n))
        except Exception:
            continue
    return out


@contextmanager
def offline_desk(*, snapshot: Optional[dict], desk: Optional[dict], holdings: Optional[dict],
                 workdir: Optional[Path] = None) -> Iterator[Any]:
    """Yield the desk module wired to fixtures, with every side effect stubbed."""
    p = _Patcher()
    tmp_ctx = tempfile.TemporaryDirectory(prefix="replay_operator_question_") if workdir is None else None
    work = Path(tmp_ctx.name) if tmp_ctx else Path(workdir)
    try:
        for k, v in _OFFLINE_ENV.items():
            p.setenv(k, v)
        p.setenv("GAP_RESOLVER_LIVE", None)

        desk_mods = _modules("scripts.lib.cio_operator_desk_loop", "lib.cio_operator_desk_loop")
        conv_mods = _modules("scripts.lib.cio_telegram_converse", "lib.cio_telegram_converse")
        cp_mods = _modules("scripts.lib.data_broker.cio_portfolio")
        gr_mods = _modules("scripts.lib.gap_resolver", "lib.gap_resolver")
        if not desk_mods:
            raise RuntimeError("cio_operator_desk_loop could not be imported")

        rows = list((desk or {}).get("rows") or [])
        computed_at = (desk or {}).get("computed_at")
        held = _held_map(holdings or {})
        known = frozenset({str(r.get("symbol")).upper() for r in rows if r.get("symbol")} | set(held))
        desk_path = Path("fixture:reentry_decision_desk_latest.json")

        def _rows():
            return (rows, computed_at, desk_path if rows else None)

        for m in conv_mods:
            p.setattr(m, "load_reentry_desk_rows", _rows)
        for m in cp_mods:
            p.setattr(m, "get_cio_snapshot", lambda max_age_s=60, **_k: snapshot or {})
        for m in gr_mods:
            p.setattr(m, "RECEIPTS_PATH", work / "gap_resolution_receipts.jsonl")
        for m in desk_mods:
            p.setattr(m, "PENDING_PATH", work / "cio_operator_pending_replies.jsonl")
            p.setattr(m, "_known_symbols", lambda ttl_s=0, _k=known: _k)
            p.setattr(m, "_held_positions_map", lambda _h=held: dict(_h))
            p.setattr(m, "_register_gaps", lambda *a, **k: {"registered": 0, "replay": True})
            p.setattr(m, "_enqueue_hermes_research", lambda *a, **k: {"ok": True, "replay": True})
            p.setattr(m, "_emit_telegram_desk_payload", lambda *a, **k: None)
            p.setattr(m, "subject_research", lambda *a, **k: [])
        try:
            import scripts.lib.symbol_thesis_attach as sta  # noqa: PLC0415
            p.setattr(sta, "thesis_fields_for_symbol", lambda *a, **k: {})
        except Exception:
            pass
        yield desk_mods[0]
    finally:
        p.undo()
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def replay(question: str, *, snapshot: Optional[dict], desk: Optional[dict], holdings: Optional[dict],
           chat_id: str = "replay", message_id: str = "replay-1") -> dict[str, Any]:
    """Run the desk path offline. Returns what the operator would receive and why."""
    with offline_desk(snapshot=snapshot, desk=desk, holdings=holdings) as d:
        res = d.handle_operator_desk_question(question, chat_id=chat_id, message_id=message_id, channel="telegram")
        pending_rows = d._read_jsonl(d.PENDING_PATH)
    # The unanswerable branch returns its body as reply_preview, not text.
    reply = res.get("text") or res.get("reply_preview") or ""
    evidence = res.get("evidence") if isinstance(res.get("evidence"), dict) else {}
    return {
        "question": question,
        "kind": res.get("kind"),
        "reply": reply,
        "reply_source": res.get("reply_source"),
        "model": res.get("model"),
        "intent": {k: (res.get("intent") or {}).get(k) for k in ("intent", "needs", "symbols", "source")},
        "sources": res.get("sources") or [],
        "gaps": res.get("gaps") or [],
        "blocking_gaps": res.get("blocking_gaps") or [],
        "pending_id": res.get("pending_id"),
        "pending_rows_written": len(pending_rows),
        # Agent C: evidence["contract_findings"]; Agent A: reply_provenance. None until they land.
        "contract_findings": res.get("contract_findings") if "contract_findings" in res
        else evidence.get("contract_findings"),
        "reply_provenance": res.get("reply_provenance"),
    }


def _print(out: dict[str, Any]) -> None:
    print(f"Question : {out['question']}")
    print(f"Intent   : {json.dumps(out['intent'])}")
    print(f"Kind     : {out['kind']}   reply_source={out['reply_source']}   model={out['model']}")
    print("-" * 74)
    print(out["reply"] or "(no reply text)")
    print("-" * 74)
    print("Evidence sources : " + (", ".join(map(str, out["sources"])) or "none"))
    print(f"Gaps             : {len(out['gaps'])}")
    for g in out["gaps"][:12]:
        print(f"    - {g.get('domain')}:{g.get('symbol') or '-'}:{g.get('field')} — {g.get('reason')}")
    print(f"Blocking gaps    : {len(out['blocking_gaps'])}")
    print(f"Pending          : {out['pending_id']}  (rows written to the temp ledger: {out['pending_rows_written']})")
    print("Contract findings: " + ("not present on this branch (Agent C)" if out["contract_findings"] is None
                                   else json.dumps(out["contract_findings"], default=str)))
    print("Reply provenance : " + ("not present on this branch (Agent A)" if out["reply_provenance"] is None
                                   else json.dumps(out["reply_provenance"], default=str)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", required=True)
    ap.add_argument("--snapshot", default=str(FIXTURE_DIR / "snapshot.json"))
    ap.add_argument("--desk", default=str(FIXTURE_DIR / "desk.json"))
    ap.add_argument("--holdings", default=str(FIXTURE_DIR / "holdings.json"))
    ap.add_argument("--dry-run", action="store_true", help="accepted for symmetry; the harness never sends")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        out = replay(args.question, snapshot=_load(Path(args.snapshot)), desk=_load(Path(args.desk)),
                     holdings=_load(Path(args.holdings)))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: replay failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        _print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
