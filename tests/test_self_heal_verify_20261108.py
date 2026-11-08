"""ANCHOR: SELF_HEAL_VERIFY_20261108 — the self-heal fixer's best-practice verification (LQ-20261107-1234).

Three properties are pinned:

1. A regression test is only evidence when it is RED ``n`` times on the base commit and GREEN ``n`` times
   after the fix. A run with no verdict (timeout, spawn failure) is neither.
2. A diff that masks the failure instead of fixing it is flagged, line by line: a new bare/broad
   ``except`` whose body is only ``pass``/``continue``, an early empty ``return`` on a failing path, a
   skip/xfail marker, a new ``conftest.py``, a deleted assertion, a forced exit code. Every rule has a
   positive fixture and a negative fixture that must stay clean.
3. The companion suite command never runs nothing: a change that resolves to no test runs the whole
   ``tests/`` tree.

Synthetic diffs and a scripted runner only: no command is executed, no repo is read.
"""

from __future__ import annotations

import pytest

from lib import self_heal_verify as V

# ------------------------------------------------------------------------------------ run helpers


class ScriptedRunner:
    """Returns the scripted exit codes in order and records every call's arguments."""

    def __init__(self, *codes):
        self.codes = list(codes)
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd=None, env=None, timeout_s=None):
        self.calls.append({"argv": list(argv), "cwd": cwd, "env": env, "timeout_s": timeout_s})
        return self.codes.pop(0)


def test_repro_reliable_needs_a_failure_in_every_run():
    runner = ScriptedRunner(1, 1, 2)  # any non-zero is a failure: the test does not need one fixed code
    assert V.repro_reliable("python -m pytest tests/test_x.py -q", runner=runner) is True
    assert len(runner.calls) == 3
    assert runner.calls[0]["argv"] == ["python", "-m", "pytest", "tests/test_x.py", "-q"]


def test_one_green_run_is_not_a_reliable_repro():
    assert V.repro_reliable(["pytest", "x"], runner=ScriptedRunner(1, 0, 1)) is False
    assert V.repro_reliable(["pytest", "x"], runner=ScriptedRunner(0, 0, 0)) is False


def test_a_run_without_a_verdict_is_not_a_reliable_repro():
    """A timeout or a spawn failure did not demonstrate the defect, so it cannot count as red (or green)."""
    assert V.repro_reliable(["pytest", "x"], runner=ScriptedRunner(1, None, 1)) is False
    assert V.fixed_reliably(["pytest", "x"], runner=ScriptedRunner(0, None, 0)) is False


def test_fixed_reliably_needs_a_pass_in_every_run():
    assert V.fixed_reliably(["pytest", "x"], runner=ScriptedRunner(0, 0, 0)) is True
    assert V.fixed_reliably(["pytest", "x"], runner=ScriptedRunner(0, 1, 0)) is False


def test_run_n_is_the_raw_observation_the_verdicts_are_computed_from():
    assert V.run_n(["pytest", "x"], runner=ScriptedRunner(3, 0, None)) == [3, 0, None]
    assert V.run_n(["pytest", "x"], n=2, runner=ScriptedRunner(1, 1)) == [1, 1]


def test_n_defaults_to_three_and_must_be_a_positive_int():
    runner = ScriptedRunner(1, 1, 1)
    assert V.repro_reliable(["pytest", "x"], runner=runner) is True
    assert len(runner.calls) == 3
    for bad in (0, -1, True, 1.5, "3"):
        with pytest.raises(ValueError):
            V.run_n(["pytest", "x"], bad, runner=ScriptedRunner(1))


def test_the_runner_receives_cwd_env_and_the_configured_timeout():
    runner = ScriptedRunner(0)
    env = {"TRADE_AI_CI": "1"}
    V.fixed_reliably(["pytest", "x"], n=1, runner=runner, cwd="/tmp/wt", env=env, timeout_s=42.0)
    assert runner.calls == [{"argv": ["pytest", "x"], "cwd": "/tmp/wt", "env": env, "timeout_s": 42.0}]


