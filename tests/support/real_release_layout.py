"""A release fixture matching CURRENT and persistent log symlinks, not a flat repo."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil


@dataclass(frozen=True)
class ReleaseLayout:
    current: Path
    release: Path
    state: Path
    locks: Path


def real_release_layout(tmp_path: Path, source: Path) -> ReleaseLayout:
    release = tmp_path / "releases" / "candidate"
    state = tmp_path / "persistent-state"
    logs = state / "logs"
    locks = tmp_path / "locks"
    (release / "scripts" / "lib").mkdir(parents=True)
    logs.mkdir(parents=True)
    locks.mkdir()
    # The caller's actual private group, mode775 exactly as served.
    os.chmod(logs, 0o775)
    (release / "logs").symlink_to(logs, target_is_directory=True)
    for name in ("safe_flock.sh", "cron_wrapper.sh", "lib/wrapper_events.py", "effect_claim_cron.sh",
                 "market_day_gate.sh", "market_session.py", "llm_priority_guard.sh",
                 "run_with_deepseek_offpeak.sh", "lib/deepseek_offpeak.py", "non_trading_hours_gate.sh"):
        shutil.copy2(source / "scripts" / name, release / "scripts" / name)
    current = tmp_path / "CURRENT"
    current.symlink_to(release, target_is_directory=True)
    return ReleaseLayout(current, release, state, locks)
