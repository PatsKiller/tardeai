"""Real escalation constructor and sender call, isolated from the job's DB/model/send imports."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import notification_url_builder as urls
from scripts.lib.watchlist_escalation_message import build_escalation_message

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_public_base(monkeypatch):
    monkeypatch.setattr(urls, "get_public_base_url", lambda: "https://cc.fixture.invalid")


def current_watch_tab():
    page = (ROOT / "apps/command-center-v3/src/pages/WatchHub.tsx").read_text()
    slugs = page.split("const TAB_SLUG", 1)[1].split("const SLUG_TAB", 1)[0]
    return re.search(r"MyWatchlist:\s*'([^']+)'", slugs).group(1)


@pytest.mark.parametrize("symbol", ["TSLA", "BRK.B", "FIXTURE & tab=other?x#fragment"])
def test_review_link_survives_notification_normalization_and_has_one_query(symbol):
    text = build_escalation_message(symbol, "AVOID", 0.82, ["6 agent conflicts"])
    normalized = urls.publicize_message(text)
    link = normalized.rsplit("Review at: ", 1)[1]
    parts = urlsplit(link)
    assert parts.scheme == "https" and parts.netloc == "cc.fixture.invalid"
    assert parts.path == "/v3/watch" and parts.fragment == ""
    assert link.count("?") == 1
    assert parse_qs(parts.query) == {"tab": [current_watch_tab()], "symbol": [symbol]}
    assert text.split("Review at: ", 1)[0] == (
        f"🚨 *Escalation: {symbol}*\nSynthesis: AVOID (82% confidence)\nReasons: 6 agent conflicts\n"
    )


def test_actual_sender_call_uses_constructor_and_preserves_notification_metadata():
    """Execute only the actual sender expression with a recording fake, never import/run the worker."""
    tree = ast.parse((ROOT / "scripts/process_watchlist_agent_jobs.py").read_text())
    send = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "send_telegram"
                and any(k.arg == "producer" and isinstance(k.value, ast.Constant)
                        and k.value.value == "process_watchlist_agent_jobs" for k in node.keywords)
                and node.args and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Name)
                and node.args[0].func.id == "build_escalation_message")
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "lib.watchlist_escalation_message"]
    assert any(alias.name == "build_escalation_message" for node in imports for alias in node.names)
    calls = []
    namespace = {"send_telegram": lambda message, **meta: calls.append((message, meta)),
                 "build_escalation_message": build_escalation_message,
                 "symbol": "TSLA", "parsed": {"recommendation": "AVOID", "confidence": 0.82},
                 "escalation_reasons": ["6 agent conflicts"]}
    eval(compile(ast.fix_missing_locations(ast.Expression(send)), "actual-escalation-send-expression", "eval"), namespace)
    assert len(calls) == 1
    message, metadata = calls[0]
    assert metadata == {"priority": "P2", "producer": "process_watchlist_agent_jobs"}
    assert message == build_escalation_message("TSLA", "AVOID", 0.82, ["6 agent conflicts"])


def test_worker_flat_import_layout_uses_same_central_builder(monkeypatch):
    """Compile the pure helper in the supported scripts-only namespace, with the same fixture module."""
    import sys
    import types

    monkeypatch.setitem(sys.modules, "notification_url_builder", urls)
    module = types.ModuleType("lib.watchlist_escalation_message")
    module.__package__ = "lib"
    source = (ROOT / "scripts/lib/watchlist_escalation_message.py").read_text()
    exec(compile(source, "flat-layout-escalation-helper", "exec"), module.__dict__)
    expected = build_escalation_message("TSLA", "AVOID", 0.82, ["6 agent conflicts"])
    assert module.build_escalation_message("TSLA", "AVOID", 0.82, ["6 agent conflicts"]) == expected
