"""Work-package structure on the task board (operator 2026-10-23): hermetic, temp dirs only, pinned clocks.

"this is what should be done inside of the board also. structure: problem, definition of done, agent prompt,
operator commands, and proof of completion." and "also add that the above should be part of the board."

Covers: the optional structure fields on tasks (backward compatible: old tasks without them still work), ``task
edit``, proof-gated ``done`` (agent, evidence-only and operator paths), ``next``/``take`` never handing an OPERATOR
work package to an agent, the CLI flags and ``task show``, the handoff importer (header, sections, multi-line status,
inline prompts, dependencies, related-task links, adoption, ``[x]`` closing, idempotence, dry run writes nothing),
``export-handoff`` as an import fixed point, and the Work pipeline read model (wp block, stage intros, task detail with
the B0-prefixed prompt, cached export, GET-only routes).
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402
from scripts import import_handoff_workpackages as IMP  # noqa: E402
from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402
from scripts.lib import handoff_playbook as HP  # noqa: E402
from scripts.lib import work_pipeline as WP  # noqa: E402

T0 = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pin_cli_clock(monkeypatch):
    """The CLI and the importer build their own ClaimBoard: pin their clock to T0 as well (no real-clock reads)."""
    monkeypatch.setattr(B, "utc_now", lambda: T0)


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


def board(tmp_path, clock=None) -> TB.TaskBoard:
    return TB.TaskBoard(B.ClaimBoard(tmp_path / "claims", now=clock or Clock()))


def run_cli(tmp_path, *argv, session="s-test") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = CLI.main(["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--vendor", "claude", "--session", session,
                       *argv])  # fmt: skip
    return rc, out.getvalue(), err.getvalue()


STRUCT = {
    "problem": "The board does not say what is wrong.",
    "definition_of_done": "- every task has five sections",
    "agent_prompt": "Implement it. Write tests.",
    "operator_commands": "```\ngh pr merge 1 --merge\n```",
    "proof": "`task show` prints the five sections",
    "wp_id": "WP-41",
    "stage": "Stage 7",
    "owner_kind": "agent",
}


# --------------------------------------------------------------------------------------------- schema


def test_legacy_task_without_structure_still_works(tmp_path):
    t = board(tmp_path)
    d = t.add(title="old style", kind="build", areas=["a.py"])
    assert not any(k in d for k in TB.STRUCTURE_FIELDS) and "wp_id" not in d
    got, _claim = t.next(vendor="claude", session="s1", agent=None)
    done = t.done(got["task_id"], session="s1", summary="ok")  # no proof -> no evidence needed
    assert done["status"] == "done" and "proof_evidence" not in done
    row = t.board()["tasks"][0]
    assert row["sections"] == [] and row["wp_id"] is None and row["owner_kind"] is None


def test_add_with_structure_validates_and_normalizes(tmp_path):
    t = board(tmp_path)
    d = t.add(title="WP-41 board", kind="build", areas=["handoff/WP-41"], structure=STRUCT)
    assert d["owner_kind"] == "AGENT" and d["wp_id"] == "WP-41" and d["proof"].startswith("`task show`")
    assert t.board()["tasks"][0]["sections"] == [
        "problem",
        "definition_of_done",
        "agent_prompt",
        "operator_commands",
        "proof",
    ]
    with pytest.raises(TB.TaskError, match="wp_id"):
        t.add(title="x", kind="build", areas=["a"], structure={"wp_id": "W7"})
    with pytest.raises(TB.TaskError, match="owner_kind"):
        t.add(title="x", kind="build", areas=["a"], structure={"owner_kind": "ROBOT"})
    with pytest.raises(TB.TaskError, match="unknown structure field"):
        t.add(title="x", kind="build", areas=["a"], structure={"secret_sauce": "x"})
    big = t.add(title="big", kind="build", areas=["b"], structure={"problem": "x" * (TB.STRUCTURE_MAX_CHARS + 50)})
    assert len(big["problem"]) <= TB.STRUCTURE_MAX_CHARS and big["problem"].endswith("(truncated)")


def test_edit_sets_and_clears_fields_and_records_which(tmp_path):
    t = board(tmp_path)
    a = t.add(title="a", kind="build", areas=["a.py"])
    b = t.add(title="b", kind="build", areas=["b.py"])
    e = t.edit(b["task_id"], by="op", problem="new problem", depends_on=[a["task_id"]], priority=1, title="b2")
    assert e["problem"] == "new problem" and e["depends_on"] == [a["task_id"]] and e["priority"] == 1
    assert e["history"][-1]["event"] == "edited"
    assert set(e["history"][-1]["fields"]) == {"problem", "depends_on", "priority", "title"}
    e2 = t.edit(b["task_id"], by="op", problem=None)
    assert "problem" not in e2
    same = t.edit(b["task_id"], by="op", problem=None)
    assert len(same["history"]) == len(e2["history"])  # no-op edit writes nothing
    with pytest.raises(TB.TaskError, match="does not exist"):
        t.edit(b["task_id"], by="op", depends_on=["T-20261023-abcdef"])
    with pytest.raises(TB.TaskError, match="itself"):
        t.edit(b["task_id"], by="op", depends_on=[b["task_id"]])


def test_done_requires_proof_evidence_when_the_task_has_a_proof(tmp_path):
    t = board(tmp_path)
    d = t.add(title="proved", kind="build", areas=["p.py"], structure=STRUCT)
    t.next(vendor="claude", session="s1", agent=None)
    with pytest.raises(TB.TaskError, match="proof-evidence"):
        t.done(d["task_id"], session="s1")
    done = t.done(d["task_id"], session="s1", proof_evidence="PR #9 merged, served abc1234")
    assert done["status"] == "done" and done["proof_evidence"].startswith("PR #9") and done["wp_status"] == "done"
    assert done["history"][-1]["proof_evidence"].startswith("PR #9")


def test_evidence_recorded_by_edit_satisfies_done(tmp_path):
    t = board(tmp_path)
    d = t.add(title="proved", kind="build", areas=["p.py"], structure=STRUCT)
    t.next(vendor="claude", session="s1", agent=None)
    t.edit(d["task_id"], by="s1", proof_evidence="receipt data/runtime/x_last.json")
    assert t.done(d["task_id"], session="s1")["status"] == "done"


def test_evidence_only_maps_into_proof_evidence(tmp_path):
    t = board(tmp_path)
    d = t.add(title="shipped", kind="build", areas=["p.py"], structure=STRUCT)
    rc, out, err = run_cli(tmp_path, "task", "done", d["task_id"], "--evidence-only", "--summary", "shipped in batch 10",
                           "--evidence", "https://github.com/PatsKiller/tardeai/pull/2023", "c04a09498")  # fmt: skip
    assert rc == 0, err
    got = t.get(d["task_id"])
    assert got["done_mode"] == "evidence_only" and got["evidence"][1] == "c04a09498"
    assert "shipped in batch 10" in got["proof_evidence"] and "pull/2023" in got["proof_evidence"]
    assert got["wp_status"] == "done"


def test_operator_done_accepts_owner_kind_and_needs_summary_with_proof(tmp_path):
    t = board(tmp_path)
    op = t.add(title="WP-05 GitHub App config", kind="review", areas=["handoff/WP-05"],
               structure={**STRUCT, "wp_id": "WP-05", "owner_kind": "OPERATOR"})  # fmt: skip
    with pytest.raises(TB.TaskError, match="proof-evidence"):
        t.operator_done(op["task_id"], by="operator")
    d = t.operator_done(op["task_id"], by="operator", summary="wrote github-app.json, 600 johnclaw")
    assert d["status"] == "done" and d["proof_evidence"].startswith("wrote github-app.json")
    agent = t.add(title="agent work", kind="build", areas=["x.py"])
    with pytest.raises(TB.TaskError, match="not an OPERATOR"):
        t.operator_done(agent["task_id"], by="operator")


def test_next_and_take_never_hand_an_operator_package_to_an_agent(tmp_path):
    t = board(tmp_path)
    op = t.add(title="WP-04 install timers", kind="review", areas=["handoff/WP-04"], priority=1,
               structure={"wp_id": "WP-04", "owner_kind": "OPERATOR"})  # fmt: skip
    both = t.add(title="WP-08 wiring", kind="build", areas=["handoff/WP-08"], priority=2,
                 structure={"wp_id": "WP-08", "owner_kind": "BOTH"})  # fmt: skip
    got, _ = t.next(vendor="claude", session="s1", agent=None)
    assert got["task_id"] == both["task_id"]
    with pytest.raises(TB.TaskError, match="OPERATOR"):
        t.next(vendor="claude", session="s2", agent=None, task_id=op["task_id"])


def test_stages_store_round_trip(tmp_path):
    t = board(tmp_path)
    assert t.stages()["stages"] == []
    t.set_stages(
        [{"stage": "Stage 2", "title": "Release train", "description": "> what we build"}], source="h.md", by="x"
    )
    st = t.stages()
    assert st["schema"] == TB.STAGES_SCHEMA and st["stages"][0]["title"] == "Release train" and st["source"] == "h.md"
    with pytest.raises(TB.TaskError):
        t.set_stages([{"stage": ""}], source=None, by=None)


# --------------------------------------------------------------------------------------------- CLI


def test_cli_add_edit_show_done(tmp_path):
    files = {}
    for k, v in (("problem", "P text"), ("dod", "D text"), ("prompt", "Do the thing."), ("operator", "```\nrun x\n```"),
                 ("proof", "receipt exists")):  # fmt: skip
        f = tmp_path / f"{k}.md"
        f.write_text(v, encoding="utf-8")
        files[k] = str(f)
    rc, out, err = run_cli(tmp_path, "task", "add", "--title", "WP-07 Phase 5 proof", "--kind", "build", "--areas",
                           "handoff/WP-07", "--problem-file", files["problem"], "--dod-file", files["dod"],
                           "--prompt-file", files["prompt"], "--operator-file", files["operator"], "--proof-file",
                           files["proof"], "--wp-id", "WP-07", "--stage", "Stage 2", "--owner-kind", "AGENT")  # fmt: skip
    assert rc == 0, err
    tid = out.strip()
    rc, out, _ = run_cli(tmp_path, "task", "show", tid)
    for title in (
        "## Problem",
        "## Definition of done",
        "## Agent prompt",
        "## Operator commands",
        "## Proof of completion",
    ):
        assert title in out
    assert "(WP-07 Stage 2 AGENT)" in out and "run x" in out
    rc, out, _ = run_cli(tmp_path, "task", "show", tid, "--full-prompt")
    assert "Read `AGENTS.md` §0 and §28.3a." in out and out.index("Read `AGENTS.md`") < out.index("Do the thing.")
    rc, out, _ = run_cli(tmp_path, "task", "list", "--wp")
    assert tid in out
    rc, _, _ = run_cli(tmp_path, "take", tid)
    assert rc == 0
    rc, _, err = run_cli(tmp_path, "task", "done", tid)
    assert rc == 2 and "proof-evidence" in err
    rc, out, err = run_cli(tmp_path, "task", "done", tid, "--proof-evidence", "reports/rtw-1.json")
    assert rc == 0, err
    rc, _, _ = run_cli(tmp_path, "task", "edit", tid, "--clear", "notes", "--stage", "Stage 3")
    assert rc == 0 and json.loads((tmp_path / "claims" / "tasks" / f"{tid}.json").read_text())["stage"] == "Stage 3"


def test_cli_show_of_a_legacy_task_keeps_the_compact_output(tmp_path):
    rc, out, _ = run_cli(tmp_path, "task", "add", "--title", "legacy", "--kind", "fix", "--areas", "a.py")
    rc, out2, _ = run_cli(tmp_path, "task", "show", out.strip())
    assert "## Problem" not in out2 and "legacy" in out2


# --------------------------------------------------------------------------------------------- importer

HANDOFF = """# Plan

