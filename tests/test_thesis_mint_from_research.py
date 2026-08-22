"""Mint dry-run grades CURRENT vs THIN. No live cio_theses.jsonl writes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import thesis_mint_from_research as mint
from scripts.lib.thesis_substantiveness import grade_text, join_research_text, pass_fixture


def test_would_say_is_not_truncated_to_400():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    assert '"would_say": mint_body,' in src
    assert '"would_say": mint_body[:400]' not in src
    assert "would_say_preview" in src


def test_summary_caps_but_keeps_pass_floor():
    text = pass_fixture("JEPI") + " extra clause " * 80
    s = mint._summary_from_rec("JEPI", text, cap=2000)
    assert "JEPI" in s
    assert len(s) <= 2000
    assert len(s) >= 400
    assert grade_text("JEPI", s)["coverage_state"] == "CURRENT"


def test_would_mint_state_thin_not_current_on_short_rec():
    rec = "CSWC: Hold / watch. Insufficient evidence to act."
    g = grade_text("CSWC", mint._summary_from_rec("CSWC", rec))
    assert g["coverage_state"] == "THIN"
    assert g["would_mint"] is True


def test_apply_live_flag_exists_and_warns():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    assert "--apply-live" in src
    assert "cio_theses.jsonl" in src
    assert "apply_after" in src
    assert "substantiveness" in src
    assert "LIVE_APPLY_WARNING" in src
    assert "WRITES TO THE LIVE CIO THESIS STORE" in src
    assert "notify=True" in src
    assert "notify=False" in src
    assert "trade-ai-releases/portfolio-server/CURRENT" in src
    assert "emit_desk_card=True" in src
    help_p = subprocess.run(
        [sys.executable, str(ROOT / "scripts/thesis_mint_from_research.py"), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_p.returncode == 0
    assert "--apply-live" in help_p.stdout
    assert "--apply-staging" in help_p.stdout


def test_joined_body_is_preferred_over_rec_only():
    rec = "PFLT: Hold."
    joined = join_research_text(
        rec,
        "Counter-view: credit spread widening.",
        [{"tag": "fact", "text": pass_fixture("PFLT")}],
    )
    g_rec = grade_text("PFLT", mint._summary_from_rec("PFLT", rec))
    g_join = grade_text("PFLT", mint._summary_from_rec("PFLT", joined))
    assert g_rec["coverage_state"] != "CURRENT"
    assert g_join["coverage_state"] == "CURRENT"


def test_mint_state_grades_joined():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    assert "g_mint = g_joined if summary_joined else g_rec" in src
    assert "g_mint = g_rec\n" not in src
    assert "rec_only" in src
    assert "split_joined" in src
    assert "grade_rec_only" in src
    assert "grade_joined" in src


def test_notify_true_only_for_apply_live():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    staging_mark = "# P4: staging stays silent. notify=False"
    live_mark = "# P4: live apply uses CIOThesisStore.publish notify=True"
    assert staging_mark in src
    assert live_mark in src
    staging_idx = src.index(staging_mark)
    live_idx = src.index(live_mark)
    staging_block = src[staging_idx:live_idx]
    live_block = src[live_idx : live_idx + 800]
    assert "notify=False" in staging_block
    assert "notify=True" not in staging_block
    assert "notify=True" in live_block


def test_publish_cards_notify_passthrough():
    class FakeStore:
        def __init__(self):
            self.calls = []

        def publish(self, *_a, **kw):
            self.calls.append(kw)

    cards = [{
        "would_mint": True,
        "would_say": "JEPI income sleeve: overlay yield, invalidate if NAV thesis breaks.",
        "symbol": "JEPI",
        "bucket": "T0-HOLD",
        "research_id": 1,
        "research_lane": "deepseek",
        "would_mint_state": "THIN",
        "grade_mint": "B",
        "grade_joined": "B",
        "grade_rec_only": "C",
        "mint_grade_source": "joined",
    }]
    live = FakeStore()
    n = mint._publish_mint_cards(
        cards, live, notify=True, dry_run=False, apply_live=True,
        actor_id="thesis_mint_from_research", change_note="LIVE",
    )
    assert n == 1
    assert live.calls[0]["notify"] is True
    assert live.calls[0]["extra"]["apply_live"] is True
    staging = FakeStore()
    mint._publish_mint_cards(
        cards, staging, notify=False, dry_run=True, apply_live=False,
        actor_id="thesis_mint_dryrun", change_note="DRY",
    )
    assert staging.calls[0]["notify"] is False
    assert staging.calls[0]["extra"]["dry_run"] is True


def test_live_paths_point_at_current_not_worktree():
    assert "CURRENT" in str(mint.LIVE_EVENTS)
    assert "tradeai-wt-" not in str(mint.LIVE_EVENTS)
    assert mint.LIVE_EVENTS.name == "cio_theses.jsonl"


def test_kind_for_card():
    assert mint._kind_for_card({"live_state": "RESEARCH_REQUIRED", "would_mint_state": "CURRENT"}) == "minted"
    assert mint._kind_for_card({"live_regrade": "THIN", "would_mint_state": "CURRENT"}) == "upgraded"
    assert mint._kind_for_card({"live_regrade": "CURRENT", "would_mint_state": "THIN"}) == "downgraded"


def test_write_thesis_change_card_jsonl(tmp_path, monkeypatch):
    from scripts.lib.cio_held_thesis_coverage import write_thesis_change_card

    p = tmp_path / "thesis_change_cards.jsonl"
    monkeypatch.setenv("THESIS_CHANGE_CARDS_PATH", str(p))
    monkeypatch.delenv("CIO_THESIS_BUS", raising=False)
    card = write_thesis_change_card(
        symbol="NOC",
        thesis_id="symbol_noc",
        version=1,
        kind="minted",
        summary="NOC: defense-electronics cash conversion; invalidate if backlog rolls off.",
        mint_state="CURRENT",
        grade="A",
        emit_bus=False,
    )
    assert card["kind"] == "minted"
    assert card["symbol"] == "NOC"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["schema"] == "ThesisChangeCard@v1"
