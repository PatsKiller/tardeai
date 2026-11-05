"""Design workflow (AGENTS.md §28.13, design/README.md, operator-approved 2026-10-25).

tokens.json is THE source and renders tokens.css byte-identically; design/registry.json and every version status
validate; v001 carries the back-filled 10-24 approvals; committed design text passes the public-repo privacy scan.
Hermetic: reads repo files and tmp copies only.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import gen_design_tokens as gen
from scripts import check_design_registry as cli
from scripts.lib import design_pages as dp

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "apps/command-center-v3/src/styles/tokens.css"


def _tokens() -> dict:
    return json.loads((ROOT / "design/system/tokens.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- tokens.json -> tokens.css


def test_generated_css_is_byte_identical_to_the_committed_stylesheet():
    assert gen.render(_tokens()).encode("utf-8") == CSS.read_bytes()


def test_check_mode_passes_on_the_repo(capsys):
    assert gen.main(["--check"]) == 0
    assert "matches" in capsys.readouterr().out


def test_a_value_change_changes_exactly_that_declaration():
    doc = _tokens()
    doc["themes"]["dark"]["--bg-0"] = "#000000"
    out = gen.render(doc)
    before, after = CSS.read_text(encoding="utf-8").splitlines(), out.splitlines()
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert changed == [("  --bg-0: #0f1117;", "  --bg-0: #000000;")]


def test_unknown_placeholder_and_unused_value_are_refused():
    doc = _tokens()
    doc["layout"].append("  {dark.--nope}")
    with pytest.raises(gen.TokenError, match="unresolved"):
        gen.render(doc)
    doc = _tokens()
    doc["themes"]["dark"]["--orphan"] = "#123456"
    with pytest.raises(gen.TokenError, match="not used"):
        gen.render(doc)


def test_value_cannot_inject_css():
    doc = _tokens()
    doc["themes"]["dark"]["--bg-0"] = "red; } body { display:none"
    with pytest.raises(gen.TokenError):
        gen.render(doc)


def test_check_mode_fails_when_css_drifts(tmp_path):
    doc = _tokens()
    doc["generated_css"] = "design/_tmp_tokens_check.css"
    src = tmp_path / "tokens.json"
    src.write_text(json.dumps(doc), encoding="utf-8")
    target = ROOT / "design/_tmp_tokens_check.css"
    try:
        target.write_text("stale\n", encoding="utf-8")
        assert gen.main(["--check", "--source", str(src)]) == 1
        assert target.read_text(encoding="utf-8") == "stale\n"  # --check never writes
    finally:
        target.unlink(missing_ok=True)


def test_light_theme_values_live_once_and_feed_both_light_blocks():
    css = CSS.read_text(encoding="utf-8")
    light_bg0 = _tokens()["themes"]["light"]["--bg-0"]
    assert css.count(f"--bg-0: {light_bg0};") == 2  # [data-theme="light"] block + prefers-color-scheme block


# ---------------------------------------------------------------- registry + versions


def test_repo_design_folder_validates():
    assert dp.validate(ROOT) == []


def test_every_nav_route_is_registered():
    nav = (ROOT / "apps/command-center-v3/src/components/NavRail.tsx").read_text(encoding="utf-8")
    import re
    routes = set(re.findall(r"\{ to: '([^']+)'", nav))
    registered = {p["route"] for p in dp.load_registry(ROOT)["pages"]}
    assert routes and routes <= registered, sorted(routes - registered)


def test_v001_records_the_operator_10_24_approvals():
    reg = dp.load_registry(ROOT)
    approved = {p["id"] for p in reg["pages"] if p["approved_version"] == "v001"}
    # 22 desk boards cover these pages; plus TradeInView, My questions, Watch row and the site fix package.
    for pid in ("home", "risk", "jobs", "approvals", "rulebook", "watch", "tradeinview", "my-questions", "site", "shell"):
        assert pid in approved
    for page, version, status, vdir in dp.iter_versions(ROOT):
        if version == "v000":  # as-built captures (BASELINE), never approvals
            assert status["state"] == "BASELINE" and status["approval"] is None
            continue
        assert version == "v001" and status["state"] == "APPROVED"
        a = status["approval"]
        assert a["by"] == "operator" and a["at"] == "2026-10-24"
        assert a["kind"] == "recorded in handoff, back-filled 2026-10-25"
        assert a["ref"].startswith('"') and a["ledger"] is None
        assert status["private_assets"]["root"] == f"persistent-state/data/design/pages/{page}"
        assert any(f["role"] in ("mockups", "spec") for f in status["private_assets"]["files"])
        assert "## Removals, hides and moves" in (vdir / "SPEC.md").read_text(encoding="utf-8")


def test_tradeinview_v001_keeps_calendar_and_replay():
    spec = (ROOT / "design/pages/tradeinview/versions/v001/SPEC.md").read_text(encoding="utf-8")
    assert "Journeys · Calendar · Replay · Holding history" in spec
    labels = {r["label"].lower() for r in dp.parse_removals(spec)}
    assert "calendar" not in labels and "replay" not in labels


def test_parse_removals_reads_only_the_removals_section():
    text = '## What changes\n- remove: tab "Nope" — not here\n## Removals, hides and moves\n- move: tab "Evidence" — merged\n- none\n'
    assert dp.parse_removals(text) == [{"action": "move", "kind": "tab", "label": "Evidence"}]


def _copy_design(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "design", tmp_path / "design")
    return tmp_path


def _status(root: Path, page="home"):
    p = root / f"design/pages/{page}/versions/v001/status.json"
    return p, json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate,needle", [
    (lambda s: s.update(state="SHIPPED"), "unknown state"),
    (lambda s: s["approval"].update(by="agent"), "needs approval"),
    (lambda s: s["approval"].update(kind="chat"), "ledger"),
    (lambda s: s["private_assets"]["files"][0].update(path="../../etc/passwd"), "relative"),
    (lambda s: s["private_assets"]["files"][0].update(sha256="0" * 64), "fingerprint does not match"),
    (lambda s: s["private_assets"].update(root="/home/someone/data"), "private_assets.root"),
])
def test_tampered_status_is_refused(tmp_path, mutate, needle):
    root = _copy_design(tmp_path)
    path, status = _status(root)
    mutate(status)
    path.write_text(json.dumps(status), encoding="utf-8")
    assert any(needle in e for e in dp.validate(root)), dp.validate(root)


def test_registry_version_must_match_status(tmp_path):
    root = _copy_design(tmp_path)
    reg_path = root / "design/registry.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    next(p for p in reg["pages"] if p["id"] == "home")["versions"][0]["state"] = "CURRENT"
    reg_path.write_text(json.dumps(reg), encoding="utf-8")
    assert any("state/fingerprint differ" in e for e in dp.validate(root))


def test_proposed_version_without_private_mockup_is_refused(tmp_path):
    root = _copy_design(tmp_path)
    vdir = root / "design/pages/trading/versions/v002"
    vdir.mkdir(parents=True)
    (vdir / "SPEC.md").write_text("# t\n## Removals, hides and moves\n- none\n", encoding="utf-8")
    (vdir / "status.json").write_text(json.dumps({"schema": "DesignVersionStatus@v1", "page": "trading", "version": "v002",
                                                  "state": "PROPOSED", "approval": None, "private_assets": {"files": []}}), encoding="utf-8")
    errs = dp.validate(root)
    assert any("needs at least one private mockup" in e for e in errs)
    assert any("trading: versions" in e and "'v002']" in e for e in errs)


def test_private_store_verification(tmp_path):
    root = _copy_design(tmp_path)
    _, status = _status(root)
    store = tmp_path / "store"
    for f in status["private_assets"]["files"]:
        (store / "pages/home" / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (store / "pages/home" / f["path"]).write_bytes(b"not the original")
    errs = dp.verify_private(root, store)
    assert any("home/v001: private asset changed" in e for e in errs)
    assert any("private asset missing" in e for e in errs)  # other pages' assets absent from this store


# ---------------------------------------------------------------- privacy (public repository)


def test_committed_design_text_passes_the_privacy_scan():
    assert dp.privacy_scan([ROOT / "design"]) == []


@pytest.mark.parametrize("text", ["Cash $12,500 idle", "value 132,948 at risk", "acct # 12345678", "ending …4821"])
def test_privacy_patterns_catch_amounts_and_account_numbers(tmp_path, text):
    f = tmp_path / "SPEC.md"
    f.write_text(f"# x\n{text}\n", encoding="utf-8")
    assert dp.privacy_scan([f])


def test_private_terms_from_the_host_are_refused_as_whole_words(tmp_path):
    f = tmp_path / "SPEC.md"
    f.write_text("Watch shows ZZQX as held.\nNot a match: ZZQXY.\n", encoding="utf-8")
    hits = dp.privacy_scan([f], {"ZZQX"})
    assert len(hits) == 1 and "ZZQX" in hits[0]


def test_holdings_terms_reads_symbols_and_account_names(tmp_path):
    holdings = tmp_path / "holdings.json"
    holdings.write_text(json.dumps({"holdings": [{"symbol": "zzqx", "lots": [{"underlying": "QQZZ"}]}, {"symbol": "TOO-LONG-1"}]}))
    names = tmp_path / "names.json"
    names.write_text(json.dumps({"acct_a": "Example Brokerage Joint", "acct_b": {"label": "Example IRA"}}))
    assert dp.holdings_terms(holdings, names) == {"ZZQX", "QQZZ", "Example Brokerage Joint", "Example IRA"}


def test_cli_passes_on_the_repo(capsys):
    assert cli.main([]) == 0
    assert "PASS" in capsys.readouterr().out


def test_agents_28_13_text_is_present_and_names_its_causes():
    text = (ROOT / "design/AGENTS_28_13.md").read_text(encoding="utf-8")
    assert "## 28.13 Design lifecycle" in text
    for cause in ("handoff", "Decided recently", "Calendar and Replay", "15% of the viewport", "Rulebook", "public"):
        assert cause in text, cause
