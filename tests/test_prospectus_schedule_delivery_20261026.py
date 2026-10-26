"""Prospectus run windows + delivery (operator 2026-10-26).

"Those new reports shouldn't just run ad hoc independently. They should be queued up and run a certain time of the
day, like if something moves plus or minus the 8% threshold; also those reports should be sent out both in Word and
PDF as a notification [on] Telegram and [email]." Email clarified the same day: "just the audit", no attachments.

Synthetic symbols and values only; every store lives under a temp state root; transports are stubs.
"""
from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.prospectus import delivery, load_config, schedule, store  # noqa: E402
import prospectus_window as PW  # noqa: E402
import prospectus_deliver as PD  # noqa: E402


def Z(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture()
def cfg():
    return load_config()


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "state"


def base_of(root, cfg):
    return store.base_dir(root, cfg)


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_config_defaults(cfg):
    wins = {w["id"]: w for w in cfg["run_windows"]["windows"]}
    assert cfg["run_windows"]["timezone"] == "America/New_York"
    assert wins["post_close"]["time"] == "17:45" and wins["post_close"]["scopes"] == ["holding", "watch"]
    assert wins["pre_market"]["time"] == "07:00" and wins["pre_market"]["scopes"] == ["holding"]
    assert "day_move" not in wins["pre_market"]["triggers"]
    d = cfg["delivery"]
    assert d["telegram"]["enabled"] and d["telegram"]["formats"] == ["pdf", "docx"]
    assert d["email"]["enabled"] and d["email"]["attachments"] is False  # operator: email = audit only
    assert d["scopes"]["holding"] and d["scopes"]["watch"]
    assert cfg["cadence"]["triggers"]["day_move_abs_pct"] == 8.0


# ── window selection across DST ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now,expected", [
    ("2026-10-26T21:44:00Z", None),          # EDT: 17:44
    ("2026-10-26T21:46:00Z", "post_close"),  # EDT: 17:46
    ("2026-11-02T21:50:00Z", None),          # EST (DST ended 11-01): 16:50
    ("2026-11-02T22:50:00Z", "post_close"),  # EST: 17:50
    ("2026-11-02T11:05:00Z", None),          # EST: 06:05
    ("2026-11-02T12:05:00Z", "pre_market"),  # EST: 07:05
    ("2026-03-09T11:05:00Z", "pre_market"),  # EDT (DST began 03-08): 07:05
    ("2026-03-06T12:05:00Z", "pre_market"),  # EST Friday: 07:05
    ("2026-10-27T00:10:00Z", None),          # EDT 20:10: past the 120 min catch-up
    ("2026-10-24T21:50:00Z", None),          # Saturday
])
def test_due_window_dst(cfg, root, now, expected):
    win = schedule.due_window(cfg, base_of(root, cfg), Z(now))
    assert (win or {}).get("id") == expected


def test_window_runs_once_and_weekend_flag(cfg, root):
    base = base_of(root, cfg)
    win = schedule.due_window(cfg, base, Z("2026-10-26T21:46:00Z"))
    schedule.record_window(base, win["key"], {"done": []}, month="2026-10", cost_usd=1.25)
    assert schedule.due_window(cfg, base, Z("2026-10-26T22:30:00Z")) is None  # same day, already ran
    assert schedule.read_window_state(base)["spend_by_month"]["2026-10"] == 1.25
    weekend = json.loads(json.dumps(cfg))
    weekend["run_windows"]["windows"][0]["weekend"] = True
    assert schedule.due_window(weekend, base, Z("2026-10-24T21:50:00Z"))["id"] == "post_close"


# ── triggers only enqueue ─────────────────────────────────────────────────────────────────────────────────────
class FakeSources:
    def __init__(self, *, holdings=None, watch=(), bars=None, cats=None, cio=None, stops=None):
        self._h = holdings or {}
        self._w = list(watch)
        self._bars = bars or {}
        self._cats = cats or {}
        self._cio = cio or {}
        self._stops = stops or {}

    def holdings(self):
        return self._h

    def watch_symbols(self):
        return self._w

    def bars(self, sym, days=1100):
        return self._bars.get(sym, [])

    def catalysts(self, sym):
        return self._cats.get(sym, [])

    def cio(self, sym):
        return self._cio.get(sym, {})

    def stops(self, sym, accounts):
        return self._stops.get(sym, [])


def bars(prev, last, last_date="2026-10-26"):
    d = datetime.fromisoformat(last_date)
    return [{"price_date": (d - timedelta(days=1)).date().isoformat(), "close": prev},
            {"price_date": last_date, "close": last}]


