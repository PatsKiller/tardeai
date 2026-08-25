"""R11 local-generative routing + no broker writes on new modules."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_synthesis import LOCAL_GENERATIVE_FORBIDDEN, select_model, synthesize
from scripts.lib.cio_situation_state import detect_office_situations
from scripts.lib.llm_task_policy import local_judgment_allowed
from scripts.local_llm import LocalGenerativeForbidden, _try_ollama
from tests.r11_office_fixtures import NOW, office, portfolio

ROOT = Path(__file__).resolve().parents[1]
R11_LIBS = [
    ROOT / "scripts/lib/cio_situation_state.py",
    ROOT / "scripts/lib/cio_office_cycle.py",
    ROOT / "scripts/lib/cio_advisory_synthesis.py",
    ROOT / "scripts/lib/cio_advisory_message.py",
    ROOT / "scripts/lib/cio_advisory_notify.py",
    ROOT / "scripts/lib/cio_operator_attention.py",
    ROOT / "scripts/lib/cio_operator_feedback_loop.py",
    ROOT / "scripts/lib/memory_consolidator_shadow.py",
]

FORBIDDEN_WRITES = (
    "place_order",
    "broker_submit",
    "mutate_stop",
    "risk_override",
    "send_2fa",
    "execute_trade",
)

pytestmark = pytest.mark.tier0


def test_local_judgment_forbidden() -> None:
    assert local_judgment_allowed() is False


def test_local_llm_generate_raises() -> None:
    with pytest.raises(LocalGenerativeForbidden):
        _try_ollama("hello")


def test_research_cio_advisory_telegram_cannot_select_local() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    choice = select_model(scan)
    assert choice["requested"] in {None, "deepseek-v4-flash", "oauth-challenger", "deepseek-v4-pro"}
    assert choice.get("requested") != "local"
    quiet = detect_office_situations(office(portfolio_state=portfolio(cash_pct=10.0)), evaluated_at=NOW)
    quiet_choice = select_model(quiet)
    assert quiet_choice["llm_calls"] == 0
    syn = synthesize(quiet)
    assert syn["local_generative"] is False


def test_fallback_cannot_silently_route_local() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)

    def _bad(*_a, **_k):
        raise RuntimeError(LOCAL_GENERATIVE_FORBIDDEN)

    with pytest.raises(RuntimeError, match="LOCAL_GENERATIVE"):
        synthesize(scan, generate=_bad, persisted_summary=None)
    syn = synthesize(scan, persisted_summary="prior")
    assert syn["local_generative"] is False
    assert syn["used_llm"] is False


def test_r11_modules_have_no_broker_writes() -> None:
    for path in R11_LIBS:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_WRITES:
            assert token not in text
        assert "READ_ONLY_ADVISORY" in text
        assert "11434" not in text
        assert "ollama" not in text.lower() or "forbidden" in text.lower()
