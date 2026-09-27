"""P2 audit remediation: cron hygiene CLI (R-10), grant consumption (C-10), Maria desk-exchange lineage (C-05)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_r10_detector_cli_reports_wakes_without_shell_quoting(monkeypatch, capsys):
    cli = _load("scripts/cio_event_detector_cli.py", "_p2_detector_cli")
    fake = SimpleNamespace(run_cio_event_detector_once=lambda: {"wakes_created": 3, "events_seen": 7})
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_event_detector", fake)
    assert cli.main(["--period", "weekly"]) == 0
    assert capsys.readouterr().out.strip() == "[weekly] Wakes: 3"
    assert cli.main(["--period", "monthly", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"period": "monthly", "wakes_created": 3, "events_seen": 7}


def test_c10_preflight_consumes_one_use_only_when_allowed(monkeypatch, tmp_path):
    pf = _load("scripts/release_grant_preflight.py", "_p2_preflight")
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout='noise\n{"tier": "release-write", "uses_left": 2}\n', stderr="")
    ledger = tmp_path / "guard_ledger.py"; ledger.write_text("# stub\n")
    monkeypatch.setattr(pf, "GUARD_LEDGER", ledger)
    out = pf.consume_release_grant(runner=runner)
    assert out["ok"] is True and out["ledger"]["uses_left"] == 2
    assert calls[0][1:] == [str(ledger), "consume", "--tier", "release-write"]
    monkeypatch.setenv("TRADEAI_GUARD_CONSUME", "0")
    assert pf.consume_release_grant(runner=runner)["skipped"] == "disabled"
    monkeypatch.delenv("TRADEAI_GUARD_CONSUME")
    monkeypatch.setattr(pf, "GUARD_LEDGER", tmp_path / "missing.py")
    assert pf.consume_release_grant(runner=runner)["skipped"] == "guard_ledger.py absent"
    boom = lambda *a, **k: (_ for _ in ()).throw(OSError("no exec"))  # noqa: E731
    monkeypatch.setattr(pf, "GUARD_LEDGER", ledger)
    assert pf.consume_release_grant(runner=boom)["ok"] is False
    src = (ROOT / "scripts" / "release_grant_preflight.py").read_text(encoding="utf-8")
    assert 'out["consumed"] = consume_release_grant()' in src


def test_c10_pre_push_consumes_unless_shell_guard_did():
    src = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "guard_ledger.py consume --tier git-push" in src
    assert "TRADEAI_GUARD_CONSUMED_BY_SHELL" in src and 'TRADEAI_GUARD_CONSUME:-1' in src
    # the consume sits inside the guard_ok branch, after override=1
    branch = src.split('if [[ "$guard_ok" == "1" ]]; then', 1)[1].split("\nfi\n", 1)[0]
    assert "override=1" in branch and "consume --tier git-push" in branch


def test_c05_maria_exchange_receipt_written_with_desk_text_not_rewrite(tmp_path):
    mp = _load("scripts/lib/maria_parity_hook.py", "_p2_maria_hook")
    path = tmp_path / "ex.jsonl"
    desk = ("🎯 *SCHD — re-entry check* _(READ_ONLY)_\nPrice $33.12 …\nDecision integrity: *INVALIDATED_BY_PRICE_OR_STOP* — no actionable mechanics\n"
            "Watch alert: none armed — nothing is monitored from this chat; ask to arm a price-cross alert.")
    rid = mp.record_desk_exchange(question="...fallen 4.6% to $33.68... whats CIO prepective on rentry",
                                  chat_id="8797974247", message_id="tg:54321", channel="skill",  # hardcode-ok: fixture asserting lineage capture of the desk chat id
                                  desk_text=desk, result={"symbols": ["SCHD"]}, path=path)
    assert rid and rid.startswith("mdx_")
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    r = rows[0]
    assert r["schema"] == "MariaDeskExchange@v1" and r["receipt_id"] == rid
    assert r["decision_integrity_state"] == "INVALIDATED_BY_PRICE_OR_STOP"
    assert r["alert_armed"] is False and r["symbols"] == ["SCHD"]
    assert "33.68" in r["question_excerpt"] and len(r["question_sha16"]) == 16
    assert r["prose_author"].startswith("downstream LLM")
    # never raises into Maria's reply
    assert mp.record_desk_exchange(question="q", chat_id="", message_id="", channel="skill",
                                   desk_text="x", path=tmp_path / "no" / "dir" / "x.jsonl") is not None
    bad = tmp_path / "ro"; bad.write_text("file, not a dir")
    assert mp.record_desk_exchange(question="q", chat_id="", message_id="", channel="skill",
                                   desk_text="x", path=bad / "x.jsonl") is None


def test_c05_hook_records_exchange_on_the_return_path():
    src = (ROOT / "scripts" / "lib" / "maria_parity_hook.py").read_text(encoding="utf-8")
    assert 'out["exchange_receipt_id"] = record_desk_exchange(' in src
    assert src.index("scrub_maria_outbound(\n        body") < src.index('out["exchange_receipt_id"]')
