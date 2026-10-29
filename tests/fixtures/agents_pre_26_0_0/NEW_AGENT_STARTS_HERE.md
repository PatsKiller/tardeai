# New agent starts here (one page)

Status:      PROPOSED (v1.0.0, ships with the AGENTS.md amendment that links it)
Owner:       platform
as_of:       2026-09-25T09:30:00-04:00
Measured at: base 1c60ecb42

Tick each box before your first mutating command. If you can't, stop and ask the coordinator.

**Read**
- [ ] `AGENTS.md` §0 (ten rules) and §1 (authority). `AI_WORK_POLICY.md` (push budget, deploy boundary).
- [ ] [`docs/architecture/ARCHITECTURE_INDEX.md`](../architecture/ARCHITECTURE_INDEX.md): find the **one** registry that owns the thing you're changing.
- [ ] [`docs/governance/ENGINEERING_STANDARD.md`](ENGINEERING_STANDARD.md): which checks cover your files, and which rules are UNENFORCED.

**Claim**
- [ ] `scripts/new-worktree.sh <name>`. Never mutate the primary tree. Never `git stash`. Symlink the dev-tree `.venv` yourself (the script doesn't); there are no `node_modules` in worktrees.
- [ ] `scripts/agent_session_start.py --agent <id from config/agent_clients.yaml> --mode mutating --claim … --store … --doc-read AGENTS.md --doc-read AI_WORK_POLICY.md --expected-worktree $PWD --expected-head $(git rev-parse HEAD)` returns `ok: true`.
- [ ] Record the **base SHA** (`git rev-parse HEAD`) and **served SHA** (`readlink -f ~/trade-ai-releases/portfolio-server/CURRENT`).

**Locate**
- [ ] The authoritative contract (a `Name@vN` schema, registry row, or API payload) and its producer file:line.
- [ ] The owner: DSA writer (data) > lane owner (scheduling) > catalog agent (agent authority). If they disagree, or the store is in no registry, record it as drift and ask. Also the grant the change needs (`bin/guard scopes`; `bin/guard show` right before acting). Guard grants are **advisory** outside Cursor.
- [ ] Any displayed value you touch: trace GUI → API → producer → store, and note each `as_of`.

**Build**
- [ ] Smallest coherent change. No hardcoded values, chat IDs or secrets.
- [ ] Tests: behaviour, refusal, failure; register them in a CI route; run a CI-parity pass with missing deps shadowed.
- [ ] Run Ruff on your changed `.py` yourself (nothing else will). `bash scripts/ai_local_acceptance.sh`, then grep for `FAILED|STOP|GATES FAILED`. Regenerate **last** (it runs `git add -A`, so check the staged diff). Then `python3 scripts/check_no_secrets.py --tree`.

**Ship**
- [ ] Commit locally. Push only with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` + explicit operator intent (`AI_WORK_POLICY.md`). Note: the pre-push hook also accepts **any** active git-push grant, whatever its reason, so check the reason names your branch; the hook won't.
- [ ] The PR states base/head SHA, files and stores, authority class, contracts, migrations, negative tests, proof and rollback.
- [ ] Never merge your own PR, and never call it independently reviewed. Nothing enforces this (0 required reviews); it's on you. Update a behind branch with a merge commit, never a force-push.
- [ ] After deploy: check CURRENT, the unit `cwd`, and one natural cycle. Report live vs merged vs local.

**Never**, without a specific operator instruction: size, order or touch a broker; read or rotate a
secret; change branch protection; enable a live flag; send to an operator surface without a dry run.