def test_a_command_string_is_split_and_an_empty_command_is_refused():
    assert V.run_n("pytest 'tests/x y.py' -q", n=1, runner=ScriptedRunner(0)) == [0]
    with pytest.raises(ValueError):
        V.run_n("   ", n=1, runner=ScriptedRunner(0))


# ------------------------------------------------------------------------------------ diff fixtures


def _diff(path: str, hunk: str, *, created: bool = False) -> str:
    head = f"diff --git a/{path} b/{path}\n"
    if created:
        head += "new file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
    else:
        head += "index 1111111..2222222 100644\n--- a/" + path + "\n"
    return head + f"+++ b/{path}\n" + hunk


def _rules(findings):
    return [(f["rule"], f["path"], f["line"]) for f in findings]


# ------------------------------------------------------------------------------------ 1. broad except

BROAD_EXCEPT_PASS = _diff(
    "scripts/lib/foo.py",
    "@@ -10,5 +10,7 @@ def load(path):\n"
    "     try:\n"
    "         return read(path)\n"
    "-    except FileNotFoundError:\n"
    "-        raise\n"
    "+    except Exception:\n"
    "+        pass\n"
    "     finally:\n"
    "         close()\n",
)


def test_a_new_broad_except_that_swallows_the_error_is_flagged():
    findings = V.lint_masking(BROAD_EXCEPT_PASS)
    assert _rules(findings) == [("broad_except_swallow", "scripts/lib/foo.py", 12)]
    assert findings[0]["schema"] == V.FINDING_SCHEMA
    assert findings[0]["text"] == "except Exception:"


def test_a_bare_except_and_an_inline_pass_are_flagged_too():
    for header in ("except:", "except Exception as exc:", "except BaseException:"):
        diff = _diff("scripts/a.py", f"@@ -1,3 +1,4 @@\n def f():\n-    pass\n+    {header} pass\n     return 1\n")
        assert [f["rule"] for f in V.lint_masking(diff)] == ["broad_except_swallow"], header


def test_a_narrow_handler_or_a_handler_that_reraises_is_not_flagged():
    narrow = _diff(
        "scripts/a.py",
        "@@ -1,3 +1,4 @@\n def f():\n-    pass\n+    except ValueError:\n+        pass\n     return 1\n",
    )
    reraise = _diff(
        "scripts/a.py",
        "@@ -1,3 +1,5 @@\n def f():\n+    except Exception:\n+        log.exception('load failed')\n+        raise\n     return 1\n",
    )
    assert V.lint_masking(narrow) == []
    assert V.lint_masking(reraise) == []


# ------------------------------------------------------------------------------------ 2. empty return


def test_an_empty_return_inside_a_new_broad_except_is_flagged():
    diff = _diff(
        "scripts/lib/bar.py",
        "@@ -20,4 +20,7 @@ def count(rows):\n"
        "     try:\n"
        "         return parse(rows)\n"
        "+    except Exception:\n"
        "+        return []\n"
        "     finally:\n"
        "         done()\n",
    )
    assert _rules(V.lint_masking(diff)) == [("empty_return_stub", "scripts/lib/bar.py", 23)]


def test_a_stub_function_body_is_flagged():
    diff = _diff(
        "scripts/lib/baz.py",
        '@@ -1,2 +1,6 @@\n def existing():\n     return 1\n+def guard(x):\n+    """Doc."""\n+    return None\n',
    )
    assert _rules(V.lint_masking(diff)) == [("empty_return_stub", "scripts/lib/baz.py", 5)]


def test_an_empty_return_that_is_not_on_a_failing_path_is_not_flagged():
    narrow = _diff(
        "scripts/lib/q.py",
        "@@ -1,3 +1,5 @@\n def f(x):\n+    try:\n+        return g(x)\n+    except ValueError:\n+        return None\n     return 2\n",
    )
    fallback = _diff(
        "scripts/lib/q.py",
        "@@ -1,3 +1,4 @@\n def f(x):\n     y = g(x)\n+    return None\n",
    )
    assert V.lint_masking(narrow) == []
    assert V.lint_masking(fallback) == []