## A1. Resume procedure
not a work package

## Stage 1: Get merged work live

### WP-01 Release main
**Owner:** AGENT (coordinator), under the operator's release-write grant · **Depends:** none · **Status:** `[~]` (main had #2033 merged)

**Current issue:** code merged to `main` does nothing until released.

**Target state:**
- The served `git_sha` equals main.

**Agent prompt:**
> (B0 preamble.) Deploy current `origin/main`.
> 1. Wait for CI.

**Operator commands** (only if there is no grant):
```
bin/guard grant release-write --for 12h
**Not a label:** inside a fence
```

**Verify:** `curl /v3/build-meta.json` shows the main SHA.

**Traps:**
- A merge restarts CI.

### WP-02 Claim gate (#2031)
**Owner:** OPERATOR merge · **Depends:** WP-01 done (don't merge during a release) · **Status:** `[x]` PR #2031 merged 27f696bee

**Current issue:** the hook does not call the gate.

**Verify:** rc=1 with "BLOCK".

## Stage 2: Release train

> **What we're building.** A scheduled train.
>
> STOP is always available.

### WP-03 Phase 5 proof
**Owner:** AGENT (coordinator; operator approval I already given) · **Depends:** WP-01, WP-02 (WP-04 optional) · **Status:**
- P9 research #2005: `[x]` live
- P8 #2011: `[~]` red

**What happened:** nothing ran.

**Remaining, each with its own prompt:**
1. **Gate 4 alerts.**
   > (B0.) Fold Gate 4 alerts into the prospect.
2. **Operator:** decide the split.

### WP-04 Keep the plan in sync
**Owner:** AGENT (coordinator) · **Repeating**

- After each WP: mark it.
"""


def write_handoff(tmp_path, text=HANDOFF) -> Path:
    p = tmp_path / "HANDOFF_test.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_handoff_maps_every_section(tmp_path):
    parsed = IMP.parse_handoff(HANDOFF)
    assert [s["stage"] for s in parsed["stages"]] == ["Stage 1", "Stage 2"]
    assert parsed["stages"][1]["description"].startswith("**What we're building.** A scheduled train.")
    assert parsed["stages"][0]["description"] is None
    w1, w2, w3, w4 = parsed["wps"]
    assert (w1["owner_kind"], w2["owner_kind"], w3["owner_kind"]) == ("AGENT", "OPERATOR", "AGENT")
    s1 = w1["sections"]
    assert s1["problem"] == "code merged to `main` does nothing until released."
    assert s1["definition_of_done"] == "- The served `git_sha` equals main."
    assert s1["agent_prompt"] == "Deploy current `origin/main`.\n1. Wait for CI."  # B0 marker stripped
    assert (
        s1["operator_commands"].startswith("(only if there is no grant)\n```")
        and "**Not a label:**" in s1["operator_commands"]
    )
    assert s1["proof"].startswith("`curl /v3/build-meta.json`")
    assert s1["notes"].startswith("**Traps:**")
    assert w1["wp_status"] == "in_progress" and "#2033" in w1["wp_status_note"] and w1["prs"] == [2033]
    assert w2["depends"] == ["WP-01"] and w2["wp_status"] == "done" and "27f696bee" in w2["wp_status_note"]
    assert w3["depends"] == ["WP-01", "WP-02"]  # "(WP-04 optional)" is not a dependency
    assert w3["wp_status"] == "in_progress" and w3["wp_status_note"].count("\n") == 1
    assert w3["sections"]["problem"] == "nothing ran."
    assert w3["sections"]["definition_of_done"].startswith("**Remaining, each with its own prompt:**")
    assert w3["sections"]["agent_prompt"] == "**Item 1. Gate 4 alerts:** Fold Gate 4 alerts into the prospect."
    assert w4["wp_status"] == "repeating" and w4["sections"]["problem"] == "- After each WP: mark it."


def test_importer_dry_run_writes_nothing_then_apply_creates_links_and_closes(tmp_path, capsys):
    h = write_handoff(tmp_path)
    claims = tmp_path / "claims"
    t = board(tmp_path)
    legacy = t.add(title="OPERATOR: merge #2031 once green", kind="review", areas=["operator/pr-2031"])
    rc = IMP.main(["--file", str(h), "--dry-run", "--claims-dir", str(claims)])
    out = capsys.readouterr().out
    assert rc == 0 and "dry run: nothing written" in out
    assert "plan: 4 work packages · create 4" in out and f"related: {legacy['task_id']}" in out
    assert [x["task_id"] for x in board(tmp_path).read_all()] == [legacy["task_id"]]  # nothing written
    assert not (claims / "tasks" / TB.STAGES_NAME).exists()
    rc = IMP.main(["--file", str(h), "--apply", "--claims-dir", str(claims), "--session", "imp"])
    out = capsys.readouterr().out
    assert rc == 0 and "applied: created 4 · updated 0 · closed 1 · stages 2" in out
    tb = board(tmp_path)
    by_wp = {x["wp_id"]: x for x in tb.read_all() if x.get("wp_id")}
    assert by_wp["WP-01"]["task_id"] == "DSN-20261023-handoff-v3-P1-T01" and by_wp["WP-01"]["source"] == "handoff"
    assert by_wp["WP-01"]["areas"] == ["handoff/WP-01"] and by_wp["WP-01"]["priority"] == 1
    assert by_wp["WP-02"]["status"] == "done" and "27f696bee" in by_wp["WP-02"]["proof_evidence"]
    assert by_wp["WP-02"]["related_tasks"] == [legacy["task_id"]] and by_wp["WP-02"]["kind"] == "review"
    assert by_wp["WP-03"]["depends_on"] == [by_wp["WP-01"]["task_id"], by_wp["WP-02"]["task_id"]]
    assert tb.get(legacy["task_id"]).get("status") == "free"  # linked, never duplicated or closed
    assert tb.stages()["stages"][1]["description"].startswith("**What we're building.**")
    rc = IMP.main(["--file", str(h), "--dry-run", "--claims-dir", str(claims)])
    assert "create 0 · update 0 · unchanged 4" in capsys.readouterr().out  # idempotent


def test_importer_adopts_an_existing_task_with_the_same_wp_id(tmp_path, capsys):
    h = write_handoff(tmp_path)
    t = board(tmp_path)
    mine = t.add(task_id="DSN-20261023-work-pipeline-P3-T1", title="my own title", kind="build", areas=["x.py"],
                 structure={"wp_id": "WP-03", "proof": "my proof"})  # fmt: skip
    t.next(vendor="claude", session="me", agent=None, task_id=mine["task_id"])
    rc = IMP.main(["--file", str(h), "--apply", "--claims-dir", str(tmp_path / "claims")])
    out = capsys.readouterr().out
    assert rc == 0 and "adopts existing task (taken): sections only" in out
    got = board(tmp_path).get(mine["task_id"])
    assert got["title"] == "my own title" and got["status"] == "taken" and got["depends_on"] == []
    assert got["problem"] == "nothing ran." and got["proof"] == "my proof"  # handoff has no Verify: kept
    assert not board(tmp_path).path("DSN-20261023-handoff-v3-P2-T03").exists()


def test_export_handoff_is_an_import_fixed_point(tmp_path, capsys):
    h = write_handoff(tmp_path)
    claims = tmp_path / "claims"
    IMP.main(["--file", str(h), "--apply", "--claims-dir", str(claims)])
    capsys.readouterr()
    out_file = tmp_path / "export.md"
    rc, out, err = run_cli(tmp_path, "export-handoff", "--out", str(out_file))
    assert rc == 0, err
    text = out_file.read_text(encoding="utf-8")
    assert text.startswith("# Trade AI: complete ordered work plan (generated from the board)")
    assert "## A1. Resume procedure (any agent, every time)" in text  # the playbook is included
    assert "| WP-02 | Claim gate (#2031) | OPERATOR merge | [x] |" in text
    assert "**Proof evidence:**" in text and "> (B0.) Deploy current `origin/main`." in text
    assert "> **What we're building.** A scheduled train." in text
    rc = IMP.main(["--file", str(out_file), "--dry-run", "--claims-dir", str(claims)])
    assert "create 0 · update 0 · unchanged 4" in capsys.readouterr().out
    rc, out2, _ = run_cli(tmp_path, "export-handoff", "--out", "-")
    assert out2.split("```", 2)[2] == text.split("```", 2)[2]  # stable apart from the header block


# --------------------------------------------------------------------------------------------- Work pipeline


def test_pipeline_items_carry_the_wp_block_and_operator_owner(tmp_path):
    tb = board(tmp_path)
    a = tb.add(
        title="WP-07 proof",
        kind="build",
        areas=["handoff/WP-07"],
        structure={**STRUCT, "wp_id": "WP-07", "stage": "Stage 2"},
    )
    o = tb.add(title="WP-05 App config", kind="review", areas=["handoff/WP-05"], depends_on=[a["task_id"]],
               structure={"wp_id": "WP-05", "owner_kind": "OPERATOR", "stage": "Stage 2", "proof": "stat 600"})  # fmt: skip
    legacy = tb.add(title="plain", kind="fix", areas=["p.py"])
    rows = tb.board()["tasks"]
    items = {i["id"]: i for i in WP.build_items(tasks=rows, claims=[], census={}, now=T0)}
    ia, io_, il = items[a["task_id"]], items[o["task_id"]], items[legacy["task_id"]]
    assert ia["what"]["wp_id"] == "WP-07" and ia["what"]["stage"] == "Stage 2"
    assert ia["wp"]["sections"] == ["problem", "definition_of_done", "agent_prompt", "operator_commands", "proof"]
    assert "agent_prompt" not in json.dumps(ia["wp"]).replace('"agent_prompt"', "")  # names only, no text
    assert io_["wp"]["blocked_by"] == [a["task_id"]] and io_["next"]["owner"] == "operator"
    assert io_["who"]["kind"] == "operator" and "task_done" in io_["actions"]["available"]
    assert il["wp"] is None and il["what"]["wp_id"] is None


def test_task_detail_prefixes_the_b0_preamble(tmp_path):
    tb = board(tmp_path)
    a = tb.add(title="WP-07 proof", kind="build", areas=["handoff/WP-07"], structure=STRUCT)
    d = WP.task_detail(a["task_id"], tmp_path / "claims")
    assert d["schema"] == "WorkTaskDetail@v1" and d["problem"] == STRUCT["problem"]
    pre = HP.load_playbook()["b0_preamble"]
    assert pre and d["full_prompt"] == f"{pre}\n\n---\n\n{STRUCT['agent_prompt']}" and d["preamble"]["present"]
    with pytest.raises(TB.TaskError):
        WP.task_detail("../etc/passwd", tmp_path / "claims")


def test_view_carries_stage_intros_and_export_is_cached(tmp_path, monkeypatch):
    tb = board(tmp_path)
    tb.set_stages([{"stage": "Stage 2", "title": "Release train", "description": "x" * 9000}], source="h", by="t")
    rows = WP._wp_stages(tmp_path / "claims")
    assert rows[0]["title"] == "Release train" and len(rows[0]["description"]) == WP.MAX_STAGE_DESCRIPTION_CHARS
    calls = []
    monkeypatch.setattr(WP, "_EXPORT", None)
    monkeypatch.setattr(WP, "build_handoff_export", lambda claims_dir=None: calls.append(1) or {"markdown": "m"})
    assert WP.handoff_export() == {"markdown": "m"} and WP.handoff_export() == {"markdown": "m"}
    assert calls == [1]  # single-flight, at most once per REFRESH_S


def test_build_handoff_export_from_a_board(tmp_path, monkeypatch):
    tb = board(tmp_path)
    tb.add(title="WP-07 proof", kind="build", areas=["handoff/WP-07"], structure={**STRUCT, "wp_id": "WP-07"})
    monkeypatch.setenv("TRADEAI_AGENT_CLAIMS_DIR", str(tmp_path / "claims"))
    d = WP.build_handoff_export(tmp_path / "claims")
    assert d["work_packages"] == 1 and not d["truncated"] and "### WP-07 proof" in d["markdown"]
    assert d["filename"].startswith("HANDOFF_ORDERED_WORK_") and d["filename"].endswith(".md")


def test_api_routes_are_get_only_and_bounded():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('"/api/v2/coordination/task", "/api/v2/coordination/playbook", "/api/v2/coordination/handoff-export"')
    block = src[i : i + 1400]
    assert 'if method != "GET":' in block and '"read_only"' in block
    assert "_wpl.task_detail(" in block and "_wpl.handoff_export()" in block and "_load_playbook()" in block
    assert "[:120]" in block
