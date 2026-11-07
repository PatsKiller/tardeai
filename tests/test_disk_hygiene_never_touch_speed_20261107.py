"""LQ-41: never_touch_reason must not re-resolve the never-touch list for every scanned entry."""
import fnmatch
import os
from pathlib import Path

from scripts import disk_hygiene as dh


def _rules(tmp_path):
    return dh.load_rules(home=tmp_path)


def _old_reason(path, rules):  # the pre-fix algorithm, verbatim, as the equivalence oracle
    home = rules["_home"]
    for cand in {Path(os.path.abspath(path)), dh._real(path)}:
        for nt in rules["_never_paths"]:
            for ntp in {Path(os.path.abspath(nt)), dh._real(nt)}:
                if dh.is_within(cand, ntp):
                    return f"never_touch_path:{ntp}"
                if dh.is_within(ntp, cand):
                    return f"contains_never_touch_path:{ntp}"
        try:
            parts = cand.relative_to(home).parts if dh.is_within(cand, home) else cand.parts
        except ValueError:
            parts = cand.parts
        for part in parts:
            if part in rules["_never_names"]:
                return f"never_touch_name:{part}"
            for g in rules["_never_globs"]:
                if fnmatch.fnmatch(part.lower(), g.lower()):
                    return f"never_touch_glob:{g}:{part}"
    return None


def test_same_verdicts_as_the_unoptimised_rule(tmp_path):
    rules = _rules(tmp_path)
    samples = [tmp_path, tmp_path / ".cache" / "agent-tmp" / "x" / "f", Path("/"), Path("/etc/passwd"), tmp_path / ".ssh" / "id"]
    samples += [Path(p) for p in rules["_never_paths"]]
    samples += [Path(p) / "child" for p in rules["_never_paths"]]
    samples += [Path(p).parent for p in rules["_never_paths"]]
    samples += [tmp_path / n for n in list(rules["_never_names"])[:5] + ["my_token_file", "SECRET_x", "ok.txt"]]
    for p in samples:
        assert dh.never_touch_reason(p, rules) == _old_reason(p, rules), p


def test_never_touch_list_is_resolved_once_not_per_entry(tmp_path, monkeypatch):
    rules = _rules(tmp_path)
    entry = tmp_path / ".cache" / "agent-tmp" / "x" / "f"
    dh.never_touch_reason(entry, rules)  # warm the one-time resolution
    calls = []
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    for _ in range(50):
        dh.never_touch_reason(entry, rules)
    assert len(calls) <= 50 * 2, f"{len(calls)} realpath calls for 50 entries"