def idx(**entries):
    return {"items": {s: {"generated_at": g, "inputs_digest": dg} for s, (g, dg) in entries.items()}}


def test_day_move_on_the_close_enqueues_once(cfg):
    now = Z("2026-10-26T21:50:00Z")
    hold = {"AAA": {"market_value": 500.0}, "BBB": {"market_value": 900.0}, "CCC": {"market_value": 100.0}}
    src = FakeSources(holdings=hold, bars={"AAA": bars(100, 109), "BBB": bars(100, 91), "CCC": bars(100, 107)})
    uni = schedule.plan_universe(hold, [], cfg)
    gen = "2026-10-25T12:00:00+00:00"
    rows = schedule.evaluate_triggers(uni, idx(AAA=(gen, {}), BBB=(gen, {}), CCC=(gen, {})), src, cfg, now=now)
    got = {r["symbol"]: r["reason"] for r in rows}
    assert got["AAA"].startswith("day_move +9.0% close 2026-10-26")
    assert got["BBB"].startswith("day_move -9.0%")  # plus or minus
    assert "CCC" not in got  # 7% is under the 8% threshold
    # report already written after that close -> the same close never fires again
    after = "2026-10-26T21:30:00+00:00"
    rows = schedule.evaluate_triggers(uni, idx(AAA=(after, {}), BBB=(after, {}), CCC=(after, {})), src, cfg, now=now)
    assert not [r for r in rows if r["reason"].startswith("day_move")]


def test_trigger_reasons_and_value_priority(cfg):
    now = Z("2026-10-26T21:50:00Z")
    gen = "2026-10-24T12:00:00+00:00"
    hold = {"BIG": {"market_value": 9000.0, "accounts": ["acct-a"]}, "SML": {"market_value": 10.0, "accounts": []},
            "STP": {"market_value": 50.0, "accounts": ["acct-a"]}}
    src = FakeSources(holdings=hold, watch=["WWW", "NEW"],
                      cats={"BIG": [{"at": "2026-10-26T13:00:00+00:00"}]},
                      cio={"SML": {"stance": "trim"}, "WWW": {"stage": "proposal"}},
                      stops={"STP": [{"stop_price": 41.0}]})
    uni = schedule.plan_universe(hold, ["WWW", "NEW", "BIG"], cfg)
    index = idx(BIG=(gen, {}), SML=(gen, {"cio_stance": "hold"}), STP=(gen, {"stop_levels": [40.0]}),
                WWW=(gen, {"cio_stage": "research"}))
    rows = schedule.evaluate_triggers(uni, index, src, cfg, now=now, holdings=hold)
    got = {r["symbol"]: r["reason"] for r in rows}
    assert got == {"BIG": "material_news", "SML": "cio_stance_change", "STP": "stop_event",
                   "WWW": "promoted_to_proposal", "NEW": "missing"}
    assert [r["symbol"] for r in rows] == ["BIG", "STP", "SML", "NEW", "WWW"]  # holdings by $ value, then watch
    # the pre-market window evaluates only its own scopes and triggers
    pm = next(w for w in cfg["run_windows"]["windows"] if w["id"] == "pre_market")
    rows = schedule.evaluate_triggers(uni, index, src, cfg, now=now, triggers=pm["triggers"], scopes=pm["scopes"],
                                     holdings=hold)
    assert {r["symbol"] for r in rows} == {"BIG", "SML", "STP"}


def test_cadence_monthly_quarterly_weekly(cfg):
    now = Z("2026-10-26T21:50:00Z")
    hold = {"MON": {"market_value": 1.0}, "WEK": {"market_value": 2.0}}
    uni = schedule.plan_universe(hold, ["QTR"], cfg)
    index = idx(MON=("2026-09-20T00:00:00+00:00", {}), WEK=("2026-10-18T00:00:00+00:00", {}),
                QTR=("2026-07-01T00:00:00+00:00", {}))
    got = {r["symbol"]: (r["reason"], r["mode"]) for r in
           schedule.evaluate_triggers(uni, index, FakeSources(holdings=hold), cfg, now=now)}
    assert got == {"MON": ("monthly_due", "full"), "WEK": ("weekly_delta", "delta"), "QTR": ("quarterly_due", "full")}


