"""The Telegram chokepoint ratchet must actually execute.

`scripts/check_telegram_chokepoint.py` is a well-built behavioural guard: it
looks for the BEHAVIOUR of bypassing the transport -- raw endpoints, HTTP aimed
at Telegram, a producer selecting the chat id or reading the bot token itself --
rather than one spelling. Its own docstring records why: an earlier guard matched
only a literal URL, and thirty-nine producers walked through it while looking
centralized.

It was invoked by NOTHING. `ai_local_acceptance.sh` names it in a `case`
statement that classifies changed paths -- that is a filename in a pattern list,
not an execution. So the ratchet could not ratchet: a new bypass added today
would have been caught by no one.

This test runs it inside the only required context on `main`, so a NEW bypass
fails the build while the 133 inherited violations stay declared debt that can
only shrink.
"""

from __future__ import annotations

import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_telegram_chokepoint.py"
BASELINE = ROOT / "config" / "telegram_chokepoint_baseline.json"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def test_package_style_transport_import_is_detected_and_poller_reply_stays_proposed():
    """E-B2: package imports count. cio_poller_reply is proposed, not approved."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_telegram_chokepoint as checker

    assert checker.PROPOSED_INBOUND == {"scripts/lib/cio_poller_reply.py"}
    assert not (checker.PROPOSED_INBOUND & checker.APPROVED)
    for src in (
        "from scripts import telegram_transport\n",
        "import scripts.telegram_transport\n",
        "from scripts.telegram_transport import send_message\n",
    ):
        assert checker.PATTERNS["transport_import"].search(src), src
        assert checker._transport_import_is_sending(src), src
    r = _run()
    assert r.returncode == 0, r.stderr
    assert "PROPOSED for APPROVED_INBOUND" in r.stdout
    assert "scripts/lib/cio_poller_reply.py" in r.stdout
    for rel in (
        "tests/test_cio_answer_quality.py",
        "tests/test_cio_poller_reply.py",
        "tests/test_cio_telegram_plain_ids.py",
        "tests/test_comms_editor_transport_20260914.py",
        "tests/test_desk_reply_delivery_20260914.py",
        "tests/test_m5_gate_coverage_20260923.py",
        "tests/test_telegram_operator_presentation.py",
    ):
        assert rel in checker.APPROVED_TOOLING, rel


def test_the_checker_exists_and_is_runnable():
    assert CHECKER.is_file(), "the chokepoint checker is missing"
    assert BASELINE.is_file(), "the ratchet baseline is missing"


def test_the_ratchet_holds_on_this_tree():
    """Exit code checked for 0 exactly -- not merely 'not a crash'.

    A non-zero here means a bypass was added without declaring it.
    """
    r = _run()
    assert r.returncode == 0, (
        "telegram chokepoint ratchet failed:\n"
        f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-2000:]}")


def test_the_ratchet_reports_debt_or_explicit_zero():
    """While debt remains, the guard must print a violation count.

    After the bypass cohort migrations emptied the baseline, an explicit
    ``pass: zero bypasses`` line is the honest clean signal — still distinct
    from a silent vacuous pass.
    """
    r = _run()
    out = (r.stdout + r.stderr).lower()
    assert ("violation" in out) or ("zero bypasses" in out), (
        "the ratchet must state outstanding debt or an explicit zero-bypass pass"
    )


def test_the_checker_can_go_red(tmp_path):
    """Guard the guard: a NEW undeclared bypass must fail the build.

    Without this the ratchet could be vacuous -- passing because it finds
    nothing rather than because nothing new was added.
    """
    # The probe is ASSEMBLED FROM FRAGMENTS. Written literally, this test file
    # would itself contain the offending endpoint -- and the checker scans the
    # whole tree, so the guard correctly flagged the test as a new bypass. The
    # test must plant the pattern without carrying it.
    host = "api" + "." + "telegram" + "." + "org"
    probe = (
        "import requests, os\n"
        "def send():\n"
        "    tok = os.environ['TELEGRAM_" + "BOT_TOKEN']\n"
        "    cid = os.environ['TELEGRAM_" + "CHAT_ID']\n"
        f"    return requests.post(f'https://{host}/bot{{tok}}/sendMessage',\n"
        "                         json={'chat_id': cid, 'text': 'probe'})\n"
    )
    # Use a throwaway tree so parallel CI scans never see an adversarial probe.
    checker = tmp_path / "scripts" / CHECKER.name
    checker.parent.mkdir(parents=True)
    shutil.copy2(CHECKER, checker)
    baseline = tmp_path / "config" / BASELINE.name
    baseline.parent.mkdir(parents=True)
    shutil.copy2(BASELINE, baseline)
    planted = tmp_path / "scripts" / "_pytest_chokepoint_probe.py"
    planted.write_text(probe, encoding="utf-8")
    r = subprocess.run([sys.executable, str(checker)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode != 0, (
        "a new undeclared bypass did NOT fail the ratchet -- the guard is vacuous\n"
        f"stdout:\n{r.stdout[-2000:]}")
    assert "_pytest_chokepoint_probe.py" in r.stdout
