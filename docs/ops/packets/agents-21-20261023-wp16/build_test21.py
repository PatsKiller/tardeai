"""Generate tests/test_agents_policy_21_0_0_advisory_sizing.py into src/ from build_ratify21.py and the base.

Clause literals are copied byte for byte; every digest is computed here on the base (current 20.1.0 ACTIVE) and on a simulated 21.0.0 ratification, so the test pins them in advance. The pinned sections and
adapters hold no PR, SHA or date, so the digests are the same on this exact 20.1.0 base.
usage: python build_test21.py   (reads base/, out_AGENTS.proposed.md; writes src/tests/...)
"""

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

A = Path(__file__).resolve().parent
BASE, PROPOSED, OUT = map(Path, sys.argv[1:4])
spec = importlib.util.spec_from_file_location("build_ratify21", A / "build_ratify21.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
h = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()  # noqa: E731

BOUNDS = {
    "§0": ("# 0 · If you read nothing else", "# 1 · Identity and responsibilities"),
    "§2": ("# 2 · Authority rails", "# 2A ·"),
    "§2A": ("# 2A ·", "# 2B ·"),
    "§7": ("# 7 · ", "# 7A ·"),
    "§7A": ("# 7A ·", "# 8 ·"),
    "§13": ("# 13 · ", "# 14 · "),
    "§17": ("# 17 · Operator-only decisions", "# 17A ·"),
    "§22": ("# 22 · ", "# 23 · "),
    "§23": ("# 23 · ", "# 24 · "),
    "§24": ("# 24 · ", "# 25 · "),
    "§26": ("# 26 · ", "# 27 · "),
    "§27": ("# 27 · ", "# 28 · "),
}
CHANGING = ("§0", "§17", "§26")
FIXED = ("§2", "§2A", "§7", "§7A", "§13", "§22", "§23", "§24", "§27")


def section(text, name):
    start, end = BOUNDS[name]
    s = re.search(rf"^{re.escape(start)}", text, re.M)
    e = re.search(rf"^{re.escape(end)}", text[s.start() + 1 :], re.M)
    block = text[s.start() : s.start() + 1 + e.start()]
    return re.sub(
        r"(<!-- SOURCE_OF_TRUTH_TABLE_START -->).*?(<!-- SOURCE_OF_TRUTH_TABLE_END -->)",
        r"\1\n<generated>\n\2",
        block,
        flags=re.S,
    )


base = (BASE / "AGENTS.md").read_text(encoding="utf-8")
proposed = PROPOSED.read_text(encoding="utf-8")
ratified_body = R.clause_edits(proposed)
pre = {n: h(section(base, n)) for n in CHANGING + FIXED}
for n in CHANGING + FIXED:
    assert h(section(proposed, n)) == pre[n], f"proposed changed {n}"
    assert R._TOKEN20 not in section(base, n), f"{n} holds 20.0.0 ratification values"
post = {n: h(section(ratified_body, n)) for n in CHANGING}
adapters_pre = {a: h((BASE / a).read_text(encoding="utf-8")) for a in R.ADAPTERS}
adapters_post = {a: h(R.adapter_edit((BASE / a).read_text(encoding="utf-8"))) for a in R.ADAPTERS}

lits = []
for n in R.CLAUSES:
    lits.append(f"{n} = (")
    for line in getattr(R, n).splitlines(keepends=True):
        lits.append("    " + repr(line))
    lits.append(")")
sha_map = {n: h(getattr(R, n)) for n in R.CLAUSES}

T = (A / "test_agents_policy_21_0_0_advisory_sizing.py.in").read_text(encoding="utf-8")
fill = {
    "@CLAUSES@": "\n".join(lits),
    "@CLAUSE_SHA@": "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in sha_map.items()) + "}",
    "@PRE@": "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in pre.items()) + "}",
    "@POST@": "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in post.items()) + "}",
    "@ADAPTERS_PRE@": "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in adapters_pre.items()) + "}",
    "@ADAPTERS_POST@": "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in adapters_post.items()) + "}",
}
for k, v in fill.items():
    assert T.count(k) == 1, k
    T = T.replace(k, v)
dst = OUT / "tests" / "test_agents_policy_21_0_0_advisory_sizing.py"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(T, encoding="utf-8")
print("wrote", dst)
for k, v in post.items():
    print(f"  post {k:5s} {v}")