# ── draining a window ─────────────────────────────────────────────────────────────────────────────────────────
def fake_run_queue(calls, *, stop_after=None, cost=0.5, big=False):
    """A stand-in for pipeline.run_queue: same queue semantics, writes a synthetic version per row."""
    def run_queue(base, sources, cfg, *, limit, holdings=None, manual=False, **_):
        calls.append({"limit": limit, "states": {r["symbol"]: r.get("state") for r in store.read_queue(base)["items"]}})
        summary = {"done": [], "queued": [], "failed": [], "stopped_reason": None, "cost_usd": 0.0}
        for row in list(store.read_queue(base)["items"]):
            if len(summary["done"]) >= limit:
                break
            if row.get("state") not in ("queued", None):
                continue
            if stop_after is not None and len(summary["done"]) >= stop_after:
                summary["stopped_reason"] = "PAUSED_TODAY"
                summary["queued"].append(row["symbol"])
                break
            sym = row["symbol"]
            n = len(store.versions(base, sym))
            version = f"2026102{6 + n}T220000Z"
            doc = {"symbol": sym, "name": f"{sym} Corp", "generated_at": "2026-10-26T22:00:00+00:00", "mode": "full",
                   "verdict_line": f"{sym} synthetic verdict v{n + 1}",
                   "facts": [{"kind": "cio", "label": "CIO conviction", "value": 71}]}
            files = {"prospectus.html": b"<html></html>", "prospectus.pdf": b"%PDF-1.4 x",
                     "prospectus.docx": b"PK" + (b"0" * (51 * 1024 * 1024) if big else b"")}
            store.write_version(base, sym, version, doc, files)
            store.update_index(base, sym, name=doc["name"], scope=row.get("scope"), version=version, status="ready",
                               verdict_line=doc["verdict_line"], cost_usd=cost, model="claude-opus-5-5",
                               generated_at=doc["generated_at"])
            store.mark(base, sym, state="done", done=True)
            summary["done"].append(sym)
            summary["cost_usd"] += cost
        return summary
    return run_queue


def args(**kw):
    return Namespace(apply=kw.get("apply", True), dry_run=False, now=kw.get("now", ""), window=kw.get("window", ""))


def seed_queue(base, rows):
    store.enqueue(base, rows, now=Z("2026-10-26T12:00:00Z"))


def test_pre_market_drains_holdings_only_in_value_order_with_cap(cfg, root):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": "WAT", "scope": "watch", "priority": 1000, "reason": "missing"},
                      {"symbol": "LOW", "scope": "holding", "priority": 105, "reason": "weekly_delta"},
                      {"symbol": "TOP", "scope": "holding", "priority": 10, "reason": "material_news"},
                      {"symbol": "MID", "scope": "holding", "priority": 101, "reason": "monthly_due"}])
    small = json.loads(json.dumps(cfg))
    next(w for w in small["run_windows"]["windows"] if w["id"] == "pre_market")["max_reports"] = 2
    calls = []
    src = FakeSources(holdings={"TOP": {"market_value": 9.0}, "MID": {"market_value": 5.0}, "LOW": {"market_value": 1.0}})
    out = PW.run(args(now="2026-10-27T11:05:00Z"), small, root, sources_factory=lambda r, ro: src,
                 run_queue_fn=fake_run_queue(calls))
    assert out["ran"] == "window" and out["window"] == "pre_market"
    assert out["done"] == ["TOP", "MID"] and calls[0]["limit"] == 2
    assert calls[0]["states"]["WAT"] == schedule.HELD  # watch parked during a holdings-only window
    left = {r["symbol"]: r["state"] for r in store.read_queue(base)["items"]}
    assert left == {"LOW": "queued", "WAT": "queued"}  # leftovers stay queued, nothing stranded
    assert out["queue_left"] == 2
    rec = json.loads((base / out["outbox"]).read_text())
    assert [i["symbol"] for i in rec["items"]] == ["TOP", "MID"] and rec["month_spend_usd"] == 1.0


def test_credit_cap_stops_and_leaves_queue(cfg, root):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": s, "scope": "holding", "priority": 100 + i, "reason": "monthly_due"}
                      for i, s in enumerate(["AAA", "BBB", "CCC"])])
    out = PW.run(args(now="2026-10-26T21:50:00Z"), cfg, root, sources_factory=lambda r, ro: FakeSources(),
                 run_queue_fn=fake_run_queue([], stop_after=1))
    assert out["done"] == ["AAA"] and out["stopped_reason"] == "PAUSED_TODAY" and out["queue_left"] == 2


def test_off_window_runs_only_operator_rewrites(cfg, root):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": "OPR", "scope": "watch", "priority": 1, "reason": "operator_refresh",
                       "requested_by": "operator"},
                      {"symbol": "SCH", "scope": "holding", "priority": 100, "reason": "day_move +9.0%"}])
    calls = []
    out = PW.run(args(now="2026-10-26T15:00:00Z"), cfg, root, sources_factory=lambda r, ro: FakeSources(),
                 run_queue_fn=fake_run_queue(calls))
    assert out["ran"] == "operator_rewrite" and out["done"] == ["OPR"]
    assert [r["symbol"] for r in store.read_queue(base)["items"]] == ["SCH"]  # the trigger row waits for a window
    assert out["enqueued"] == 0