# ------------------------------------------------------------------------------------ 3. test suppression


def test_skip_skipif_xfail_and_deselect_are_flagged():
    cases = [
        "+    @pytest.mark.skip(reason='flaky')\n",
        "+    @pytest.mark.skipif(os.name == 'posix', reason='x')\n",
        "+    @pytest.mark.xfail(strict=False)\n",
        "+    pytest.skip('not today')\n",
        "+    self.skipTest('later')\n",
        "+    pytest --deselect tests/test_a.py::test_b\n",
        "+    pytest -q -k 'not test_a'\n",
    ]
    for added in cases:
        diff = _diff("tests/test_a.py", "@@ -1,2 +1,3 @@\n def test_a():\n" + added + "     assert 1\n")
        assert [f["rule"] for f in V.lint_masking(diff)] == ["test_suppression"], added


def test_a_comment_or_a_plain_assertion_is_not_flagged():
    comment = _diff("tests/test_a.py", "@@ -1,2 +1,3 @@\n def test_a():\n+    # pytest.mark.skip is banned by the guard\n     assert 1\n")
    plain = _diff("tests/test_a.py", "@@ -1,2 +1,3 @@\n def test_a():\n+    with pytest.raises(ValueError):\n+        parse('')\n     assert 1\n")
    assert V.lint_masking(comment) == []
    assert V.lint_masking(plain) == []


# ------------------------------------------------------------------------------------ 4. new conftest


def test_a_new_conftest_is_flagged():
    diff = _diff("tests/conftest.py", "@@ -0,0 +1,3 @@\n+import pytest\n+\n+def pytest_collection_modifyitems(items):\n", created=True)
    assert _rules(V.lint_masking(diff)) == [("new_conftest", "tests/conftest.py", 1)]


def test_an_edited_conftest_is_not_a_new_one():
    diff = _diff("tests/conftest.py", "@@ -1,2 +1,3 @@\n import pytest\n+TRADE_AI_CI = 1\n")
    assert V.lint_masking(diff) == []


# ------------------------------------------------------------------------------------ 5. deleted asserts


def test_a_deleted_assertion_is_flagged():
    diff = _diff(
        "tests/test_a.py",
        "@@ -5,3 +5,3 @@ def test_a():\n     out = run()\n-    assert out == 0\n     assert out < 2\n",
    )
    findings = V.lint_masking(diff)
    assert _rules(findings) == [("deleted_assert", "tests/test_a.py", 6)]
    assert findings[0]["text"] == "assert out == 0"


def test_an_assertion_restated_with_a_message_is_not_flagged():
    diff = _diff(
        "tests/test_a.py",
        '@@ -5,2 +5,2 @@ def test_a():\n     out = run()\n-    assert out == 0\n+    assert out == 0, "the run must succeed"\n',
    )
    assert V.lint_masking(diff) == []


def test_only_the_surplus_of_removed_assertions_is_flagged():
    diff = _diff(
        "tests/test_a.py",
        "@@ -5,4 +5,3 @@ def test_a():\n     out = run()\n-    assert out == 0\n-    assert out < 2\n+    assert out == 0, 'ok'\n",
    )
    assert _rules(V.lint_masking(diff)) == [("deleted_assert", "tests/test_a.py", 6)]


# ------------------------------------------------------------------------------------ 6. forced exit


def test_forced_exit_codes_are_flagged():
    cases = [
        "+    sys.exit(0)\n",
        "+    raise SystemExit(0)\n",
        "+    os._exit(0)\n",
        "+    pytest tests/test_a.py || true\n",
        "+    run_the_lane || :\n",
        "+    set +e\n",
    ]
    for added in cases:
        diff = _diff("scripts/a.py", "@@ -1,2 +1,3 @@\n def f():\n" + added + "     return 1\n")
        assert [f["rule"] for f in V.lint_masking(diff)] == ["forced_exit"], added


