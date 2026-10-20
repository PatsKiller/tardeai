"""General notification display fixtures: no AT engine, provider, secrets or sends."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import scripts.lib.comms_editor as ce
from lib import momentum_setup_evidence as evidence
from lib.scanner_candidate_projection import build_candidate_projection

# Load the exact source as a test module, matching rich-wiring fixtures. The
# existing public chokepoint is exercised below; its raw delivery is always inert.
spec = importlib.util.spec_from_file_location(
    "momentum_notification_transport_fixture", ROOT / "scripts/telegram_transport.py"
)
tt = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tt)

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def fixture_transport(tmp_path, monkeypatch, editor_mode="live"):
    original = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD\nAdvisory observation"
    row = {
        "symbol": "ABCD",
        "price": 12,
        "float_m": 8,
        "rvol": 6,
        "gap_pct": 7,
        "decision": "WAIT",
        "run_id": "2026-10-12::0900",
        "observed_at": "2026-10-12T14:30:00+00:00",
        "catalyst": "ABCD upgraded to BUY",
        "catalyst_source": "synthetic-news",
        "catalyst_verified": True,
        "catalyst_at": "2026-10-12T14:00:00+00:00",
    }
    snapshot = build_candidate_projection(
        {"run_id": row["run_id"], "latest_run_timestamp": row["observed_at"], "tickers": [row]}, [], now=NOW
    )
    calls = []
    enrich = evidence.enrich_active_trader_notification
    monkeypatch.setattr(
        evidence,
        "enrich_active_trader_notification",
        lambda text, **kw: (
            calls.append(("annotate", text)) or enrich(text, now=NOW, snapshot_loader=lambda: snapshot, **kw)
        ),
    )
    q = lambda *a, **k: [{"symbol": "ABCD", "action": "AVOID", "created_at": "2026-10-12T14:00:00+00:00"}]
    resolve = lambda text: [{"symbol": "ABCD", "guid": "11111111-2222-3333-4444-555555555555"}]
    ledger = ce.DuplicateLedger(tmp_path / "ledger.json")

    def edit(text, **kwargs):
        calls.append(("editor", text))
        return ce.edit(text, now=NOW, ledger=ledger, resolve=resolve, editor_mode=editor_mode, **kwargs)

    def commit(decision, chat_id):
        return ce.commit(decision, chat_id=chat_id, now=NOW, ledger=ledger, receipts=tmp_path / "receipts.jsonl")

    fake_ce = SimpleNamespace(mode=lambda: editor_mode, edit=edit, commit=commit, default_db_query=q)
    monkeypatch.setattr(tt, "_blocked", lambda grant: False)
    monkeypatch.setattr(tt, "_comms_editor", lambda: fake_ce)
    monkeypatch.setattr(
        tt, "_deliver_text_raw", lambda **kw: calls.append(("raw", kw)) or {"ok": True, "response": {}, "message_id": 1}
    )
    return tt.deliver_text, original, calls


def test_annotation_after_editor_preserves_stance_and_duplicate(tmp_path, monkeypatch):
    send, original, calls = fixture_transport(tmp_path, monkeypatch)
    first = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert first["ok"] and not first.get("suppressed")
    assert [c[1] for c in calls if c[0] == "editor"] == [original]
    sent = [c[1] for c in calls if c[0] == "raw"]
    assert len(sent) == 1 and "ABCD upgraded to BUY" in sent[0]["text"]
    assert "Momentum evidence (advisory)" in sent[0]["text"]
    assert first["comms_editor"]["fingerprint"] == ce.fingerprint(original)
    duplicate = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert duplicate["suppressed"] == "duplicate"
    assert len([c for c in calls if c[0] == "raw"]) == 1
    assert len([c for c in calls if c[0] == "annotate"]) == 1


def test_original_cio_hold_remains_held_without_any_annotation_or_send(tmp_path, monkeypatch):
    send, original, calls = fixture_transport(tmp_path, monkeypatch)
    original += "\nABCD BUY"
    out = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert out["suppressed"] == "cio_disagreement"
    assert not [c for c in calls if c[0] in {"raw", "annotate"}]


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_mode_decisions_keep_original_editor_inputs(tmp_path, monkeypatch, mode):
    send, original, calls = fixture_transport(tmp_path, monkeypatch, mode)
    out = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert out["ok"] and not out.get("suppressed")
    assert [c[1] for c in calls if c[0] == "editor"] == ([original] if mode == "shadow" else [])
    assert "ABCD upgraded to BUY" in [c[1] for c in calls if c[0] == "raw"][0]["text"]


def test_metadata_renderer_failure_preserves_existing_accepted_delivery(tmp_path, monkeypatch):
    send, original, calls = fixture_transport(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        calls.append(("failed_annotation", True))
        raise RuntimeError("synthetic renderer failure")

    monkeypatch.setattr(evidence, "enrich_active_trader_notification", unavailable)
    out = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert out["ok"] and not out.get("suppressed")
    payload = [c[1] for c in calls if c[0] == "raw"][0]
    assert "Momentum evidence (advisory)" not in payload["text"]
    assert "Advisory observation" in payload["text"]
    assert out["comms_editor"]["fingerprint"] == ce.fingerprint(original)
    assert len([c for c in calls if c[0] == "failed_annotation"]) == 1


def test_notification_interdict_returns_before_editor_annotation_and_raw(tmp_path, monkeypatch):
    send, original, calls = fixture_transport(tmp_path, monkeypatch)
    monkeypatch.setattr(tt, "_blocked", lambda grant: True)
    out = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    assert not [c for c in calls if c[0] in {"editor", "annotate", "raw"}]
    assert out.get("suppressed") is not None or not out["ok"]


def test_acceptance_context_cannot_override_a_different_explicit_subject(tmp_path, monkeypatch):
    send, original, calls = fixture_transport(tmp_path, monkeypatch)
    original = original.replace("Symbol: ABCD", "Symbol: WXYZ")
    out = send(token="synthetic", chat_id="fixture", text=original, primary_symbols=["ABCD"])
    payload = [c[1] for c in calls if c[0] == "raw"][0]
    assert out["ok"] and not out.get("suppressed")
    # Operator 2026-10-19 ("drop from the alert, why have a false positive"): with no current same-symbol
    # evidence the appendix is omitted entirely — no "UNKNOWN" line. Nothing is borrowed either way.
    assert "Momentum evidence (advisory)" not in payload["text"]
    assert "ABCD upgraded to BUY" not in payload["text"]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:password@example.test/a",
        "https://news.example/line\nfeed",
        "https://news.example/<b>text</b>",
        "https://news.example/" + "a" * 1001,
    ],
)
def test_malformed_source_url_stays_unknown_without_truncation(url):
    row = {"symbol": "ABCD", "catalyst_url": url}
    out = evidence.build_setup_evidence(row, now=NOW)
    assert out["catalyst"]["url"] is None


def test_safe_source_url_is_preserved_exactly_for_shared_view():
    url = "https://news.example/clinical_result?first=1&second=2"
    assert evidence.build_setup_evidence({"catalyst_url": url}, now=NOW)["catalyst"]["url"] == url


def test_annotation_utf16_bound_preserves_original_body():
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD\n" + "😀" * 1970
    result = evidence.enrich_active_trader_notification(
        message, primary_symbols=[], snapshot_loader=lambda: None, now=NOW
    )
    assert 3950 < len(message.encode("utf-16-le")) // 2 <= 4000
    assert result == message


def test_html_catalyst_display_is_escaped_after_acceptance(monkeypatch):
    row = {
        "symbol": "ABCD",
        "price": 12,
        "float_m": 8,
        "rvol": 6,
        "gap_pct": 7,
        "decision": "WAIT",
        "run_id": "2026-10-12::0900",
        "observed_at": "2026-10-12T14:30:00+00:00",
        "catalyst": "Fixture <b>news</b> & result",
        "catalyst_source": "fixture-news",
        "catalyst_verified": True,
        "catalyst_at": "2026-10-12T14:00:00+00:00",
    }
    snapshot = build_candidate_projection(
        {"run_id": row["run_id"], "latest_run_timestamp": row["observed_at"], "tickers": [row]}, [], now=NOW
    )
    original = "<b>ACTIVE TRADER · SCALP ALERT</b>\nSymbol: ABCD"
    out = evidence.enrich_active_trader_notification(
        original, primary_symbols=["ABCD"], snapshot_loader=lambda: snapshot, now=NOW
    )
    assert out.startswith(original) and "Fixture bnews/b &amp; result" in out
    assert "<b>news</b>" not in out and "Published:" in out and "observed" in out
    assert "2026-10-12T14:00:00+00:00" in out