def test_off_window_without_operator_rows_does_nothing(cfg, root):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": "SCH", "scope": "holding", "priority": 100, "reason": "material_news"}])
    calls = []

    def no_sources(r, ro):
        raise AssertionError("an idle fire must not read the house stores")
    out = PW.run(args(now="2026-10-26T15:00:00Z"), cfg, root, sources_factory=no_sources,
                 run_queue_fn=fake_run_queue(calls))
    assert out["ran"] == "nothing_due" and calls == [] and out["produced_count"] == 0


def tree(path: Path) -> dict:
    return {str(p.relative_to(path)): p.stat().st_mtime_ns for p in path.rglob("*")} if path.exists() else {}


def test_window_dry_run_writes_nothing(cfg, root):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": "OPR", "scope": "watch", "priority": 1, "reason": "operator_refresh"}])
    before = tree(root)
    src = FakeSources(holdings={"AAA": {"market_value": 1.0}}, bars={"AAA": bars(100, 120)})
    out = PW.run(args(apply=False, now="2026-10-26T21:50:00Z"), cfg, root, sources_factory=lambda r, ro: src)
    assert out["mode"] == "dry_run" and out["window"] == "post_close"
    assert [r["symbol"] for r in out["would_enqueue"]] == ["AAA"]
    assert tree(root) == before


# ── delivery ──────────────────────────────────────────────────────────────────────────────────────────────────
class Stubs:
    def __init__(self, fail_text=False, fail_mail=False):
        self.texts, self.docs, self.mails = [], [], []
        self.fail_text, self.fail_mail = fail_text, fail_mail

    def text(self, msg):
        self.texts.append(msg)
        return not self.fail_text

    def doc(self, path, caption):
        assert Path(path).is_file()
        self.docs.append((Path(path).name, caption))
        return True

    def mail(self, subject, body):
        self.mails.append((subject, body))
        return not self.fail_mail


def run_window(cfg, root, syms, *, now="2026-10-26T21:50:00Z", big=False, scope="holding"):
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": s, "scope": scope, "priority": 100 + i, "reason": "monthly_due"}
                      for i, s in enumerate(syms)])
    return PW.run(args(now=now), cfg, root, sources_factory=lambda r, ro: FakeSources(),
                  run_queue_fn=fake_run_queue([], big=big))


def test_delivery_telegram_files_email_audit_and_idempotent(cfg, root):
    run_window(cfg, root, ["AAA", "BBB"])
    s = Stubs()
    out, code = PD.run(True, cfg, root, send_text=s.text, send_document=s.doc, send_email=s.mail)
    assert code == 0 and len(s.texts) == 1 and len(s.mails) == 1
    assert sorted(n for n, _ in s.docs) == ["prospectus.docx", "prospectus.docx", "prospectus.pdf", "prospectus.pdf"]
    msg = s.texts[0]
    assert "AAA" in msg and "CIO conviction 71" in msg and "monthly_due" in msg and "gate not gated" in msg
    assert "https://ms01-openclaw.tail163d14.ts.net/v3/prospectus/AAA" in msg
    subject, body = s.mails[0]
    assert "run cost $1.00" in subject and "Month to date (2026-10): $1.00" in body
    assert "no attachments" not in body and "PDF and Word files are on the Prospectus page" in body
    assert "account" not in (msg + body).lower()
    base = base_of(root, cfg)
    assert delivery.pending_outbox(base) == [] and list(delivery.sent_dir(base).glob("*.json"))
    # rerun: nothing pending, nothing sent again
    s2 = Stubs()
    PD.run(True, cfg, root, send_text=s2.text, send_document=s2.doc, send_email=s2.mail)
    assert s2.texts == s2.docs == s2.mails == []


def test_verdict_change_in_email_audit(cfg, root):
    run_window(cfg, root, ["AAA"])
    PD.run(True, cfg, root, **dict(zip(("send_text", "send_document", "send_email"),
                                       (lambda *a: True, lambda *a: True, lambda *a: True))))
    run_window(cfg, root, ["AAA"], now="2026-10-27T21:50:00Z")
    s = Stubs()
    PD.run(True, cfg, root, send_text=s.text, send_document=s.doc, send_email=s.mail)
    body = s.mails[0][1]
    assert "Verdict CHANGED. Was: AAA synthetic verdict v1" in body and "Now: AAA synthetic verdict v2" in body
    assert "Month to date (2026-10): $1.00" in body


