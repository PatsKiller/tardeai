# New agent starts here (one page)

Status:      ACTIVE (v2.0.0, with AGENTS.md 26.0.0)
Owner:       platform
as_of:       2026-10-27T23:30:00-04:00
Measured at: base 274e531f5

Tick each box before your first mutating command. If you can't, stop and ask the coordinator.

**Read**
- [ ] `AGENTS.md` §0 (eleven rules), §1 (identity and session protocol) and §17 (the one operator-only list).
  `AI_WORK_POLICY.md` for the push budget and the deploy boundary.
- [ ] [`docs/governance/OPEN_ITEMS.md`](OPEN_ITEMS.md): the known gaps in the area you are touching, with their owners.
- [ ] [`docs/architecture/ARCHITECTURE_INDEX.md`](../architecture/ARCHITECTURE_INDEX.md): find the **one** registry that owns the thing you're changing.
- [ ] [`docs/governance/ENGINEERING_STANDARD.md`](ENGINEERING_STANDARD.md): which checks cover your files, and which rules are UNENFORCED.

**Claim**
- [ ] `python3 scripts/agent_claim.py status`, then `claim --paths …` and at least one `plan "<step>"`. The pre-commit
  claim gate blocks a commit whose files you have not claimed (AGENTS.md §0 rule 11, §28.3).
- [ ] `scripts/new-worktree.sh <name>` off fresh `origin/main`. Never edit, stage or commit in the canonical checkout
  the host runs from. Never bare `git stash`.
- [ ] `scripts/agent_session_start.py --agent <id from config/agent_clients.yaml> --mode mutating --claim … --store … --doc-read AGENTS.md --doc-read AI_WORK_POLICY.md --expected-worktree $PWD --expected-head $(git rev-parse HEAD)` returns `ok: true`.
- [ ] Record the **base SHA** (`git rev-parse HEAD`) and the **served SHA** (`readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`).

**Locate**
- [ ] The authoritative contract (a `Name@vN` schema, registry row, or API payload) and its producer `file::function`.
- [ ] The owner: DSA writer (data) > lane owner (scheduling) > catalog agent (agent authority). If they disagree, or
  the store is in no registry, record it as drift and ask.
- [ ] The grant the change needs (`bin/guard scopes`; `bin/guard show` right before acting). Grants come only from
  the operator at the keyboard or on Ops → Controls — never Telegram. Guard grants are mechanical only in Cursor.
- [ ] Any displayed value you touch: trace GUI → API → producer → store, and note each `as_of`.

**Build**
- [ ] Smallest coherent change. No hardcoded values, chat IDs, secrets, account identifiers or real portfolio data —
  the repository is public (AGENTS.md §2A).
- [ ] Tests: behaviour, refusal, failure; register new test files in a `config/ci_gates/*.json` gate
  (`scripts/check_test_coverage.py --fail-on-new`); run a CI-parity pass with missing deps shadowed.
- [ ] Ruff with the pinned `ruff==0.16.2` on your changed `.py` (`scripts/agent_changed_file_quality.py`).
  `bash scripts/ai_local_acceptance.sh`, then grep for `FAILED|STOP|GATES FAILED`. Then
  `python3 scripts/check_no_secrets.py --tree`.

**Ship**
- [ ] Commit locally. Push only with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` + explicit operator intent, within the
  per-branch budget the hook prints (`AI_WORK_POLICY.md` §3). Never push `main`.
- [ ] The PR title is a plain-English sentence, and the description opens with `## In plain English`: what changes,
  why, who or what it affects, when it takes effect, approval type, risk and fallback (AGENTS.md §28.12; the template
  pre-fills it, `scripts/check_pr_plain_english.py` checks it). Then the technical detail: base/head SHA, files and
  stores, contracts, migrations, negative tests, proof and rollback, and the operator instruction it delivers, quoted.
- [ ] Never merge, never promote, never review your own PR. Mergify merges after the operator approves; a held-class
  PR is merged by the operator (AGENTS.md §25.10). Update a behind branch with a merge commit, never a force-push.
- [ ] After the poller promotes: check `CURRENT`, the unit `cwd`, and one forced or natural cycle (AGENTS.md §8.1).
  Report live vs merged vs local, and close or update your incident records (§28.16).

**Never**, without a specific operator instruction: size, order or touch a broker; read or rotate a
secret; change branch protection; enable a live flag; send to an operator surface without a dry run.
