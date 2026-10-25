"""Rebuild and verify an inert, exact-base-bound operator proposal. No remote writes."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python")
ADAPTERS = ("CLAUDE.md", ".cursor/rules/00-tradeai-work-policy.mdc", ".github/copilot-instructions.md", ".goosehints")
OLD_TESTS = (
    "10_0_0_n8n_fabric",
    "11_0_0_workflow_framework",
    "12_0_0_cutover_directive",
    "14_0_0_broker_read",
    "15_0_0_disk_hygiene",
    "16_0_0_cutover_standard",
    "17_0_0_release_train",
    "18_0_0_data_foundation",
    "19_0_0_broker_read_controls",
    "1_3_0_amendment",
    "20_0_0_agent_operations",
    "3_0_0_amendment",
    "4_0_0_scalp_lane",
    "4_1_0_amendment",
    "4_3_0_r1_classes",
    "4_4_0_r1_shadow_shape",
    "4_6_0_platform_rules",
    "5_0_0_execution_ops",
    "5_1_0_notification_intents",
    "5_2_0_validation",
    "7_0_0_advisory_market_data",
)


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, text=True, **kwargs)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scratch(prefix):
    root = Path.home() / ".cache/rtc/codex-wp16-20261023"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))


def export(repo, sha, target):
    target.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(["git", "-C", str(repo), "archive", sha], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-xf", "-", "-C", str(target)], stdin=p.stdout, check=True)
    p.stdout.close()
    if p.wait():
        raise RuntimeError("git archive failed")


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_file(rel, before, after):
    if before == after:
        return ""
    header = f"diff --git a/{rel} b/{rel}\n"
    if before is None:
        header += "new file mode 100644\n"
    text = header + "".join(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{rel}" if before is not None else "/dev/null",
            tofile=f"b/{rel}",
            n=3,
        )
    )
    # Git accepts an unprefixed empty context line. Normalize only that exact line,
    # retaining all source whitespace while keeping the patch artifact whitespace-clean.
    return "".join("\n" if line == " \n" else line for line in text.splitlines(keepends=True))


def rebuild(repo, ref):
    sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", ref], text=True).strip()
    work = scratch("rebuild-")
    base, proposed, src = work / "base", work / "AGENTS.proposed.md", work / "src"
    export(repo, sha, base)
    agents = (base / "AGENTS.md").read_text()
    assert re.search(r"^Policy-Version:\s+20\.1\.0$", agents, re.M), "Rebuild needed for a new base policy"
    assert re.search(r"^Status:\s+ACTIVE$", agents, re.M)
    run([sys.executable, HERE / "build_agents21.py", base / "AGENTS.md", proposed])
    run([sys.executable, HERE / "build_test21.py", base, proposed, src])
    module = src / "scripts/lib/cio_advisory_sizing.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text((HERE / "cio_advisory_sizing.py.in").read_text())

    # Existing section pins undo only the new ratifying clauses; the20.1 whole-document pin
    # additionally removes this proposal's own header/banner/section/row before comparing.
    add = (
        "from tests.test_agents_policy_21_0_0_advisory_sizing import pre_21_0_0, pre_21_0_0_adapter  # noqa: E402\n"
        "AGENTS = pre_21_0_0(AGENTS)\n"
    )
    line = 'AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")\n'
    for name in OLD_TESTS:
        rel = Path("tests") / f"test_agents_policy_{name}.py"
        text = (base / rel).read_text()
        assert text.count(line) == 1, rel
        text = text.replace(line, line + add)
        if name == "4_6_0_platform_rules":
            text = text.replace('(20, 1, 0): {"20.0.0"}}.get(', '(20, 1, 0): {"20.0.0"}, (21, 0, 0): {"20.1.0"}}.get(')
            text = text.replace(
                'pre_20_0_0_adapter((ROOT / "CLAUDE.md").read_text(encoding="utf-8"))',
                'pre_20_0_0_adapter(pre_21_0_0_adapter((ROOT / "CLAUDE.md").read_text(encoding="utf-8")))',
            )
        if name == "20_0_0_agent_operations":
            text = text.replace("(?=^# Version history)", "(?=^# 29 · |^# Version history)")
            text = text.replace(
                'text = (ROOT / adapter).read_text(encoding="utf-8")',
                'text = pre_21_0_0_adapter((ROOT / adapter).read_text(encoding="utf-8"))',
            )
        dst = src / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
    test21 = src / "tests/test_agents_policy_21_0_0_advisory_sizing.py"
    header_keys = ("Policy-Version", "Status", "Effective-Date", "Last-Reviewed", "Supersedes")
    header = {k: re.search(r"^" + re.escape(k) + r":\s+(.+)$", agents, re.M).group(1) for k in header_keys}
    restore = (
        """\n\nBASE_POLICY_HEADER = %r

def pre_21_0_0_document(text):
    text = pre_21_0_0(text)
    if not re.search(r"^\\| 21\\.0\\.0 \\|", text, re.M):
        return text
    start = text.index("**21.0.0 is ")
    text = text[:start] + text[text.index("**20.1.0 is ", start):]
    start = text.index("\\n# 29 · Advisory size suggestions")
    text = text[:start] + text[text.index("\\n# Version history", start):]
    text = re.sub(r"^\\| 21\\.0\\.0 \\|.*\\n", "", text, count=1, flags=re.M)
    for key, value in BASE_POLICY_HEADER.items():
        text = re.sub(r"^("+re.escape(key)+r":\\s+).*$", lambda m: m.group(1)+value,
                      text, count=1, flags=re.M)
    return text
