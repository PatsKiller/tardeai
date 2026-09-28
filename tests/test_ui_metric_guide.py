"""Metric guide (PR3, 2026-09-27): assets/ui_metric_guide.yaml is valid, every entry answers the
four questions, the generated TypeScript key union matches the YAML, and the API handler
serves it. Hermetic: pyyaml only."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import ui_metric_guide as umg  # noqa: E402


def test_guide_parses_and_every_entry_answers_the_four_questions():
    payload = umg.load(ROOT)
    assert payload["ok"], payload["errors"]
    assert payload["schema"] == "UiMetricGuide@v1" and payload["version"] == "1" and payload["count"] >= 100
    for key, e in payload["entries"].items():
        for f in umg.REQUIRED:
            assert str(e.get(f) or "").strip(), f"{key} missing {f}"
        assert umg.KEY_RE.match(key), key
    assert re.fullmatch(r"[0-9a-f]{16}", payload["etag"])


def test_house_entries_present_with_benchmarks_and_no_frontend_arithmetic():
    e = umg.load(ROOT)["entries"]
    for k in ("options.credit_basis", "options.loss_to_credit_ratio", "options.hedged_max_loss_from_mark",
              "sentiment.score", "cio.decision", "watch.rr", "position.unrealized_pct", "freshness.as_of", "options.pop"):
        assert k in e, k
    assert "not a fill" in e["options.credit_basis"]["short"] or "midpoint" in e["options.credit_basis"]["short"]
    assert "MONITOR_ONLY is not approval" in e["cio.decision"]["why_it_matters"]
    # placeholders are the only dynamic content; they must be simple names the frontend fills from the payload
    for k, v in e.items():
        for f in umg.REQUIRED + umg.OPTIONAL:
            for ph in re.findall(r"\{([^}]*)\}", str(v.get(f) or "")):
                assert re.fullmatch(r"[A-Za-z0-9_]+", ph), f"{k}.{f}: placeholder {{{ph}}} is not a plain name"


def test_generated_key_union_matches_the_yaml():
    gen = (ROOT / "apps/command-center-v3/src/lib/metricGuide.keys.generated.ts").read_text(encoding="utf-8")
    keys = re.findall(r'^\s+"([^"]+)",$', gen, re.M)
    assert keys == umg.keys(ROOT)
    assert 'export type MetricGuideKey = (typeof METRIC_GUIDE_KEYS)[number]' in gen


def test_validate_names_every_defect():
    errs = umg.validate({"version": 1, "entries": {"Bad Key": {"label": "x"}, "ok.metric": {"label": "a", "short": "b",
                        "definition": "c", "why_it_matters": "d", "interpretation": "e", "bogus": 1, "sources": "s"}}})
    joined = "\n".join(errs)
    assert "Bad Key: key must be dotted" in joined and "Bad Key: missing short" in joined
    assert "ok.metric: unknown field bogus" in joined and "ok.metric: sources must be a list" in joined
    assert umg.validate({"version": 1, "entries": {}}) == ["entries missing or empty"]


def test_loader_caches_by_mtime_and_reports_missing_file(tmp_path):
    root = tmp_path
    (root / "assets").mkdir()
    (root / "assets" / "ui_metric_guide.yaml").write_text(
        "version: 1\nas_of: \"2026-09-27\"\nentries:\n  a.b:\n    label: \"A\"\n    short: \"s\"\n    definition: \"d\"\n    why_it_matters: \"w\"\n    interpretation: \"i\"\n")
    p1 = umg.load(root)
    assert p1["ok"] and p1["count"] == 1 and umg.load(root) is p1     # cached object
    assert umg.load(tmp_path / "nowhere")["ok"] is False


def test_api_handler_returns_the_guide():
    """The api_v2 handler is a thin wrapper; prove the wiring without importing the 50k-line module."""
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/ui/metric-guide": _ui_metric_guide,' in src
    body = src[src.index("def _ui_metric_guide("):src.index("def _ui_prefs_get(")]
    assert "ui_metric_guide import load" in body and "return _load_guide()" in body
    payload = umg.load(ROOT)
    assert json.dumps(payload)  # serialisable as the handler returns it
