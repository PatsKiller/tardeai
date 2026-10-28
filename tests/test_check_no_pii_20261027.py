"""ANCHOR: SECRET_PII_SCAN_20261027 -- the standing secret + personal-data scan.

Operator request, 2026-10-27, verbatim: "would need some validates or checks that I don't have any type of
secrets or codes or anything identifiable in the codes and GitHub that should also be in the agents.md".

Pins scripts/check_no_pii.py (every category, the ratchet and its CI guard, value-free output, blocked paths,
the policy-snapshot exclusion, range vs tree, inline markers never honoured, fail-closed) and the shape of
.github/workflows/secret-scan.yml (main's rules copied over the checkout before gitleaks, allow comments
ignored), .gitleaks.toml, .gitleaksignore and config/pii_baseline.json.

Hermetic: synthetic strings only, assembled at runtime so this file itself never contains a value the scanner
would flag; git work happens in tmp_path repositories with HOME pointed at tmp_path. No network, no gitleaks.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts import check_no_pii as pii

ROOT = Path(__file__).resolve().parents[1]
AT = "@"
DOT = "."
BS = "\\"

# Synthetic values, assembled so no literal match sits in this source file.
PERSONAL_EMAIL = "jdoe.fixture" + AT + "personal-mailbox" + DOT + "com"
HOME_PATH = "/home/" + "jdoe" + "fixture/project/file.py"
MAC_HOME = "/Users/" + "jdoe" + "fixture/Library/x"
WIN_HOME = "C:" + BS + "Users" + BS + "jdoe" + "fixture" + BS + "proj"
ACCT_DIGITS = "4" + "8151623"
CHAT_DIGITS = "-100" + "9876543210"
IP_10 = DOT.join(["10", "1", "2", "3"])
IP_172 = DOT.join(["172", "20", "0", "5"])
IP_192 = DOT.join(["192", "168", "1", "20"])
IP_TS = DOT.join(["100", "101", "102", "103"])
DOB_VALUE = "1984-07-" + "23"
MARKER = "pii" + "-ok"


def cats(text: str, deny=None, lines=None) -> list[str]:
    return [f.category for f in pii.scan_text("f.txt", text, deny or [], lines)]


# ── categories ───────────────────────────────────────────────────────────────────────────────────────


def test_personal_email_is_flagged_and_examples_are_not():
    assert cats(f"contact: {PERSONAL_EMAIL}\n") == ["email"]
    allowed = [
        "ops" + AT + "example" + DOT + "com",
        "a" + AT + "sub.example" + DOT + "org",
        "noreply" + AT + "anthropic" + DOT + "com",
        "12345+bot" + AT + "users.noreply.github" + DOT + "com",
        "git" + AT + "github" + DOT + "com",
        "x" + AT + "host" + DOT + "test",
        "tradeai-job" + AT + "nightly" + DOT + "timer",  # systemd template unit, not an address
        "icon" + AT + "2x" + DOT + "png",
    ]
    assert cats("\n".join(allowed)) == []


def test_date_of_birth_needs_a_real_looking_date():
    assert cats(f"dob: {DOB_VALUE}\n") == ["date_of_birth"]
    assert cats(f'"date_of_birth": "{DOB_VALUE}"\n') == ["date_of_birth"]
    assert cats('birth_date = "07/23/' + '1984"\n') == ["date_of_birth"]
    assert cats(f"user_dob = {DOB_VALUE}\n") == ["date_of_birth"]  # "_" before the keyword
    assert cats(f"OWNER_BIRTH_DATE: {DOB_VALUE}\n") == ["date_of_birth"]
    assert cats("dob: 1990-01-01\n") == []  # placeholder
    assert cats("birth_date: 1984-13-40\n") == []  # not a date
    assert cats("dob: 2999-07-23\n") == []  # future
    assert cats(f"created: {DOB_VALUE}\n") == []  # no dob keyword
    assert cats(f"adobe: {DOB_VALUE}\n") == []  # "dob" inside a word


def test_account_numbers_next_to_account_words():
    assert cats(f"account_number: {ACCT_DIGITS}\n") == ["account_number"]
    assert cats(f"Roth IRA #{ACCT_DIGITS}\n") == ["account_number"]
    assert cats(f"routing {ACCT_DIGITS}\n") == ["account_number"]
    assert cats(f"{ACCT_DIGITS} acct\n") == ["account_number"]
    assert cats(f'"broker_account": "{ACCT_DIGITS}"\n') == ["account_number"]  # "_" before the keyword
    assert cats(f"bank_routing_number={ACCT_DIGITS}\n") == ["account_number"]
    assert cats(f"acct_{ACCT_DIGITS}\n") == ["account_number"]
    assert cats("account: 12345\n") == []  # five digits
    assert cats("ROUTING_DECISION_" + "20261027\n") == []  # an anchor id, not an account
    assert cats("ACCOUNT_LABELS_" + "20261023\n") == []
    assert cats("account_id: " + "20261027\n") == []  # date-shaped


def test_letter_prefixed_broker_account_ids():
    assert cats("U" + "1234567 and Z" + "12345678\n") == ["account_number", "account_number"]
    assert cats("U" + "123456\n") == []  # too short
    assert cats("AU" + "12345678\n") == []  # part of a longer token
    assert cats("u" + "1234567\n") == []  # case-sensitive


def test_account_fast_path_matches_the_reference_regex():
    samples = [
        f"account_number: {ACCT_DIGITS} and {ACCT_DIGITS} acct",
        f"xacct {ACCT_DIGITS}; IRA#{ACCT_DIGITS}; spiral {ACCT_DIGITS} ira.",
        f"Account-No {ACCT_DIGITS[:3]}-{ACCT_DIGITS[3:]}",
        f"{ACCT_DIGITS}account routing_number={ACCT_DIGITS}",
        f"broker_account_{ACCT_DIGITS} {ACCT_DIGITS}_acct bank_routing_number: {ACCT_DIGITS}",
    ]
    for s in samples:
        ref = []
        for m in pii.ACCOUNT_RE.finditer(s):
            g = 1 if m.group(1) else 2
            ref.append((m.start(g), m.group(g)))
        assert pii._account_numbers(s, s.lower()) == sorted(set(ref)), s


def test_telegram_chat_id():
    assert cats(f"chat_id = {CHAT_DIGITS}\n") == ["telegram_chat_id"]
    assert cats(f'{{"chat_id": "{CHAT_DIGITS[1:]}"}}\n') == ["telegram_chat_id"]
    assert cats(f"TELEGRAM_CHAT_ID={CHAT_DIGITS}\n") == ["telegram_chat_id"]  # "_" before the keyword
    assert cats(f"OPERATOR_CHAT_ID: {CHAT_DIGITS[1:]}\n") == ["telegram_chat_id"]
    assert cats(f"chat_ids = [{CHAT_DIGITS}]\n") == ["telegram_chat_id"]
    assert cats("chat_id: 12345\n") == []


def test_private_and_tailscale_addresses_but_not_ranges_or_public():
    assert cats(f"{IP_10} {IP_172} {IP_192} {IP_TS}\n") == ["private_ip"] * 4
    public_or_ranges = [
        DOT.join(["172", "32", "0", "1"]),
        DOT.join(["100", "128", "0", "1"]),
        DOT.join(["8", "8", "8", "8"]),
        DOT.join(["10", "0", "0", "0"]) + "/8",
        DOT.join(["100", "64", "0", "0"]) + "/10",
        DOT.join(["10", "300", "1", "1"]),
    ]
    assert cats(" ".join(public_or_ranges)) == []


def test_home_paths_for_real_users_only():
    assert cats(f"open('{HOME_PATH}')\n") == ["home_path"]
    assert cats(f"cd {MAC_HOME}\n") == ["home_path"]
    assert cats(f'cd /d "{WIN_HOME}"\n') == ["home_path"]
    assert cats(json.dumps({"p": WIN_HOME + BS}) + "\n") == ["home_path"]  # JSON-escaped backslashes
    assert cats("C:/Users/" + "jdoe" + "fixture/x\n") == ["home_path"]
    generic = "/home/runner/work/x /home/user/x /home/ubuntu/x /home/$USER/x /Users/Shared/x C:\\Users\\Public\\x"
    assert cats(generic + "\n") == []
    assert cats("https://api.example.com/Users/" + "jdoe" + "fixture/x\n") == []  # a URL path, not a home folder


def test_deny_patterns_come_from_a_file_outside_the_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    deny = tmp_path / "deny.txt"
    deny.write_text("# private\n" + "secret-handle-" + "zz\n", encoding="utf-8")
    pats = pii.load_deny_patterns(repo, {pii.DENY_ENV: str(deny)})
    assert cats("by Secret-Handle-" + "ZZ today\n", deny=pats) == ["deny_pattern"]
    assert pii.load_deny_patterns(repo, {}) == []

    inside = repo / "deny.txt"
    inside.write_text("x\n", encoding="utf-8")
    with pytest.raises(pii.ScanError, match="inside the repository"):
        pii.load_deny_patterns(repo, {pii.DENY_ENV: str(inside)})
    with pytest.raises(pii.ScanError, match="unreadable"):
        pii.load_deny_patterns(repo, {pii.DENY_ENV: str(tmp_path / "missing.txt")})
    bad = tmp_path / "bad.txt"
    bad.write_text("([unclosed\n", encoding="utf-8")
    with pytest.raises(pii.ScanError, match="invalid regex"):
        pii.load_deny_patterns(repo, {pii.DENY_ENV: str(bad)})


def test_no_inline_marker_silences_a_finding():
    assert cats(f"{IP_10}  # {MARKER} synthetic fixture\n") == ["private_ip"]
    assert cats(f"{IP_10}  # gitleaks" + ":allow\n") == ["private_ip"]
    pats = [re.compile("handle-" + "zz", re.I)]
    assert cats("handle-" + f"zz  # {MARKER}\n", deny=pats) == ["deny_pattern"]


def test_line_filter_limits_findings_to_given_lines():
    text = f"{IP_10}\nclean\n{IP_192}\n"
    found = pii.scan_text("f.txt", text, [], {3})
    assert [(f.line, f.category) for f in found] == [(3, "private_ip")]


# ── output never carries a value ─────────────────────────────────────────────────────────────────────


def test_findings_carry_location_and_category_only():
    f = pii.scan_text("f.txt", f"x {PERSONAL_EMAIL}\n", [])[0]
    assert (f.path, f.line, f.category, f.detail) == ("f.txt", 1, "email", "")
    blob = json.dumps(f.__dict__)
    assert PERSONAL_EMAIL[:3] not in blob and "personal-mailbox" not in blob


# ── blocked paths and the snapshot exclusion ─────────────────────────────────────────────────────────

BLOCKED = [
    ".env",
    "config/.env.local",
    ".env.production",
    "certs/server.pem",
    "deploy/id.key",
    "certs/client.p12",
    "certs/client.pfx",
    "android/release.jks",
    "home/.ssh/id_rsa",
    "keys/id_rsa.pub",
    "keys/id_ed25519",
    "keys/id_ecdsa.pub",
    ".netrc",
    "apps/web/.npmrc",
    "config/credentials.json",
    "secrets/token.json",
    "data/state.db",
    "data/cache.sqlite3",
    "debug/trace.har",
    "cookies.txt",
    "docs/sessions/notes.md",
    "a/persistent-state/data/x.json",
    "apps/web/.next/cache/info",
    "apps/web/tsconfig.app.tsbuildinfo",
    "tests/fixtures/holdings.json",
    "exports/holdings_2026.json",
    "tests/fixtures/agents_pre_26_0_0/.env",  # the snapshot exclusion never covers blocked paths
]
ALLOWED_PATHS = [
    ".env.example",
    "infra/searxng/.env.example",
    "scripts/keys.py",
    "src/key.ts",
    "docs/session_notes.md",
    "config/environment.json",
    "scripts/holdings_report.py",
    "docs/sessions.md",
    "docs/credentials.md",
    "scripts/token_json_util.py",
    "docs/ssh_keys.md",
]


@pytest.mark.parametrize("path", BLOCKED)
def test_blocked_paths(path: str):
    assert pii.blocked_reason(path)


@pytest.mark.parametrize("path", ALLOWED_PATHS)
def test_not_blocked_paths(path: str):
    assert pii.blocked_reason(path) is None


def test_snapshot_exclusion_is_exactly_the_agents_pre_fixture_folders():
    assert pii.snapshot_excluded("tests/fixtures/agents_pre_26_0_0/AGENTS.md")
    assert pii.snapshot_excluded("tests/fixtures/agents_pre_25_0_0/sub/CLAUDE.md")
    assert not pii.snapshot_excluded("tests/fixtures/agents_pre_26_0_0")  # the folder name itself
    assert not pii.snapshot_excluded("tests/fixtures/other/AGENTS.md")
    assert not pii.snapshot_excluded("docs/tests/fixtures/agents_pre_26_0_0/AGENTS.md")
    assert not pii.snapshot_excluded("tests/agents_pre_26_0_0/AGENTS.md")
    assert not pii.snapshot_excluded("AGENTS.md")


# ── git: range, tree and the baseline guard ──────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{k}_NAME", "fixture")
        monkeypatch.setenv(f"{k}_EMAIL", "fixture" + AT + "example" + DOT + "com")
    monkeypatch.delenv(pii.DENY_ENV, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], cwd=r, check=True)
    (r / "config").mkdir()
    (r / "docs" / "sessions").mkdir(parents=True)
    (r / "app.py").write_text(f"OLD_HOST = '{IP_10}'\n", encoding="utf-8")  # inherited finding
    (r / "docs" / "sessions" / "old.md").write_text("old notes\n", encoding="utf-8")  # inherited blocked path
    _commit(r, "base")
    return r


def _commit(r: Path, msg: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=r, check=True)
    return _head(r)


def _head(r: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=r, check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(r: Path, *args: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pii.main(["--repo", str(r), "--json", *args])
    return rc, json.loads(buf.getvalue())


def test_range_flags_only_new_lines(repo: Path):
    base = _head(repo)
    (repo / "app.py").write_text(f"OLD_HOST = '{IP_10}'\nx = 1\nOWNER = '{PERSONAL_EMAIL}'\n", encoding="utf-8")
    _commit(repo, "add")
    rc, out = _run(repo, "--range", f"{base}..HEAD")
    assert rc == 1
    assert [(f["path"], f["line"], f["category"]) for f in out["findings"]] == [("app.py", 3, "email")]
    assert PERSONAL_EMAIL[:3] not in json.dumps(out)


def test_range_clean_change_passes(repo: Path):
    base = _head(repo)
    (repo / "README.md").write_text("plain text\n", encoding="utf-8")
    (repo / "docs" / "sessions" / "old.md").write_text("old notes, edited\n", encoding="utf-8")  # modify, not add
    _commit(repo, "clean")
    rc, out = _run(repo, "--range", f"{base}...HEAD")
    assert (rc, out["findings"], out["allow_markers_added"]) == (0, [], 0)


def test_range_counts_added_allow_markers_and_still_fails(repo: Path):
    base = _head(repo)
    (repo / "probe.py").write_text(
        f"HOST = '{IP_192}'  # {MARKER}\nclean = 1  # gitleaks" + ":allow\nplain = 2\n", encoding="utf-8"
    )
    _commit(repo, "markers")
    rc, out = _run(repo, "--range", f"{base}..HEAD")
    assert rc == 1 and out["allow_markers_added"] == 2
    assert [(f["path"], f["line"], f["category"]) for f in out["findings"]] == [("probe.py", 1, "private_ip")]


def test_range_blocks_added_and_renamed_never_commit_files(repo: Path):
    base = _head(repo)
    (repo / "config" / ".env.local").write_text("A=1\n", encoding="utf-8")
    (repo / "README.md").write_text("long enough content to be detected as the same file on rename\n" * 3)
    mid = _commit(repo, "env")
    subprocess.run(["git", "mv", "README.md", "docs/sessions/README.md"], cwd=repo, check=True)
    _commit(repo, "move")
    rc, out = _run(repo, "--range", f"{base}..{mid}")
    assert rc == 1 and [(f["path"], f["category"]) for f in out["findings"]] == [("config/.env.local", "blocked_path")]
    rc, out = _run(repo, "--range", f"{mid}..HEAD")
    assert rc == 1 and [(f["path"], f["category"]) for f in out["findings"]] == [
        ("docs/sessions/README.md", "blocked_path")
    ]


def test_range_skips_policy_snapshot_content_but_not_blocked_files(repo: Path):
    base = _head(repo)
    snap = repo / "tests" / "fixtures" / "agents_pre_26_0_0"
    snap.mkdir(parents=True)
    (snap / "AGENTS.md").write_text(f"Served from {HOME_PATH} on {IP_TS}\n", encoding="utf-8")
    _commit(repo, "snapshot")
    rc, out = _run(repo, "--range", f"{base}..HEAD")
    assert (rc, out["findings"]) == (0, [])

    mid = _head(repo)
    (snap / ".env").write_text("A=1\n", encoding="utf-8")
    (repo / "tests" / "fixtures" / "AGENTS_copy.md").write_text(f"{HOME_PATH}\n", encoding="utf-8")
    _commit(repo, "outside the exclusion")
    rc, out = _run(repo, "--range", f"{mid}..HEAD")
    assert rc == 1
    assert sorted((f["path"], f["category"]) for f in out["findings"]) == [
        ("tests/fixtures/AGENTS_copy.md", "home_path"),
        ("tests/fixtures/agents_pre_26_0_0/.env", "blocked_path"),
    ]


def test_tree_skips_policy_snapshot_content(repo: Path):
    snap = repo / "tests" / "fixtures" / "agents_pre_25_0_0"
    snap.mkdir(parents=True)
    (snap / "AGENTS.md").write_text(f"{HOME_PATH}\n{IP_TS}\n", encoding="utf-8")
    _commit(repo, "snapshot")
    found = pii.scan_tree(repo, [])
    assert not [f for f in found if f.path.startswith("tests/fixtures/agents_pre_")]


def test_range_scans_inside_added_gz(repo: Path):
    base = _head(repo)
    (repo / "evidence.json.gz").write_bytes(gzip.compress(f'{{"host": "{IP_192}"}}\n'.encode()))
    _commit(repo, "gz")
    rc, out = _run(repo, "--range", f"{base}..HEAD")
    assert rc == 1 and [(f["path"], f["category"]) for f in out["findings"]] == [("evidence.json.gz", "private_ip")]


def test_range_git_error_fails_closed(repo: Path):
    rc = pii.main(["--repo", str(repo), "--range", "no-such-ref..HEAD"])
    assert rc == 2


def test_tree_ratchet_shrink_ok_grow_fails(repo: Path, capsys: pytest.CaptureFixture[str]):
    baseline = repo / pii.BASELINE_REL
    assert pii.main(["--repo", str(repo), "--tree"]) == 2  # no baseline: fail closed
    assert pii.main(["--repo", str(repo), "--tree", "--write-baseline"]) == 0
    doc = json.loads(baseline.read_text(encoding="utf-8"))
    assert doc["schema"] == pii.SCHEMA
    assert doc["counts"]["private_ip"] == 1 and doc["counts"]["blocked_path"] == 1
    _commit(repo, "baseline")

    rc, out = _run(repo, "--tree")
    assert rc == 0 and out["grew"] == {}

    (repo / "app.py").write_text(f"OLD_HOST = '{IP_10}'\nNEW = '{IP_172}'\n", encoding="utf-8")
    rc, out = _run(repo, "--tree")
    assert rc == 1 and out["grew"] == {"private_ip": [1, 2]}
    capsys.readouterr()
    assert pii.main(["--repo", str(repo), "--tree", "--write-baseline"]) == 1  # refuses to raise
    assert "REFUSED" in capsys.readouterr().err
    assert json.loads(baseline.read_text(encoding="utf-8"))["counts"]["private_ip"] == 1

    (repo / "app.py").write_text("OLD_HOST = 'from-config'\n", encoding="utf-8")
    rc, out = _run(repo, "--tree")
    assert rc == 0 and out["shrank"] == {"private_ip": [1, 0]}
    assert pii.main(["--repo", str(repo), "--tree", "--write-baseline"]) == 0
    assert json.loads(baseline.read_text(encoding="utf-8"))["counts"]["private_ip"] == 0


def test_baseline_guard_fails_on_any_raised_count(repo: Path):
    rc, out = _run(repo, "--baseline-guard", "HEAD")  # HEAD has no baseline yet: first introduction
    assert rc == 0 and "first introduction" in out["note"]
    assert pii.main(["--repo", str(repo), "--tree", "--write-baseline"]) == 0
    _commit(repo, "baseline")
    path = repo / pii.BASELINE_REL
    doc = json.loads(path.read_text(encoding="utf-8"))

    rc, out = _run(repo, "--baseline-guard", "HEAD")
    assert (rc, out["raised"]) == (0, {})

    doc["counts"]["email"] += 1  # a hand edit that raises a count
    path.write_text(json.dumps(doc), encoding="utf-8")
    rc, out = _run(repo, "--baseline-guard", "HEAD")
    assert rc == 1 and out["raised"] == {"email": [0, 1]}

    doc["counts"]["email"] = 0
    doc["counts"]["private_ip"] = 0  # lowering is always fine
    path.write_text(json.dumps(doc), encoding="utf-8")
    rc, out = _run(repo, "--baseline-guard", "HEAD")
    assert (rc, out["raised"]) == (0, {})

    assert pii.main(["--repo", str(repo), "--baseline-guard", "no-such-ref"]) == 2
    path.write_text("not json", encoding="utf-8")
    assert pii.main(["--repo", str(repo), "--baseline-guard", "HEAD"]) == 2


def test_tree_output_is_value_free(repo: Path, capsys: pytest.CaptureFixture[str]):
    (repo / "notes.txt").write_text(f"{PERSONAL_EMAIL}\n{HOME_PATH}\n", encoding="utf-8")
    _commit(repo, "notes")
    pii.main(["--repo", str(repo), "--tree", "--write-baseline"])
    capsys.readouterr()
    assert pii.main(["--repo", str(repo), "--tree", "--verbose"]) == 0
    out = capsys.readouterr().out
    assert "notes.txt:1  email" in out and "notes.txt:2  home_path" in out
    for value in (PERSONAL_EMAIL, HOME_PATH, IP_10):
        assert value[:3] not in out.replace("notes.txt", ""), value


# ── committed configuration ──────────────────────────────────────────────────────────────────────────


def test_repo_baseline_is_counts_only_and_complete():
    doc = json.loads((ROOT / pii.BASELINE_REL).read_text(encoding="utf-8"))
    assert doc["schema"] == pii.SCHEMA
    assert set(doc["counts"]) == set(pii.RATCHETED)
    assert all(isinstance(v, int) and v >= 0 for v in doc["counts"].values())
    assert set(doc) == {"schema", "_note", "counts"}


def test_scanner_and_rules_do_not_flag_themselves():
    for rel in (
        "scripts/check_no_pii.py",
        ".gitleaks.toml",
        ".gitleaksignore",
        ".github/workflows/secret-scan.yml",
        "config/pii_baseline.json",
        "tests/test_check_no_pii_20261027.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert pii.scan_text(rel, text, []) == [], rel
        assert pii.blocked_reason(rel) is None, rel
        assert pii.count_markers(text, set(range(1, text.count("\n") + 2))) == 0, rel


def test_gitleaks_config_extends_defaults_and_covers_required_shapes():
    doc = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert doc["extend"]["useDefault"] is True
    rules = {r["id"]: r for r in doc["rules"]}
    assert "allowlist" not in doc  # no global allowlist: every exemption is rule- or fingerprint-scoped
    for r in doc["rules"]:
        for k in ("path", "paths"):
            assert k not in r and k not in (r.get("allowlist") or {}), r["id"]
    samples = {
        "tradeai-github-token": "ghs_" + "A1b2C3d4" * 4 + "Zz9Y",
        "tradeai-github-fine-grained-pat": "github_pat_" + "Ab3_" * 20 + "Cd",
        "tradeai-telegram-bot-token": "1234567" + "89:" + "AAx_y-" * 5 + "Zz9Yq",
        "tradeai-google-api-key": "AI" + "za" + "Sy" + "Q1w2E3r4" * 4 + "T",
        "tradeai-google-oauth-client-secret": "GOC" + "SPX-" + "a1B2c3D4" * 3 + "e5F6",
        "tradeai-google-oauth-access-token": "ya" + "29." + "a0Bc1De2Fg3Hi4" * 3,
        "tradeai-jwt": "ey" + "JhbGciOiJIUzI1NiJ9.ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ",
        "tradeai-database-url-with-password": "postgresql://svc:" + "Qz7" + "pW2xL@db.internal:5432/app",
    }
    for rid, sample in samples.items():
        assert re.search(rules[rid]["regex"], sample), rid
    dsn = rules["tradeai-database-url-with-password"]
    allow = [re.compile(x) for x in dsn["allowlist"]["regexes"]]
    for placeholder in ("${DB_PASSWORD}", "{password}", "<password>", "password", "FakePw"):
        assert any(a.search(placeholder) for a in allow), placeholder
    assert not any(a.search("Qz7" + "pW2xL") for a in allow)
    generic = [re.compile(x) for x in rules["generic-api-key"]["allowlist"]["regexes"]]
    allowed = [
        'subject_key": "watch:abc:2026-10-01"',
        "storageKey: 'tradeai.watch.columns'",
        'dedupe_key": "' + "3f2a9c8b-1d2e-4f5a-9b8c-" + '7d6e5f4a3b2c"',
        '"src/x/tokens.ts": "' + "ab" * 32 + '"',
    ]
    for s in allowed:
        assert any(g.search(s) for g in generic), s
    still_fire = [
        'api_key": "Zq8rT2mW' + '9xLp4KvN7bYc3HdJ6fGs1AeU"',
        'storage_key": "Zq8rT2mW' + '9xLp4KvN7bYc"',  # exempt name, random value
        'approval_key = "ab12-' + 'cd34-ef56"',
        'order_event_key": "n8n_' + 'abc123x"',
    ]
    for s in still_fire:
        assert not any(g.search(s) for g in generic), s


def test_gitleaksignore_is_commit_scoped_fingerprints_only():
    entries = [
        ln.strip()
        for ln in (ROOT / ".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert entries, "the reviewed inherited findings must be listed"
    fp = re.compile(r"^[0-9a-f]{40}:[^:*?\s]+:[a-z0-9-]+:\d+$")
    bad = [e for e in entries if not fp.match(e)]
    assert bad == [], bad[:5]
    assert len(entries) == len(set(entries))


def _wf() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/secret-scan.yml").read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _wf()["jobs"]["secret-scan"]["steps"]


def _step(name_part: str) -> tuple[int, dict]:
    for i, s in enumerate(_steps()):
        if name_part in s.get("name", ""):
            return i, s
    raise AssertionError(name_part)


def test_workflow_triggers_permissions_and_draft_guard():
    doc = _wf()
    on = doc.get(True, doc.get("on"))
    assert {"opened", "synchronize", "reopened", "ready_for_review"} <= set(on["pull_request"]["types"])
    assert on["push"]["branches"] == ["main"]
    assert on["schedule"] and "workflow_dispatch" in on
    assert doc["permissions"] == {"contents": "read"}
    conc = doc["concurrency"]
    assert "github.ref" in conc["group"] and conc["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    job = doc["jobs"]["secret-scan"]
    assert job["if"] == "github.event_name != 'pull_request' || github.event.pull_request.draft == false"
    assert job["runs-on"] == "ubuntu-latest" and "strategy" not in job
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["fetch-depth"] == 0


def test_workflow_pins_and_verifies_gitleaks_and_never_prints_values():
    doc = _wf()
    text = (ROOT / ".github/workflows/secret-scan.yml").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+\.\d+", doc["env"]["GITLEAKS_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", doc["env"]["GITLEAKS_SHA256"])
    assert "sha256sum -c -" in text and "TODO" not in text
    assert "--redact" in text
    assert "origin/${BASE_REF}..HEAD" in text and "--range origin/${BASE_REF}...HEAD" in text
    assert "--full-history HEAD" in text and "PII_ARGS=--tree" in text
    assert "Author" not in text and "'Email'" not in text  # never echo git identities from the report
    assert re.findall(r"secrets\.([A-Z_]+)", text) == ["TRADEAI_PII_DENY_PATTERNS"]
    assert "${{ github.base_ref }}" not in "\n".join(s.get("run", "") for s in _steps())  # base_ref via env only


def test_workflow_pr_uses_mains_rules_over_the_checkout_and_ignores_allow_comments():
    """gitleaks 8.21.2 always loads ./.gitleaksignore from the scanned tree and accepts fingerprints without a
    commit, so on a pull request main's copies must REPLACE the checkout's files before gitleaks runs."""
    i_rules, rules = _step("Scope and trusted rules")
    i_leaks, leaks = _step("gitleaks (credentials)")
    assert i_rules < i_leaks
    run = rules["run"]
    pr_branch = run.split("pull_request)", 1)[1].split(";;", 1)[0]
    assert 'git show "${base}:.gitleaksignore" > .gitleaksignore' in pr_branch
    assert ": > .gitleaksignore" in pr_branch  # main has none: empty, never the PR's own list
    assert 'git show "${base}:.gitleaks.toml" > .gitleaks.toml' in pr_branch
    assert 'git show "${base}:scripts/check_no_pii.py" > "$RUNNER_TEMP/rules/check_no_pii.py"' in pr_branch
    cmd = leaks["run"]
    assert "--ignore-gitleaks-allow" in cmd
    assert "--config .gitleaks.toml" in cmd and "--gitleaks-ignore-path .gitleaksignore" in cmd
    assert all("gitleaks" not in s.get("run", "") for s in _steps()[:i_rules] if "Install" not in s.get("name", ""))


def test_workflow_guards_the_baseline_on_pull_requests():
    i_pii, pii_step = _step("check_no_pii (personal")
    i_guard, guard = _step("baseline may only shrink")
    assert '"$RUNNER_TEMP/rules/check_no_pii.py"' in pii_step["run"]
    assert guard["if"].startswith("github.event_name == 'pull_request'")
    assert '--baseline-guard "origin/${BASE_REF}"' in guard["run"]
    assert guard["env"]["BASE_REF"] == "${{ github.base_ref }}"
    assert '"$RUNNER_TEMP/rules/check_no_pii.py"' in guard["run"]  # main's copy, not the PR's