"""
        % header
    )
    test21.write_text(test21.read_text() + restore)
    rel = Path("tests/test_agents_policy_20_1_0_live_server_market_hours.py")
    text = (base / rel).read_text()
    text = text.replace(
        line,
        line
        + "from tests.test_agents_policy_21_0_0_advisory_sizing import pre_21_0_0_document, pre_21_0_0_adapter  # noqa: E402\nAGENTS = pre_21_0_0_document(AGENTS)\n",
    )
    text = text.replace(
        'h((ROOT / a).read_text(encoding="utf-8"))', 'h(pre_21_0_0_adapter((ROOT / a).read_text(encoding="utf-8")))'
    )
    (src / rel).write_text(text)

    sys.path.insert(0, str(base))
    from scripts.lib.ci_gates import make_record, render

    gate = src / "config/ci_gates/agents_policy_21_0_0_advisory_sizing.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        render(
            make_record(
                "agents_policy_21_0_0_advisory_sizing",
                ["tests/test_agents_policy_21_0_0_advisory_sizing.py"],
                [
                    "ANCHOR: AGENTS_POLICY_21_0_0_ADVISORY_SIZING — operator-applied MAJOR proposal; inert until actual ratification.",
                    "Pins exact clause scope, pure deterministic arithmetic, complete facts, model-key stripping and unchanged behavior rail.",
                ],
            )
        )
    )

    # Only the new module/test are formatted; existing policy pins keep their source layout.
    run([PY.parent / "ruff", "format", module, test21], cwd=base)

    (HERE / "agents-21.0.0-proposed.patch").write_text(patch_file("AGENTS.md", agents, proposed.read_text()))
    chunks = []
    hashes = {}
    for rel in sorted(p.relative_to(src) for p in src.rglob("*") if p.is_file()):
        old = base / rel
        hashes[str(rel)] = digest(old) if old.exists() else None
        chunks.append(patch_file(str(rel), old.read_text() if old.exists() else None, (src / rel).read_text()))
    for rel in ("AGENTS.md", *ADAPTERS, "scripts/lib/cio_instrument_record.py"):
        hashes[rel] = digest(base / rel)
    (HERE / "code-tests-21.0.0.patch").write_text("".join(chunks))
    (HERE / "BASE_SHA").write_text(sha + "\n")
    (HERE / "BASE_MANIFEST.json").write_text(
        json.dumps({"base_sha": sha, "policy": "20.1.0 ACTIVE", "files": hashes}, indent=2) + "\n"
    )
    checksum = "".join(
        f"{digest(p)}  {p.name}\n" for p in sorted(HERE.iterdir()) if p.is_file() and p.name != "SHA256SUMS"
    )
    (HERE / "SHA256SUMS").write_text(checksum)
    print(
        json.dumps(
            {
                "rebuilt": sha,
                "artifact_root": str(HERE),
                "scratch": str(work),
                "manifest": digest(HERE / "BASE_MANIFEST.json"),
            }
        )
    )


def check_package():
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        if digest(HERE / name) != expected:
            raise RuntimeError(f"Package checksum drift: {name}")


def check_base(repo, ref):
    manifest = json.loads((HERE / "BASE_MANIFEST.json").read_text())
    for rel, expected in manifest["files"].items():
        p = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{rel}"], capture_output=True)
        got = hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else None
        if got != expected:
            raise RuntimeError(f"Base drift at {rel}; rebuild on current policy (including WP-15 if it lands first)")


def apply_proposed(root):
    for name in ("agents-21.0.0-proposed.patch", "code-tests-21.0.0.patch"):
        run(["git", "apply", "--check", HERE / name], cwd=root)
        run(["git", "apply", HERE / name], cwd=root)


def verify(repo, stages):
    check_package()
    sha = (HERE / "BASE_SHA").read_text().strip()
    check_base(repo, sha)
    result = []
    for stage in stages:
        out = scratch("verify-" + stage + "-")
        root = out / "tree"
        export(repo, sha, root)
        if stage != "none":
            apply_proposed(root)
        if stage == "ratified":
            load_module("build_ratify21").ratify(
                root, 9998, "89abcdef0123456789abcdef0123456789abcdef", "2", "2026-10-23T16:00:00Z", "2026-10-23"
            )
        env = __import__("os").environ.copy()
        env.update(TMPDIR=str(out), TRADE_AI_CI="1", PYTHONDONTWRITEBYTECODE="1")
        tests = sorted(str(p.relative_to(root)) for p in (root / "tests").glob("test_agents_policy_*.py"))
        tests += ["tests/test_agents_section_zero_parity.py"]
        with (out / "tests.log").open("w") as log:
            p = subprocess.run(
                [str(PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        state = subprocess.run(
            [str(PY), "scripts/check_agents_policy_state.py", "--on-main"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        row = {
            "stage": stage,
            "tests_rc": p.returncode,
            "state_rc": state.returncode,
            "state": state.stdout.strip(),
            "evidence": str(out),
        }
        result.append(row)
        print(json.dumps(row), flush=True)
        if p.returncode or state.returncode:
            print((out / "tests.log").read_text()[-6500:])
            raise SystemExit(1)
    receipt = scratch("acceptance-") / "result.json"
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    print("acceptance_receipt=" + str(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("rebuild")
    b.add_argument("--source", type=Path, default=HERE.parents[3])
    b.add_argument("--base", default="origin/main")
    v = sub.add_parser("verify")
    v.add_argument("stage", choices=["none", "proposed", "ratified", "all"])
    v.add_argument("--source", type=Path, default=HERE.parents[3])
    args = parser.parse_args()
    if args.command == "rebuild":
        rebuild(args.source, args.base)
    else:
        verify(args.source, ["none", "proposed", "ratified"] if args.stage == "all" else [args.stage])