def test_a_failure_exit_or_a_raise_is_not_flagged():
    failure = _diff("scripts/a.py", "@@ -1,2 +1,3 @@\n def f():\n+    sys.exit(1)\n     return 1\n")
    reraises = _diff("scripts/a.py", "@@ -1,2 +1,4 @@\n def f():\n+    except Exception:\n+        raise SystemExit(2)\n     return 1\n")
    assert V.lint_masking(failure) == []
    assert V.lint_masking(reraises) == []


# ------------------------------------------------------------------------------------ diff-level shape


def test_an_additive_diff_produces_no_findings():
    diff = _diff(
        "scripts/lib/foo.py",
        "@@ -10,2 +10,4 @@ def load(path):\n     rows = read(path)\n+    log.info('loaded %d rows', len(rows))\n"
        "+    return rows\n",
    )
    assert V.lint_masking(diff) == []


def test_findings_are_positioned_in_the_new_file_and_stably_ordered():
    diff = (
        _diff(
            "scripts/b_second.py",
            "@@ -3,2 +3,3 @@ def g():\n     x = 1\n+    sys.exit(0)\n",
        )
        + _diff(
            "scripts/a_first.py",
            "@@ -1,3 +1,4 @@ def f():\n     try:\n+        pass\n     finally:\n         done()\n"
            "@@ -20,2 +21,4 @@ def h():\n     y = 2\n+    except Exception:\n+        pass\n",
        )
    )
    findings = V.lint_masking(diff)
    assert [(f["path"], f["line"], f["rule"]) for f in findings] == [
        ("scripts/a_first.py", 22, "broad_except_swallow"),
        ("scripts/b_second.py", 4, "forced_exit"),
    ]
    assert all(set(f) == {"schema", "rule", "path", "line", "text", "message"} for f in findings)


def test_an_empty_or_non_diff_input_has_no_findings():
    assert V.lint_masking("") == []
    assert V.lint_masking("not a diff at all\n") == []
    assert V.lint_masking("Binary files a/x and b/x differ\n") == []


# ------------------------------------------------------------------------------------ full suite cmd


def test_a_touched_test_is_the_suite():
    assert V.full_suite_cmd(["tests/test_a.py"]) == ["python", "-m", "pytest", "-q", "tests/test_a.py"]


def test_a_changed_module_selects_the_tests_whose_names_carry_its_stem():
    cmd = V.full_suite_cmd(
        ["scripts/lib/self_heal_verify.py"],
        known_tests=["tests/test_self_heal_verify_20261108.py", "tests/test_other.py"],
    )
    assert cmd == ["python", "-m", "pytest", "-q", "tests/test_self_heal_verify_20261108.py"]


def test_no_narrow_suite_means_the_whole_tree_never_nothing():
    assert V.full_suite_cmd([]) == ["python", "-m", "pytest", "-q", "tests"]
    assert V.full_suite_cmd(["scripts/lib/unknown_module.py"], known_tests=["tests/test_a.py"]) == [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests",
    ]
    assert V.full_suite_cmd(["README.md"]) == ["python", "-m", "pytest", "-q", "tests"]


def test_the_diff_test_files_and_the_neighbours_are_merged_and_deduplicated():
    cmd = V.full_suite_cmd(
        ["tests/test_a.py", "scripts/lib/foo.py", "scripts/lib/foo_extra.py", "./scripts/lib/foo.py"],
        known_tests=["tests/test_a.py", "tests/test_foo_20261016.py", "tests/test_foo_extra_20261017.py"],
    )
    assert cmd == [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_a.py",
        "tests/test_foo_20261016.py",
        "tests/test_foo_extra_20261017.py",
    ]


def test_the_pytest_entry_point_and_tests_root_are_configurable():
    cmd = V.full_suite_cmd(
        ["tests/test_a.py"],
        pytest_cmd="/repo/.venv/bin/python -m pytest -x",
        tests_root="./tests",
    )
    assert cmd == ["/repo/.venv/bin/python", "-m", "pytest", "-x", "-q", "tests/test_a.py"]
