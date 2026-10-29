"""Plain-English approval cards; all sends, GitHub and state are isolated."""

import json
from pathlib import Path

import pytest

from scripts import check_pr_plain_english as plain
from scripts.lib import pr_merge_digest as digest
from scripts.lib import pr_merge_telegram as telegram


ANSWERS = {
    "What changes": "Shows a clear explanation for every proposed change.",
    "Why": "The operator needs to understand what is being approved.",
    "Who / what it affects": "The merge digest; no trading or broker change.",
    "When it takes effect": "After the reviewed release reaches the server.",
    "Approval": "One digest tap after required checks pass.",
    "Risk and fallback": "Hold all and revert this change if cards are wrong.",
}


def body(answers=None, *, bullets=False):
    values = ANSWERS | (answers or {})
    return (
        "## In plain English\n"
        + "\n".join(("- " if bullets else "") + f"**{key}:** {values[key]}" for key in plain.LABELS)
        + "\n\n## Technical detail\nNo private data.\n"
    )


def pr(number, *, text=None, held=False, title=None):
    return {
        "number": number,
        "title": title or f"This explains proposed change number {number}",
        "body": body() if text is None else text,
        "headRefOid": f"{number:040x}",
        "url": f"https://example.test/pull/{number}",
        "baseRefName": "main",
        "isDraft": False,
        "labels": [],
        "files": [{"path": "AGENTS.md" if held else "docs/example.md"}],
        "changedFiles": 1,
        "statusCheckRollup": [{"name": name, "conclusion": "SUCCESS"} for name in telegram.REQUIRED_CHECKS],
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PR_MERGE_TELEGRAM_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "unused"))
    sent, prs = [], []
    monkeypatch.setattr(digest, "list_open_prs", lambda *a, **kw: list(prs))

    def send(message, *, priority, reply_markup=None):
        sent.append({"message": message, "reply_markup": reply_markup})
        return True, [str(len(sent))], "delivered synthetic message"

    monkeypatch.setattr(digest, "_send", send)
    monkeypatch.setattr(digest, "_gh", lambda *a, **kw: pytest.fail("unexpected GitHub call"))
    monkeypatch.setattr(telegram, "add_operator_merge_label", lambda *a, **kw: pytest.fail("unexpected label write"))
    return prs, sent


def test_described_pr_has_all_card_fields_and_clean_headline(isolated):
    prs, sent = isolated
    prs.append(
        pr(1, title="[shared-infra] feat(ops): DSN-20261028-digest-P1-T1: Explain every proposed change clearly")
    )
    result = digest.run_digest(apply=True)
    text = "\n".join(m["message"] for m in sent)
    assert "*#1* — Explain every proposed change clearly" in text
    for prefix in ["What:", "Why:", "Affects:", "When:", "Fallback:", "Approval:", "Risk:"]:
        assert prefix in text
    assert "feat(" not in text and "DSN-" not in text and "[shared-infra]" not in text
    assert result["ready"] == [1]


def test_undescribed_prs_are_visible_but_have_no_approve_path(isolated):
    prs, sent = isolated
    prs.extend([pr(1), pr(2, text="## Summary\nEngineer-only details."), pr(3, held=True, text="Old body")])
    result = digest.run_digest(apply=True)
    assert result["ready"] == [1] and result["not_described"] == [2, 3]
    assert "Not described — cannot approve until rewritten" in result["message"]
    buttons = sent[-1]["reply_markup"]["inline_keyboard"]
    assert buttons[0][0]["text"] == "✅ Approve all (1)"
    assert not any(b["callback_data"].endswith((":2", ":3")) for row in buttons for b in row)
    assert not digest.toggle_item(result["digest_id"], 2, chat_id="test", allowed_chats={"test"})["ok"]


@pytest.mark.parametrize("missing", plain.LABELS)
def test_missing_plain_english_answer_is_not_approvable(isolated, missing):
    prs, _ = isolated
    text = body().replace(f"**{missing}:** {ANSWERS[missing]}\n", "")
    prs.append(pr(1, text=text))
    result = digest.run_digest(apply=False)
    assert result["ready"] == [] and result["not_described"] == [1]
    assert result["reply_markup"] is None


