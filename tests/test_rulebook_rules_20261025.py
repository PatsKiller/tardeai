"""Rulebook rule model: only real rule items, grouped by section; unmeasured audit is a gap, never 0.

Synthetic policy text only. No live store, no network.
"""
from pathlib import Path

from scripts.lib import operator_approvals as c

SHA = "a" * 40

FIXTURE = """# FIXTURE.md — a synthetic operating standard

```
Policy-Version:      9.9.9
Status:              ACTIVE
```

**9.0.0 is ACTIVE (MAJOR) — a synthetic version banner that must never become a rule.**
More banner wording on a second line.

Intro prose before the first section.

---

# 0 · Fixture rules

These two keep the fixture honest.

1. **Never fixture-delete.** Archive the fixture instead,
   with a tripwire.
2. **Say what is `missing`.** See [the guide](https://example.test/guide).
   - a nested point that belongs to rule 2

| table | row |
|---|---|
| - not a rule | x |

> - a quoted banner, not a rule

```bash
- inside a code fence, not a rule
# not a heading
```

## 0.1 Sub-heading

- A bulleted rule under a sub-heading.

# 1 · Prose-only section

Propose and stop.

**At session start:**

The second prose rule of this section.

# Version history

- 9.9.9 the latest change, not a rule
"""


def project(text=FIXTURE, **kwargs):
    return c.policy_projection(text, source_sha=SHA, **kwargs)


def test_only_real_rule_items_become_rules():
    rules = project()["rules"]
    texts = [r["text"] for r in rules]
    assert texts == [
        "**Never fixture-delete.** Archive the fixture instead, with a tripwire.",
        "**Say what is `missing`.** See [the guide](https://example.test/guide).\n- a nested point that belongs to rule 2",
        "A bulleted rule under a sub-heading.",
        "Propose and stop.",
        "The second prose rule of this section.",
    ]
    joined = "\n".join(texts)
    for leaked in ("FIXTURE.md", "Policy-Version", "is ACTIVE (MAJOR)", "Intro prose", "not a rule",
                   "These two keep", "At session start", "```", "| table"):
        assert leaked not in joined


def test_rules_carry_section_subsection_and_number():
    rules = project()["rules"]
    assert [r["section"] for r in rules] == ["0 · Fixture rules"] * 3 + ["1 · Prose-only section"] * 2
    assert [r["number"] for r in rules[:3]] == ["1", "2", None]
    assert rules[2]["subsection"] == "0.1 Sub-heading"
    data = project()
    assert data["sections"] == ["0 · Fixture rules", "1 · Prose-only section"]
    assert data["section_counts"] == {"0 · Fixture rules": 3, "1 · Prose-only section": 2}


def test_unmeasured_audit_tiles_are_a_gap_never_zero():
    data = project()
    assert data["counts"] == {"RULES": 5, "ENFORCED": None, "TESTED": None, "WRITTEN-only": 5, "VIOLATED": None}
    assert data["counts_measured"] is False
    assert data["audit"]["state"] == "NOT_MEASURED"
    assert data["audit"]["reason"] == c.AUDIT_NOT_RUN
    assert all(r["reason"] == "Audit not run" for r in data["rules"])


def test_measured_audit_counts_are_numbers_and_bind_the_document():
    first = project()
    rule = first["rules"][0]
    proof = {rule["id"]: {"document_sha": first["document_sha"], "test_passed": True, "test_receipt": "receipt:1"}}
    data = project(enforcement=proof)
    assert data["counts_measured"] is True
    assert data["counts"]["TESTED"] == 1 and data["counts"]["ENFORCED"] == 0 and data["counts"]["VIOLATED"] == 0
    assert data["section_status"]["0 · Fixture rules"] == "WRITTEN-only"


def test_rule_ids_are_stable_for_the_same_text():
    assert [r["id"] for r in project()["rules"]] == [r["id"] for r in project()["rules"]]


def test_unverified_report_names_its_run_time_and_measures_nothing():
    audit = c.unverified_audit({"as_of": "2032-01-04T01:00:00Z"})
    assert audit["state"] == "NOT_MEASURED" and audit["last_run"] == "2032-01-04T01:00:00Z"
    assert "does not match" in audit["reason"]
    assert c.unverified_audit({})["reason"] == c.AUDIT_NOT_RUN


def test_the_repository_rulebook_has_no_preamble_banner_or_history_rules():
    text = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    data = c.policy_projection(text, source_sha=SHA)
    assert data["rules"], "the rulebook parsed to nothing"
    for rule in data["rules"]:
        assert not rule["text"].startswith(("#", "```", "|", ">"))
        assert " is ACTIVE (" not in rule["text"][:24]
        assert "Version history" not in rule["section"]
    assert "0 · If you read nothing else" in data["sections"]
    assert len(data["sections"]) < 80
