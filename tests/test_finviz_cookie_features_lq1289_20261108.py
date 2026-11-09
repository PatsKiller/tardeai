"""What a dead FINVIZ_COOKIE costs while the Elite API token still works (LQ-20261107-1289).

ANCHOR: FINVIZ_COOKIE_FEATURES_LQ1289_20261108

2026-11-08: FINVIZ_COOKIE expired 34 days ago and nothing said so. The Elite API token
(`auth=`) kept every screener returning rows, so the credential-health verdict was `token_ok`
— healthy, no banner, an `info` health finding. `config/finviz_cookie_features.json` is the one
list both the site banner and the operator alert name, so this test pins it to the audited set:
each entry must point at a real call site that fetches with the session cookie and has no token
substitute in the code as it stands. Pure: no network, no DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import finviz_cookie_features as fcf  # noqa: E402

CONFIG = ROOT / "config" / "finviz_cookie_features.json"
PINNED = ["position_technicals", "options_universe_completeness", "news_headline_fallback"]


def test_registry_names_the_audited_cookie_only_features_in_file_order():
    rows = fcf.features(CONFIG)
    assert [row["id"] for row in rows] == PINNED
    for row in rows:
        assert str(row["label"]).strip() and str(row["impact"]).strip(), row
        assert isinstance(row["evidence"], list) and row["evidence"], row


def test_every_evidence_pointer_resolves_to_a_real_call_site():
    """`file:marker` — the file exists and contains the marker. A stale pointer is a lie in the banner."""
    for row in fcf.features(CONFIG):
        for pointer in row["evidence"]:
            rel, sep, marker = str(pointer).partition(":")
            assert sep and rel and marker, f"{row['id']}: not a file:marker pointer: {pointer!r}"
            path = ROOT / rel
            assert path.is_file(), f"{row['id']}: no such file {rel}"
            assert marker in path.read_text(encoding="utf-8", errors="replace"), (
                f"{row['id']}: {marker!r} is not in {rel}")


def test_labels_and_summary_come_from_the_same_file():
    names = fcf.labels(CONFIG)
    count, joined = fcf.summary(CONFIG)
    assert count == len(names) == len(PINNED)
    assert joined == ", ".join(names)
    paragraph = fcf.paragraph(CONFIG)
    assert paragraph.splitlines() and all(line.startswith("• ") for line in paragraph.splitlines())
    # The alert says "renew" and the banner says "renew"; neither may be given a bare count.
    assert all(row["label"] in paragraph for row in fcf.features(CONFIG))


def test_default_path_is_the_committed_config():
    assert fcf.features() == fcf.features(CONFIG)


def test_unreadable_registry_is_an_empty_list_never_an_exception(tmp_path):
    assert fcf.load(tmp_path / "absent.json")["features"] == []
    assert fcf.labels(tmp_path / "absent.json") == []
    assert fcf.summary(tmp_path / "absent.json") == (0, "")
    assert fcf.load(tmp_path / "absent.json")["error"] == "unreadable"


def test_malformed_registry_drops_rows_without_ids_or_labels(tmp_path):
    doc = {"schema": fcf.load(CONFIG)["schema"], "features": [
        {"id": "kept", "label": "A feature", "impact": "cost", "evidence": []},
        {"id": "", "label": "no id", "impact": "cost"},
        {"id": "no_label", "label": "   ", "impact": "cost"},
        "not-a-row",
        {"id": "also_kept", "label": "B feature", "impact": ""},
    ]}
    path = tmp_path / "feats.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert [row["id"] for row in fcf.features(path)] == ["kept", "also_kept"]
    assert fcf.labels(path) == ["A feature", "B feature"]
    # A row without an impact still gets a line; the count never silently changes.
    assert fcf.paragraph(path).splitlines()[-1] == "• B feature"


def test_features_key_that_is_not_a_list_is_an_error_not_a_partial_read(tmp_path):
    path = tmp_path / "feats.json"
    path.write_text(json.dumps({"schema": "FinvizCookieFeatures@v1", "features": {"a": 1}}), encoding="utf-8")
    assert fcf.features(path) == []
    assert fcf.load(path)["error"] == "no_features"