def test_long_digest_splits_without_dropping_any_description(isolated):
    prs, sent = isolated
    for n in list(range(1, 11)) + list(range(101, 116)):
        fields = {key: f"Change {n}: " + "😀 *detail* _value_ `quote` [link] " * 30 for key in plain.LABELS}
        prs.append(pr(n, text=body(fields), held=n > 100))
    cfg = digest.load_config() | {"max_ready_per_digest": 10}
    result = digest.run_digest(apply=True, cfg=cfg)
    assert len(sent) > 3 and len(result["ready"]) == 10
    assert all(len(m["message"].encode("utf-16-le")) // 2 <= 4096 for m in sent)
    assert all(result["digest_id"] in m["message"] for m in sent)
    text = "\n".join(m["message"] for m in sent)
    for n in list(range(1, 11)) + list(range(101, 116)):
        assert f"What: Change {n}:" in text
        assert f"Why: Change {n}:" in text
        assert f"Affects: Change {n}:" in text
        assert f"Fallback: Change {n}:" in text
    assert all(m["reply_markup"] is None for m in sent[:-1])
    assert sent[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "✅ Approve all (10)"
    assert digest.load_digests()[-1]["message_ids"] == [str(n) for n in range(1, len(sent) + 1)]


def test_every_hold_class_has_plain_words():
    root = Path(__file__).resolve().parents[1]
    classes = json.loads((root / "config/merge_hold_paths.json").read_text())["classes"]
    wording = digest.load_config()["hold_class_words"]
    assert all(row["id"] in wording and wording[row["id"]].strip() for row in classes)


def test_hold_cards_translate_classes_and_state_operator_approval(isolated):
    prs, _ = isolated
    prs.append(pr(1, held=True))
    result = digest.run_digest(apply=False)
    assert "changes AGENTS.md or agent rules" in result["message"]
    assert "Approval: individual operator approval required; never Approve all" in result["message"]
    assert "agents_policy" not in result["message"]
    buttons = result["reply_markup"]["inline_keyboard"]
    assert buttons == [[{"text": "🔐 Approve #1 (held)", "callback_data": f"prdheld:{result['digest_id']}:1"}]]


def test_markdown_fields_are_escaped_and_trimmed_at_words(isolated):
    prs, _ = isolated
    text = "*stars* _under_ `code` [label]"
    prs.append(pr(1, text=body({"What changes": text, "Why": "one two three four five six seven eight"})))
    result = digest.run_digest(apply=False, cfg=digest.load_config() | {"plain_field_chars": 30})
    assert "What: \\*stars\\* \\_under\\_ \\`code\\` \\[label]" in result["message"]
    assert "Why: one two three four five six…" in result["message"]


def test_default_ready_cap_keeps_overflow_for_next_digest(isolated):
    prs, _ = isolated
    prs.extend(pr(n) for n in range(1, 11))
    result = digest.run_digest(apply=False)
    assert result["ready"] == list(range(1, 9)) and result["overflow"] == [9, 10]
    assert "2 more ready — next digest" in result["message"]


@pytest.mark.parametrize("count", [3, 6])
def test_buttons_stay_beneath_a_ready_card_not_an_orphan_footer(isolated, count):
    prs, sent = isolated
    prs.extend(pr(n) for n in range(1, count + 1))
    digest.run_digest(apply=True)
    assert f"*#{count}* —" in sent[-1]["message"]
    assert "What:" in sent[-1]["message"] and sent[-1]["reply_markup"]


def test_failed_information_only_delivery_is_retried(isolated, monkeypatch):
    prs, _ = isolated
    prs.append(pr(1, text="This PR has not been described yet."))
    normal_send = digest._send
    monkeypatch.setattr(digest, "_send", lambda *a, **kw: (False, [], "synthetic failure"))
    assert not digest.run_digest(apply=True)["ok"]
    monkeypatch.setattr(digest, "_send", normal_send)
    assert digest.run_digest(apply=True)["action"] == "sent"


@pytest.mark.parametrize("queued", [False, True])
def test_missing_detail_delivery_never_creates_an_approvable_digest(isolated, monkeypatch, queued):
    prs, sent = isolated
    prs.extend(pr(n) for n in range(1, 9))
    successful_send = digest._send

    def fail_second(message, *, priority, reply_markup=None):
        if len(sent) == 1:
            sent.append({"message": message, "reply_markup": reply_markup})
            return queued, [], "synthetic failed or queued delivery"
        return successful_send(message, priority=priority, reply_markup=reply_markup)

    monkeypatch.setattr(digest, "_send", fail_second)
    result = digest.run_digest(apply=True)
    assert result["action"] == "send_failed" and not result["ok"]
    assert digest.load_digests()[-1]["status"] == "DELIVERY_FAILED"
    assert all(m["reply_markup"] is None for m in sent)
    refusal = digest.settle_approve_all(result["digest_id"], chat_id="test", allowed_chats={"test"})
    assert refusal["reason"] == "NOT_PENDING:DELIVERY_FAILED"


def test_dry_run_contains_every_part_but_sends_and_writes_nothing(isolated):
    prs, sent = isolated
    prs.extend(pr(n) for n in range(1, 9))
    result = digest.run_digest(apply=False)
    assert len(result["messages"]) > 1
    assert not sent and digest.load_digests() == []
    assert not digest.digests_path().exists()


def test_rewritten_description_replaces_prompt_without_changing_sha_signature(isolated):
    prs, _ = isolated
    prs.append(pr(1))
    first = digest.run_digest(apply=True)
    signature = digest.load_digests()[-1]["signature"]
    prs[0]["body"] = body({"What changes": "A clearer explanation for the exact same reviewed code."})
    second = digest.run_digest(apply=True)
    assert second["digest_id"] != first["digest_id"]
    assert digest.load_digests()[-1]["signature"] == signature
    assert digest.load_digests()[0]["status"] == "SUPERSEDED"
    preview = digest.run_digest(apply=False)
    assert preview["action"] == "unchanged_pending_digest" and preview["messages"]


def test_bulleted_answers_use_shared_parser_without_cross_field_text():
    assert not plain.check("This explains a synthetic change", body(bullets=True))
    assert plain.fields(body(bullets=True)) == ANSWERS


def test_legacy_markdown_keeps_untrusted_title_outside_bold_and_preserves_backslashes(isolated):
    prs, _ = isolated
    prs.append(
        pr(77, title="Explain 2*2 calculation clearly", text=body({"What changes": r"Reads C:\folder\name safely."}))
    )
    result = digest.run_digest(apply=False)
    assert "*#77* — Explain 2\\*2 calculation clearly\n" in result["message"]
    assert r"What: Reads C:\folder\name safely." in result["message"]


@pytest.mark.parametrize("bullets", [False, True])
def test_literal_field_label_inside_an_answer_cannot_replace_the_actual_field(isolated, bullets):
    prs, _ = isolated
    values = {
        "What changes": "Adds the **Why:** field to each approval card.",
        "Why": "Operators need the actual reason before approving a change.",
    }
    text = body(values, bullets=bullets)
    assert not plain.check("This explains every proposed change", text)
    assert plain.fields(text)["Why"] == values["Why"]
    prs.append(pr(1, text=text))
    result = digest.run_digest(apply=False)
    assert "Why: Operators need the actual reason before approving a change." in result["message"]


def test_real_pr_bodies_extract_their_original_what_answer():
    path = Path(__file__).with_name("fixtures") / "pr_digest_plain_english_20261028.json"
    rows = json.loads(path.read_text())["prs"]
    for row in rows:
        assert not plain.check(row["title"], row["body"])
        answer = plain.fields(row["body"])["What changes"]
        raw = next(
            line.split("**What changes:**", 1)[1].strip()
            for line in row["body"].splitlines()
            if "**What changes:**" in line
        )
        assert answer == raw
        assert "**Why:**" not in answer and "**Approval:**" not in answer


@pytest.mark.parametrize("count", [1, 7])
def test_described_held_only_digest_keeps_pending_final_keyboard(isolated, count):
    prs, sent = isolated
    numbers = list(range(101, 101 + count))
    prs.extend(pr(number, held=True) for number in numbers)

    result = digest.run_digest(apply=True)

    assert result["ready"] == [] and result["needs_operator"] == numbers
    record = digest.load_digests()[-1]
    assert record["status"] == "PENDING"
    assert record["message_ids"] == [str(i) for i in range(1, len(sent) + 1)]
    if count > 3:
        assert len(sent) > 1
    assert all(message["reply_markup"] is None for message in sent[:-1])
    assert sent[-1]["reply_markup"]
    assert f"*#{numbers[-1]}* —" in sent[-1]["message"]
    assert "What:" in sent[-1]["message"]
    assert all(result["digest_id"] in message["message"] for message in sent)
    buttons = [button for row in sent[-1]["reply_markup"]["inline_keyboard"] for button in row]
    assert [button["callback_data"] for button in buttons] == [
        f"prdheld:{result['digest_id']}:{number}" for number in numbers
    ]
    assert all("Approve all" not in button["text"] for button in buttons)
    text = "\n".join(message["message"] for message in sent)
    assert "Approval: individual operator approval required; never Approve all" in text
    assert "no Approve here" not in text
    assert "operator's own merge required" not in text


@pytest.mark.parametrize("missing", [None, *plain.LABELS], ids=["all-answers", *plain.LABELS])
def test_undescribed_held_pr_has_no_individual_or_bulk_approval(isolated, monkeypatch, missing):
    prs, sent = isolated
    invalid = "## Summary\nThis old engineering body has no approval answers."
    if missing is not None:
        invalid = body().replace(f"**{missing}:** {ANSWERS[missing]}\n", "")
    # Keep a described ready PR and a described held PR so this is a live pending
    # digest, and the missing item must be refused by membership rather than status.
    prs.extend([pr(1), pr(5, held=True, text=invalid), pr(6, held=True)])
    label_attempts = []
    monkeypatch.setattr(
        telegram,
        "add_operator_merge_label",
        lambda number, **kwargs: label_attempts.append(number) or {"ok": False},
    )

    result = digest.run_digest(apply=True)

    assert result["ready"] == [1]
    assert result["needs_operator"] == [6]
    assert result["not_described"] == [5]
    assert "Not described — cannot approve until rewritten" in result["message"]
    assert digest.load_digests()[-1]["status"] == "PENDING"
    buttons = [button for row in sent[-1]["reply_markup"]["inline_keyboard"] for button in row]
    assert any(button["text"] == "✅ Approve all (1)" for button in buttons)
    assert any(button["callback_data"] == f"prdheld:{result['digest_id']}:6" for button in buttons)
    assert not any(button["callback_data"].endswith(":5") for button in buttons)

    refusal = digest.settle_approve_held_pr(result["digest_id"], 5, chat_id="test", allowed_chats={"test"})

    assert refusal["ok"] is False and refusal["reason"] == "PR_NOT_HELD_IN_DIGEST"
    assert label_attempts == []
    assert digest._read_jsonl(digest.approvals_path()) == []


@pytest.mark.parametrize("queued", [False, True], ids=["failed", "queued-without-message-id"])
def test_missing_held_detail_page_refuses_individual_settlement(isolated, monkeypatch, queued):
    prs, sent = isolated
    prs.extend(pr(number, held=True) for number in range(101, 109))
    successful_send = digest._send
    label_attempts = []
    monkeypatch.setattr(
        telegram,
        "add_operator_merge_label",
        lambda number, **kwargs: label_attempts.append(number) or {"ok": False},
    )

    def fail_second(message, *, priority, reply_markup=None):
        if len(sent) == 1:
            sent.append({"message": message, "reply_markup": reply_markup})
            return queued, [], "synthetic failed or queued held-detail page"
        return successful_send(message, priority=priority, reply_markup=reply_markup)

    monkeypatch.setattr(digest, "_send", fail_second)

    result = digest.run_digest(apply=True)

    assert result["action"] == "send_failed" and result["ok"] is False
    assert len(sent) == 2
    assert all(message["reply_markup"] is None for message in sent)
    assert digest.load_digests()[-1]["status"] == "DELIVERY_FAILED"
    refusal = digest.settle_approve_held_pr(result["digest_id"], 101, chat_id="test", allowed_chats={"test"})
    assert refusal["ok"] is False and refusal["reason"] == "NOT_PENDING:DELIVERY_FAILED"
    assert label_attempts == []
    assert digest._read_jsonl(digest.approvals_path()) == []
