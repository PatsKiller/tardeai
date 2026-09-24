"""Maria outbound gate — OpenClaw ``message_sending`` bridge (M5 Module 3).

Operator decision 2026-09-23: "hook Maria through the gateway". The fixture is
Maria's real 2026-09-23 12:26Z reply about S: fake "🔍 Iris" / "🎯 Alex"
sections with agentToAgent forbidden, "0 recent findings" beside a completed
desk result (res_c3a661c21740), and no Sources / LEGEND / 🆔 footer.

Offline only: stub resolver, stub ``cio_decisions`` query, tmp CIO stores.
No psycopg2, no network. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import maria_outbound_gate as mg  # noqa: E402
from scripts.lib import specialist_attribution as sa  # noqa: E402
from scripts.lib.reply_provenance import LEGEND  # noqa: E402

COVERS = [
    "scripts/lib/maria_outbound_gate.py",
    "scripts/maria_outbound_gate.py",
    "scripts/lib/specialist_attribution.py",
]

FIXTURE = ROOT / "tests" / "fixtures" / "maria_outbound_gate" / "maria_s_reply_20260923T1226Z.txt"
POLICY_NOTICE = (
    "🔒 Direct agent-to-agent delegation is currently restricted by policy. "
    "Current assessment rendered from stored CIO decisions."
)
GUIDS = {
    "S": "84601d7d-ae35-5dc7-b664-1b77ad8ea57e",
    "NOC": "0bcf1ac9-0000-5000-8000-000000000001",
    "XYZ": "7a7a7a7a-0000-5000-8000-000000000002",
}

THIN_RESULT = {
    "event": "HERMES_RESEARCH_COMPLETED",
    "result_id": "rr_06fb7ccbc798",
    "research_id": "res_c3a661c21740",
    "status": "completed",
    "symbol": "S",
    "thesis_stance": "INSUFFICIENT_DATA",
    "summary": "INSUFFICIENT_DATA — thin packet",
    "findings": [{"id": "f1", "text": "INSUFFICIENT_DATA: off-symbol RAG only."}],
}


def _resolve(text: str) -> list[dict]:
    out = []
    for sym, guid in GUIDS.items():
        import re

        if re.search(rf"(?<![A-Za-z]){sym}(?![A-Za-z])", text):
            out.append({"symbol": sym, "guid": guid, "kind": "ticker"})
    return out


def _db(actions: dict[str, str]):
    def query(sql, params=None, fetch="all"):
        wanted = {str(s).upper() for s in (params[0] if params else [])}
        return [
            {"symbol": s, "action": a, "status": "ok", "created_at": "2026-09-23T10:00:00+00:00"}
            for s, a in actions.items() if s in wanted
        ]
    return query


@pytest.fixture()
def cio_dir(tmp_path, monkeypatch):
    d = tmp_path / "cio"
    d.mkdir()
    (d / "hermes_research_results.jsonl").write_text(json.dumps(THIN_RESULT) + "\n", encoding="utf-8")
    (d / "cio_operator_gap_requests.jsonl").write_text("", encoding="utf-8")
    (d / "cio_operator_pending_replies.jsonl").write_text("", encoding="utf-8")

    class _FakeHR:
        @staticmethod
        def _load_projection():
            return {"by_research_id": {"res_c3a661c21740": {"symbol": "S", "status": "completed"}}}

    monkeypatch.setitem(sys.modules, "scripts.lib.cio_hermes_research", _FakeHR)
    monkeypatch.setitem(sys.modules, "lib.cio_hermes_research", _FakeHR)
    monkeypatch.setenv("CIO_STANCE_HOLD_RECEIPTS_DISABLE", "1")
    monkeypatch.delenv("MARIA_GATE_RECEIPTS", raising=False)
    return d


def test_real_s_reply_is_scrubbed_corrected_and_footed(cio_dir):
    raw = FIXTURE.read_text(encoding="utf-8")
    res = mg.gate(raw, session_key="agent:maria:telegram:direct:8797974247", to="8797974247",  # hardcode-ok: fixture asserts Maria-chat routing
                  db_query=_db({}), resolve=_resolve, cio_dir=cio_dir)
    out = res.content
    # specialist roleplay stripped, exact policy notice once
    assert "🔍 Iris —" not in out and "🎯 Alex —" not in out
    assert out.count(POLICY_NOTICE) == 1
    assert len(res.stripped_claims) == 2
    # the 0-findings lie is replaced by the join, citing the desk research id
    assert "0 recent findings" not in out
    assert "500 deep" not in out
    assert "res_c3a661c21740" in out and "analyzed-thin" in out
    assert res.honesty_corrections and res.honesty_corrections[0]["symbol"] == "S"
    # LEGEND first, 🆔 footer with the S GUID, Sources + authority tail last
    assert out.startswith(LEGEND)
    assert "🆔 " in out and "S:84601d7d" in out
    lines = out.rstrip().split("\n")
    assert any(ln.startswith("Sources: ") for ln in lines)
    assert "READ_ONLY_ADVISORY" in lines[-1]
    # sizing advice is flagged on the receipt (MBI_BEHAVIOR = 0), text untouched
    assert "starter size" in " ".join(res.sizing_flags)
    assert not res.held and res.errors == []


def test_bullish_vs_avoid_is_held_with_notice_not_silence(cio_dir):
    raw = "NOC looks like a BUY here — strong setup into earnings."
    res = mg.gate(raw, db_query=_db({"NOC": "AVOID"}), resolve=_resolve, cio_dir=cio_dir)
    assert res.held and res.held_reason == "cio_stance_conflict"
    assert "⛔ Held by the CIO stance gate" in res.content
    assert "strong setup" not in res.content
    assert "[CIO Stance: NOC AVOID — held]" in res.content
    out = mg.handle({"content": raw, "mode": "live"}, db_query=_db({"NOC": "AVOID"}),
                    resolve=_resolve, cio_dir=cio_dir)
    assert out["cancel"] is False and out["content"].startswith(LEGEND)


def test_bullish_with_missing_cio_row_fails_closed(cio_dir):
    res = mg.gate("XYZ is a BUY.", db_query=_db({}), resolve=_resolve, cio_dir=cio_dir)
    assert res.held and res.held_reason == "cio_decision_missing"
    assert "[CIO Stance: XYZ MISSING — held]" in res.content


def test_bullish_vs_neutral_cio_is_rewritten_to_watch_and_sent(cio_dir):
    res = mg.gate("NOC is a BUY into the print.", db_query=_db({"NOC": "RESEARCH_MORE"}),
                  resolve=_resolve, cio_dir=cio_dir)
    assert not res.held
    assert "BUY" not in res.content.split("\n\n")[1]
    assert "[CIO Stance: NOC RESEARCH_MORE — Action rewritten to WATCH]" in res.content
    assert res.stance[0]["outcome"] == "rewritten_to_watch"


def test_bullish_aligned_is_stamped_and_sent(cio_dir):
    res = mg.gate("NOC is a BUY.", db_query=_db({"NOC": "BUY"}), resolve=_resolve, cio_dir=cio_dir)
    assert not res.held and "[CIO Stance: NOC BUY]" in res.content


def test_bearish_read_is_stamped_never_held(cio_dir):
    res = mg.gate("I'd AVOID NOC for now.", db_query=_db({"NOC": "BUY"}), resolve=_resolve,
                  cio_dir=cio_dir)
    assert not res.held
    assert "[CIO Stance: NOC BUY — reply reads bearish; CIO disagrees]" in res.content


def test_hyphen_compound_is_not_a_stance(cio_dir):
    res = mg.gate("S is the up-sell narrative this quarter.", db_query=_db({}),
                  resolve=_resolve, cio_dir=cio_dir)
    assert res.stance == [] and not res.held


def test_plain_reply_gets_provenance_and_no_stance(cio_dir):
    res = mg.gate("Reminder set for Dec 8.", db_query=_db({}), resolve=_resolve, cio_dir=cio_dir)
    assert res.content.startswith(LEGEND)
    assert "Sources: none" in res.content and not res.held


def test_empty_content_passes_through(cio_dir):
    res = mg.gate("   ", db_query=_db({}), resolve=_resolve, cio_dir=cio_dir)
    assert res.content == "   " and not res.changed


def test_idempotent_on_already_gated_text(cio_dir):
    first = mg.gate(FIXTURE.read_text(encoding="utf-8"), db_query=_db({}), resolve=_resolve,
                    cio_dir=cio_dir).content
    second = mg.gate(first, db_query=_db({}), resolve=_resolve, cio_dir=cio_dir).content
    assert second.count(POLICY_NOTICE) == 1
    assert second.count("🆔 ") == 1
    assert second.count("Sources: ") == 1
    assert second.count(LEGEND) == 1


def test_header_claim_detector_keeps_desk_product_voice():
    txt, dec = sa.scrub_operator_specialist_claims(
        "Alex · CIO desk\n**🔍 Iris — research**\nbody", surface="desk")
    assert "Alex · CIO desk" in txt and "Iris —" not in txt
    assert dec.stripped_claims == ["**🔍 Iris — research**"]


def test_receipts_never_written_under_pytest_without_explicit_path(cio_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_DIR", str(tmp_path / "state"))
    assert mg.receipts_path() is None
    target = tmp_path / "r.jsonl"
    monkeypatch.setenv("MARIA_GATE_RECEIPTS", str(target))
    mg.handle({"content": "NOC is a BUY.", "mode": "observe", "sessionKey": "agent:maria:x"},
              db_query=_db({"NOC": "BUY"}), resolve=_resolve, cio_dir=cio_dir)
    row = json.loads(target.read_text(encoding="utf-8").splitlines()[-1])
    assert row["mode"] == "observe" and row["applied"] is False
    assert row["schema"] == mg.SCHEMA and "content" not in row


def test_cli_reports_error_json_on_bad_input():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "maria_outbound_gate.py")],
                          input="[1,2]", capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "MARIA_GATE_RECEIPTS": "off"})
    assert proc.returncode == 1
    assert "error" in json.loads(proc.stdout)