def test_over_ten_reports_attach_holdings_and_link_watch(cfg, root):
    run_window(cfg, root, [f"H{i:02d}" for i in range(6)])
    base = base_of(root, cfg)
    seed_queue(base, [{"symbol": f"W{i:02d}", "scope": "watch", "priority": 1000, "reason": "missing"} for i in range(6)])
    PW.run(args(now="2026-10-26T21:50:00Z", window="post_close"), cfg, root, sources_factory=lambda r, ro: FakeSources(),
           run_queue_fn=fake_run_queue([]))
    # merge both runs into one record to exercise > 10 in one window
    recs = [json.loads(p.read_text()) for p in delivery.pending_outbox(base)]
    merged = dict(recs[0], items=recs[0]["items"] + recs[1]["items"])
    plan = delivery.plan_telegram(merged, cfg, delivery.read_ledger(base), base)
    attached = {d["key"].split("@")[0] for d in plan["documents"]}
    assert attached == {f"H{i:02d}" for i in range(6)}
    assert {f"W{i:02d}" for i in range(6)} <= set(plan["linked_only"])


def test_watch_scope_toggle_and_size_cap(cfg, root):
    off = json.loads(json.dumps(cfg))
    off["delivery"]["scopes"]["watch"] = False
    run_window(off, root, ["WWW"], scope="watch")
    s = Stubs()
    PD.run(True, off, root, send_text=s.text, send_document=s.doc, send_email=s.mail)
    assert s.texts == [] and s.docs == []
    big_root = root.parent / "big"
    run_window(cfg, big_root, ["BIG"], big=True)
    s = Stubs()
    PD.run(True, cfg, big_root, send_text=s.text, send_document=s.doc, send_email=s.mail)
    assert [n for n, _ in s.docs] == ["prospectus.pdf"] and "BIG DOCX (over 50 MB)" in s.texts[0]


def test_failure_retries_then_alerts_once(cfg, root):
    run_window(cfg, root, ["AAA"])
    for attempt in range(3):
        s = Stubs(fail_mail=True)
        out, code = PD.run(True, cfg, root, send_text=s.text, send_document=s.doc, send_email=s.mail)
        assert code == 1
        if attempt == 0:
            assert s.docs  # Telegram still delivered on the first attempt
        else:
            assert not s.docs  # never re-sent
    assert out["stuck"] and any("delivery FAILED" in t for t in s.texts)
    assert delivery.pending_outbox(base_of(root, cfg))  # kept for retry
    s = Stubs(fail_mail=True)
    out, _ = PD.run(True, cfg, root, send_text=s.text, send_document=s.doc, send_email=s.mail)
    assert out["stuck"] == [] and not any("delivery FAILED" in t for t in s.texts)  # alerted once


def test_deliver_dry_run_sends_nothing(cfg, root):
    run_window(cfg, root, ["AAA"])
    before = tree(root)

    def boom(*a):
        raise AssertionError("dry run must not send")
    out, code = PD.run(False, cfg, root, send_text=boom, send_document=boom, send_email=boom)
    assert code == 0 and out["mode"] == "dry_run" and out["records"][0]["telegram"]["documents"] == 2
    assert tree(root) == before


def test_sender_uses_chokepoints_only():
    src = (ROOT / "scripts" / "prospectus_deliver.py").read_text(encoding="utf-8")
    assert "from telegram_alert import send_telegram, send_telegram_document" in src
    assert "from email_notifier import send_email" in src
    for raw in ("api.telegram.org", "requests.", "urllib", "sendDocument", "smtp" + "lib", "subprocess"):
        assert raw not in src
    lib = (ROOT / "scripts/lib/prospectus/delivery.py").read_text(encoding="utf-8")
    assert "import telegram_alert" not in lib and "email_notifier import" not in lib


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config/ci_gates/prospectus_schedule_delivery_20261026.json").read_text())
    assert ci_gates.validate(doc, stem="prospectus_schedule_delivery_20261026")


def test_deliver_lane_registered_and_units_shipped():
    rows = json.loads((ROOT / "config/lane_registry.json").read_text())["lanes"]
    row = next(r for r in rows if r["lane_id"] == "prospectus-deliver")
    assert row["scheduler"] == {"kind": "systemd", "expression": "tradeai-prospectus-deliver.timer"}
    unit = (ROOT / "config/systemd/user/tradeai-prospectus-deliver.service").read_text()
    assert "prospectus_deliver.py --apply" in unit and "portfolio-server/CURRENT" in unit
    assert (ROOT / "config/systemd/user/tradeai-prospectus-deliver.timer").is_file()
