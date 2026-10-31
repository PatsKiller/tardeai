# AGENTS.md — version history, banners and ratifying edits

Status:      ACTIVE (history; nothing here binds)
Owner:       coordinator
as_of:       2026-10-27T23:30:00-04:00
Measured at: origin/main 274e531f5 (AGENTS.md 25.0.1)

This file holds the record that AGENTS.md no longer carries in its body: every version-history row in full, every
version banner, and every ratifying edit. **Nothing here is a rule.** The binding text is the current AGENTS.md; why a
rule exists is in `LESSONS_LEARNED.md`; what is still open is in `OPEN_ITEMS.md`.

The complete AGENTS.md 25.0.1 text is preserved byte-exact at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`
(sha256 pinned in `tests/support/agents_policy_frozen.py`), and every earlier version is in git history.

## How 26.0.0 was built

On 2026-10-27 the operator asked for the file to be made coherent ("I want all of your recommendations done … I need
to make sure that all of the other documents are also in line"). The 25.0.1 file (7,401 lines) was reviewed line by
line in six slices and every passage was classified as a current rule, a problem (broken, open-ended or contradicted by
the code), history, reference material or a duplicate. 26.0.0 keeps every current rule once and moves the rest. The
section "Where the 25.0.1 text went" at the end maps each passage of the slices drafted with a line-level survival
map (§7, §7A–§9, §12–§13, §17A–§18, §23, §24–§29). The coordinator's sections (§0–§6, §10–§11, §14–§17, §19–§22 and
the version policy) carry no line-level table: compare them with the frozen copy at
`tests/fixtures/agents_pre_26_0_0/AGENTS.md`. Two independent reviews checked the rewrite before it was proposed: one
for any weakened rail (§0, §2, §2A, §2B, §17, §22, the broker, order, stop, sizing, secret, deletion, merge and push
rules) and one for lost rules, dangling references and personal data; their findings were fixed in the PR.

## Version history as it stood at 25.0.1 (verbatim)

| Version | Date | Status | Change class | Summary | Approval |
|---|---|---|---|---|---|
| 25.0.1 | 2026-10-27 | ACTIVE | PATCH | Generated §7A table refreshed by `scripts/render_source_of_truth.py`: the `operator_decisions` domain moves from proposed to granted (operator 2026-10-27, coordinator session, verbatim: "D1–D7 as recommended", D5 = turn on the decision store). No change to required behaviour. | PATCH — operator merge of this held-class PR (§20, §25.10). Effective 2026-10-27. |
| 25.0.0 | 2026-10-27 | ACTIVE | MAJOR | Consolidation (operator 2026-10-27: "Get everything in line as the senior developer and coordinator."): owner clause (§20); every MAJOR plus §0/§2/§17/role-authority needs the token and every AGENTS.md change is a held-class operator merge (§20, version policy); one-tap digest "Approve all" bound to head SHAs, held classes from `config/merge_hold_paths.json` never in it, Mergify in ET windows with the market-hours freeze, ratifying or superseding #2208's unratified §25.10 text (§25.10); `deploy_on_main` promotes under the armed standing deploy delegation with no per-SHA grant, SOFT refused outside tests, stuck deploys page P1, emergency promote operator-only or a coordinator on the operator's own in-session instruction (§25.10, §24.8); canonical checkout and hooks (§0 rule 3); pushes of own non-`main` branches under an approved plan (§0 rule 4, §28.15 item 8); no self-review (§23.19, §28.15 items 2, 3, 10); incidents, no silent drop (§28.16); paid and LLM run discipline (§29); release train removed (operator 2026-10-27; §25.1–§25.9, §17, §24.5, §24.8, §27, §28 references); version banners and ratifying edits moved to this appendix; 5.2.0 §8.1 binding, 4.2.0 withdrawn; CI fails an AGENTS.md diff without a version bump. §0 rules 1, 2, 5–11, §2, §2A, §7A, §22 and §23.14 unchanged; `MBI_BEHAVIOR = 0`. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_25_0_0 2236 78a919464a2213ea221ae12b43476bb8072d9a28` (operator, verbatim, in the coordinator Claude Code session 2026-10-27, §28.4; recorded on PR #2236 comment 6445698813); ratified by this edit, which set the header, banner and row to ACTIVE and changed nothing else. Effective 2026-10-27. |
| 24.0.0 | 2026-10-26 | ACTIVE | MAJOR | §25.10 Mergify + host deploy: Mergify merges green PRs on ET schedules; host `deploy_on_main` poller promotes exact `main` SHAs under STOP + GlobalReleaseLock + standing deploy (promote-only) delegation; emergency is operator `emergency_manual_promote.sh` + `release-write` naming SHA + `TRADEAI_EMERGENCY_RELEASE_SHA`. Agents stay PR-only. Retires train live merge/`train/*`, Ops Run now, train UI; replaces `AI_WORK_POLICY.md` §28 train-push exception. Numbered 24.0.0 after ACTIVE 22.0.0; 23.x reserved. §0/§2/§2A/§7A/§22/§23.14 byte-identical. | **ACTIVE** — operator 2026-10-26 in session (approved 24.0.0 PROPOSED, directed install/configure/commit); bind `APPROVE_AGENTS_POLICY_24_0_0 <pr> <head_sha>` on the cutover PR (§20). Effective 2026-10-26. |
| 22.0.0 | 2026-10-25 | RETIRED 2026-10-27 | MAJOR | Release train Run now. Release train retired 2026-10-27 by operator; replaced by §25.10. | Ratified `APPROVE_AGENTS_POLICY_22_0_0 2149 a91e0806cbd92fbbd6f09f971ed13fbb35338fa1`; retired by 25.0.0. |
| 21.0.0 | 2026-10-25 | ACTIVE | MAJOR | Three sections, one token. §28.13 "Design lifecycle" (operator 2026-10-25, "I approve the design workflow"): `design/` the single home, every page versioned (v000 as built 2026-10-26, v001 the 10-24 approvals back-filled), DRAFT → PROPOSED → APPROVED (operator only, one tap in Approvals → Designs, signed ledger decision; prose never counts) → IMPLEMENTING (`Design: <page>/vNNN` or `Design: none`) → VERIFIED → CURRENT, approved versions immutable, removal guard, phone ≤820 (412/390) and desktop ≥1280 (1440) rules, logged-in live drift via a read-only reader, no real data in the public repo. §28.14 "Self-heal monitor and fixer" (operator 2026-10-25, "Arm the fixer and also a logger"): host-timer monitor independent of n8n; four deterministic remediations once per incident; every other fix an ordinary self-heal fixer PR through CI and the train, never merging or deploying; refused scopes alert + coordinator task; append-only fix log on Releases & schedules → Fixes; P1 after max attempts; armed by ACTIVE status, shadow before. §28.15 "Hands-off delivery" (operator 2026-10-25, "Do 20.4"; numbered MAJOR by the version policy because it widens §17 and the §25.2 delegation): push budget 5 with a coordinator-only override on operator-approved scope; solo trains for every `needs_operator` class with one adversarial review and real-layout proof; train-self and guard/CI solo trains with two reviews, a ≥3 h veto window and a next-window dry run, no weakening of §0/§2/§17 enforcement; live lanes derived from the lane registry (host list an override); no TTY ACK for routine setup; `.env` configuration keys changeable, secrets unchanged; the `solo` delegation class accepted once at ratification; routine feature-branch pushes under an approved plan need no guard `git-push` grant (fast-forward only, never `main`/release, never force) and running toolchains (`npm run`, Playwright, pytest, builds) is never `deps`; the complete operator list (ratification, broker/MBI, credentials/secrets, design approvals, alerts/escalations). Broker/Active Trader/MBI always held; secrets never. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_21_0_0 2128 f8a89dc6b568406a3e7662e04fae9ef31fe559c3` (operator, PR #2128 comment by PatsKiller 2026-10-25T20:33:01Z, https://github.com/PatsKiller/tardeai/pull/2128#issuecomment-6402870834, verbatim: "APPROVE_AGENTS_POLICY_21_0_0 2128 f8a89dc6b568406a3e7662e04fae9ef31fe559c3"); ratified by this edit on #2128's branch, which set the header block, banner, row and §28.13–§28.15 to 21.0.0 ACTIVE and marked the `AI_WORK_POLICY.md` paragraphs binding, and changed nothing else; approval phrase as proposed `APPROVE_AGENTS_POLICY_21_0_0 <pr_number> <head_sha>`; the `solo` delegation digest acceptance (§28.15 item 7) remains the operator's host act. Effective 2026-10-25. |
| 20.3.0 | 2026-10-25 | ACTIVE | MINOR | §28.12 "Delivery lifecycle — claim to verified release" added: one ordered path (claim, design, build, test, PR, CI green, queue, release) pointing at the rules that already bind, plus two obligations: post-release verification after every release (`scripts/post_release_tester.py`: API checks at once, light 412/390 sweep outside the §28.8 window under the memory gate, nightly full sweep) and immediate P1 failure paging by Telegram, email and SMS (`scripts/delivery_failure_alerts.py`). Adds obligations only; does not touch §0, §2, §17 or role authority. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_20_3_0 2107 72bd48f46d3557501b3575002e741577ffff90f0` (operator, PR #2107 comment by PatsKiller 2026-10-25T17:17:38Z, https://github.com/PatsKiller/tardeai/pull/2107#issuecomment-6400701124, verbatim: "APPROVE_AGENTS_POLICY_20_3_0 2107 72bd48f46d3557501b3575002e741577ffff90f0"); ratified by this edit on #2107's branch, which set the header block, banner, row and §28.12 to 20.3.0 ACTIVE and changed nothing else; approval phrase as proposed `APPROVE_AGENTS_POLICY_20_3_0 <pr_number> <head_sha>`. Effective 2026-10-25. |
| 20.2.0 | 2026-10-24 | ACTIVE | MINOR | §28.9 + §28.10 + §28.11 (transition for work in action) added: conflicts resolved only by the conflict engine under the operator-approved rulebook (agreement/superseded never flag, gates not conflicts, owner decides with a reason, CIO always informed, safety never automatic); no silent removal from operator surfaces (approved mockup required); `[shared-infra]` PRs alone with real-layout proof; one source per fact owned by the CIO record; health = the job ran (exit code + output, real cause shown, independent alert path); a read never acts (no broker read/job from GET, 500 KB poll budget, one-at-a-time probes); every writer a monitored n8n lane. Adds restrictions only; does not touch §0, §2, §17 or role authority. | **RATIFIED** by the operator 2026-10-24 (`APPROVE_AGENTS_POLICY_20_2_0 2073 c17951846b3bd688a6ef1c082d208ae4970445fc`). |
| 20.1.0 | 2026-10-23 | ACTIVE | MINOR | §28.8 "No agent UI or validation traffic to the live server during market hours" added. Operator decision 2026-10-23 ~11:05 ET, "approved", after five portfolio-server SIGKILLs (09:14–10:24 ET) driven by agent crawls and previews (PR #2012): from 04:00 to 16:15 ET on a market day no agent sends Playwright, crawler, `vite preview` or dev-proxy traffic to the served `/api` on `127.0.0.1:7777`; fixtures or a mock or replay backend instead; live smoke after the close at ≤1 req/s, GET only. MINOR: one added restriction, none removed. Every other section is byte-identical to 20.0.0 before and after ratification. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_20_1_0 2019 d24a29054865a9bc09d3c50bb33dfe9c4be728af` (operator, PR #2019 comment by PatsKiller 2026-10-23T16:53:47Z, https://github.com/PatsKiller/tardeai/pull/2019#issuecomment-6370144385, verbatim: "APPROVE_AGENTS_POLICY_20_1_0 2019 d24a29054865a9bc09d3c50bb33dfe9c4be728af"); ratified by this edit on #2019's branch, which set the header block and §28.8 to 20.1.0 ACTIVE and changed nothing else; approval phrase as proposed `APPROVE_AGENTS_POLICY_20_1_0 <pr_number> <head_sha>`. Effective 2026-10-23. |
| 20.0.0 | 2026-10-22 | ACTIVE | MAJOR | §28 "Agent operations and the read-only broker baseline" added. Operator decisions 2026-10-22 (verbatim in the banner; approved as "19.1.0", numbered 20.0.0 by the version policy): measured caps and receipts for the four automations that end or rewrite a run (§28.1, absorbing the withdrawn 18.1.0), agent temp discipline (§28.2), multi-vendor coordination and the claim board `scripts/agent_claim.py` (§28.3), approval provenance (§28.4), the Ops → Controls sudo window (§28.5), the read-only Schwab baseline with the `live_submit` kill switch as an extra barrier (§28.6). While PROPOSED §0, §2, §7, §13, §17, §24, §25, §27 and the four adapters are byte-identical; the ratifying edit makes exactly the nine clause edits quoted in §28.7: §0 rule 11 "Claim, log, hand off" (and the four adapters), a second §0 rule 6 exception and the host `/tmp` hygiene lanes in §24.12, the claimer in §25.8, the §7 time-cap trap, the behaviour rail cited by symbol, the sudo window in §27.3, the corrected §27.4 and the read-only baseline in §17. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497d5d63a49f08aad247f194f884a8030b1` (operator, PR #2013 comment by PatsKiller 2026-10-23T14:42:00Z, https://github.com/PatsKiller/tardeai/pull/2013#issuecomment-6367515961, verbatim: "APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497d5d63a49f08aad247f194f884a8030b1"); ratified by this edit on #2013's branch, which set the header block to 20.0.0 ACTIVE and made the nine clause edits quoted in §28.7; approval phrase as proposed `APPROVE_AGENTS_POLICY_20_0_0 <pr_number> <head_sha>`; per-PR word, because it is MAJOR. Effective 2026-10-23. |
| 19.0.0 | 2026-10-22 | ACTIVE | MAJOR | §27 "n8n broker reads and the operator controls surface" added. Operator decisions 2026-10-22 (verbatim in the banner): n8n may read the broker because only reading is done (§27.1: a closed set of audited read lanes, host execution, every trading lock LOCKED, Schwab `read_only`, no credential in n8n; the never-list unchanged); Ops → Controls (§27.2–§27.3: settings in a Postgres `operator_settings` table with history, one governed host applier, safe direction one click, risky direction a WebAuthn passkey plus a typed phrase, TOTP recovery only, Telegram notification only), superseding decision D3 and the kill switch's terminal-only clear. Code: `scripts/lib/n8n_broker_read_carveout.py` (`CARVEOUT_STATUS` PROPOSED), consulted by `pipeline_manifest.forbidden_command_tokens()`; registry row `operator_settings` proposed. While PROPOSED §17, §23.14 and §25 are byte-identical; the ratifying edit inserts one §23.14 bullet, replaces the §25.4 "Who may do what." bullet and one §17 sentence, appends one §17 paragraph (§27.5) and sets `CARVEOUT_STATUS` ACTIVE. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_19_0_0 1962 bb54a14a89347a1c17dd0d326b0720c882bbd61f` (operator, PR #1962 comment by PatsKiller 2026-10-22T22:10:31Z, https://github.com/PatsKiller/tardeai/pull/1962#issuecomment-6352416425, verbatim: "APPROVE_AGENTS_POLICY_19_0_0 1962 bb54a14a89347a1c17dd0d326b0720c882bbd61f"); ratified by this edit on #1962's branch, which set the header block to 19.0.0 ACTIVE, made the four clause edits quoted in §27.5 and set `CARVEOUT_STATUS` to `ACTIVE`; approval phrase as proposed `APPROVE_AGENTS_POLICY_19_0_0 <pr_number> <head_sha>`; per-PR word, because it is MAJOR. Effective 2026-10-22. |
| 18.0.0 | 2026-10-22 | ACTIVE | MAJOR | §26 "Data foundation — one store, one writer, the CIO as integrator" added. Operator direction 2026-10-22 (verbatim in the banner): one data store with everything, the CIO agent and n8n tie it together, hard-coded in AGENTS.md, a data dictionary that shows one source of data. The CIO prospect record (`InstrumentRecord@v1` extended, one row per `security_guid`, written only by `InstrumentRecordStore`) is the single per-security truth; every fact has one authoritative store and one writer in the §7A registry and the dictionary rendered from it binds row by row as each is granted; pages and alerts read only through registered projections; n8n schedules gathering inside the §23.14 never-list; conflicts are recorded and shown, never silently resolved; new stores and writers stay §17; copies retire by archive and tripwire. §0, §2, §2A, §7A, §17, §22, §23.14, §24, §25 and the adapters byte-identical; the NO SILOS section byte-identical while PROPOSED, one clause replaced at ratification (§26.7). MAJOR: agent role authority (the CIO becomes the only writer of per-security judgment); grants no row, broker, order, stop, egress or n8n authority. Header block 18.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 17.0.0. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_18_0_0 1931 894bbd954ca174453e7339d30157e082d4403c84` (operator, PR #1931 comment by PatsKiller 2026-10-22T16:59:09Z, https://github.com/PatsKiller/tardeai/pull/1931#issuecomment-6346416104, verbatim: "APPROVE_AGENTS_POLICY_18_0_0 1931 894bbd954ca174453e7339d30157e082d4403c84"); ratified by this edit on #1931's branch, which set the header block to 18.0.0 ACTIVE and replaced the NO SILOS methodology rule 1 quoted in §26.7; approval phrase as proposed `APPROVE_AGENTS_POLICY_18_0_0 <pr_number> <head_sha>`; per-PR word, because it is MAJOR. Effective 2026-10-22. |
| 17.0.0 | 2026-10-21 | RETIRED 2026-10-27 | MAJOR | Release train (§25.1–§25.9). Release train retired 2026-10-27 by operator; replaced by §25.10. | Ratified `APPROVE_AGENTS_POLICY_17_0_0 1914 aeb5e6fd70dcefac0df8541c496bebb4a5e904ec`; retired by 25.0.0. |
| 16.0.0 | 2026-10-21 | ACTIVE | MAJOR | §23.21 "The cutover standard — fixed, dry run, regression tests, one live run" added, rebuilt from 8.0.0 (PR #1727, closed unratified) on the operator's word 2026-10-21 "yes rebuild 1727". Operator ruling 2026-10-14 ~11:05 ET, verbatim: "new standards apply when i say so fix and dry and regression testing, yes it should run live successful to many road blocks to testing". An n8n lane is cutover-ready when (1) its defect is fixed and served, (2) its n8n dry run passes (a forced `dry_run` fire counts; no natural shadow slot), (3) its lane regression tests pass under `TRADE_AI_CI=1`, (4) it has at least one successful `live` n8n run with the cron line still present under the shared lock: the dispatcher's slot, or an operator-forced in-window live fire (`OPERATOR_FORCED_LIVE` in `scripts/n8n_cutover_checklist.py`; never a gate override; never an agent-forced F09 live run, §23.25). Procedure: `scripts/n8n_cutover_wave.py` canary rows, `comment-cron` retirement as `# RETIRED <date> n8n-cutover <lane>` (the commented line is the fallback), then the dispatcher-row PR. Multi-day soaks removed; operator waivers recorded verbatim. While PROPOSED, §8.1, §23.3, §23.12, §23.14 and §23.23 were byte-identical; the ratifying edit replaced five quoted clauses (the §23.3 and §23.14 `trade-ai-scalp-live` 3-day fallback, the §8.1 natural-evidence gate list, a §23.12 pointer, the §23.23 (4) citation) whose digests `tests/test_agents_policy_16_0_0_cutover_standard.py` pins. §0, §2, §2A, §7A, §17, §22 and the adapters byte-identical. MAJOR: removes a 4.0.0 restriction; §23.14 changes by one clause at ratification (permitted to a new MAJOR outside a program window; window closed 2026-10-12). Header block 16.0.0 PROPOSED, `Effective-Date` PENDING, `Supersedes` 15.0.0 while PROPOSED; the ratifying edit set it to 16.0.0 ACTIVE, `Effective-Date` 2026-10-21, `Supersedes` 15.0.0. Numbered 16.0.0 after 15.0.0 (PR #1852, ACTIVE). | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1416ab9f240a69def0523dd125afbc18` (operator, PR #1911 comment by PatsKiller 2026-10-22T02:33:20Z, https://github.com/PatsKiller/tardeai/pull/1911#issuecomment-6331278599, verbatim: "APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1416ab9f240a69def0523dd125afbc18"); ratified by this edit on #1911's branch, which replaced the five clauses quoted in §23.21; approval phrase as proposed `APPROVE_AGENTS_POLICY_16_0_0 <pr_number> <head_sha>`; per-PR word, because it changes `AGENTS.md`. Effective 2026-10-21. |
| 15.0.0 | 2026-10-18 | ACTIVE | MAJOR | §24.12 "Disk hygiene: the only automated deletion" added, one sentence added to §0 rule 6 and one entry added to §17 (both inserted by the ratifying edit in `AGENTS.md`, the four adapters and §17; absent while PROPOSED). Operator-directed 2026-10-18, verbatim: "i approve automatic deletion would need an AGENTS.md amendment" (root disk 89%; about 100 GB of stale clones/worktrees and 36 GB of old releases). Once ACTIVE, the weekly n8n lane `disk-hygiene` (or the operator at the CLI) may run ONLY `scripts/disk_hygiene.py` under `config/disk_hygiene_rules.json` to remove: git clones/worktrees that are clean, have no untracked files and no unpushed commits, are merged into `origin/main`, are referenced by no CURRENT release, unit or crontab line, hold no process cwd and are idle past N days; and release directories other than CURRENT, the previous release and the newest N. A code-enforced never-touch list (db_backups, persistent-state, models, .env/credential/cookie/token paths, .ssh, .config, Docker and n8n volumes) holds over every rule; changing the rules or the list is an operator config change (config-write grant + reviewed PR; new §17 entry "changing the disk-hygiene rules or never-touch list"). Every apply needs a fresh manifest, re-validates each item, respects per-run byte/item caps and writes a `LaneRunReceipt@v2` with each removed path, size and rule evidence; the first live apply follows the operator's review of a manifest; kill switch = remove the lane from `TRADEAI_N8N_RELAY_LIVE_LANES` or set `auto_apply` false. No agent deletes by hand; data, backups, DB rows and credentials stay under "Never delete". Open gap: `scripts/disk_hygiene_enforcer.py` (release and backup removal) is not covered and is retired or folded by its own PR. MAJOR: it narrows §0 rule 6 for one lane (version policy; precedent 5.0.0, 14.0.0). Tests: `tests/test_agents_policy_15_0_0_disk_hygiene.py`. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_15_0_0 1852 fc56728962fd51c94b3dc8cfd67e2df334eda88f` (operator, PR #1852 comment by PatsKiller 2026-10-21T19:37:58Z, https://github.com/PatsKiller/tardeai/pull/1852#issuecomment-6324859562, verbatim: "APPROVE_AGENTS_POLICY_15_0_0 1852 fc56728962fd51c94b3dc8cfd67e2df334eda88f"); ratified by this edit on #1852's branch; ratifying edit inserts the §0 rule 6 sentence in `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/00-tradeai-work-policy.mdc`, `.github/copilot-instructions.md` and `.goosehints`, and the §17 entry; approval phrase as proposed `APPROVE_AGENTS_POLICY_15_0_0 <pr_number> <head_sha>`; per-PR word, because it changes `AGENTS.md` §0 and §17. Effective 2026-10-21. |
| 14.0.0 | 2026-10-16 | ACTIVE | MAJOR | §24.11 "Read-only broker sync — the `broker-read` grant" added, and one sentence added to §0 rule 2 (inserted by the ratifying edit in `AGENTS.md` and the four adapters; it was absent while PROPOSED). Operator request 2026-10-16: "make that bash so agents can run, make amendment, not trading just reading, update agents.md". With an active operator `broker-read` guard grant (≤ 4 h, one use per run, remotely grantable, revocable), an agent may invoke ONLY `scripts/ops/broker_read_sync.sh` — the repo form of the operator's `sync_all_readonly.sh`: a closed eight-step allowlist (`broker_read_sync_policy.STEPS`) of Schwab, Alpaca, moomoo and SnapTrade position and transaction reads into our own stores, dry run by default, `--apply` to write, `--plan` contacting no broker. It refuses unless the trading lock is LOCKED for every broker, the Schwab access mode resolves to `read_only` for the run, the static capability audit of every step's effective import closure is clean, and it runs from the served release. `.env` is sourced only inside each step's own shell and never printed; output is scrubbed. Re-auth, token refresh, 2FA and flags are unreachable (runtime stubs, broker-host non-GET refusal); no token → `needs_operator_reauth`, stop. Stop managers, stop sync, options lifecycle, defense execution, order pilots, approval/2FA, order transports, the API server and active trader are excluded and refused at import; CI pins it (`tests/test_broker_read_sync_20261016.py`). Receipt `BrokerReadSyncReceipt@v1`. Guard scope `broker-read` in `bin/guard` and `.cursor/hooks/guard-lib.sh` (operator-only guard configuration, carried in the PR for review). MAJOR: it narrows §0 rule 2 for one read-only purpose (version policy; precedent 5.0.0). Numbered 14.0.0 because 12.1.0 (nightly cutover controller) and 13.0.0 (PR #1830) are claimed. Tests: `tests/test_agents_policy_14_0_0_broker_read.py`. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda` (operator, PR #1838 comment by PatsKiller 2026-10-16T22:44:55Z, verbatim: "APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda"); merged #1838 as `0c5998042` (operator-merged 2026-10-16T22:44:57Z) while PROPOSED; ratifying edit inserts the §0 rule 2 sentence in `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/00-tradeai-work-policy.mdc`, `.github/copilot-instructions.md` and `.goosehints`; per-PR word, because it changes `AGENTS.md` §0. Effective 2026-10-16. |
| 12.0.0 | 2026-10-15 | ACTIVE | MAJOR | Operator directive 2026-10-15 "N8N Cutover Decision": every lane family cuts over to n8n except F07 (long-running daemons, @reboot) and registry_systemd assets (deferred this iteration). §23.25 added; for the approved families it supersedes the §23.14 scheduling restriction and the §24.1 P0/P1 placement by reference (§23.14 and §24.1 text unchanged); host-side placement rationales are not blockers; F07w and F10 keep independent backstops. Grants nothing beyond scheduling. §0, §2, §2A, §7A, §17 and §22 byte-identical. Tests: `tests/test_agents_policy_12_0_0_cutover_directive.py`. The ratifying edit set the header to 12.0.0 ACTIVE, `Supersedes` 11.0.0. | **RATIFIED 2026-10-15** (`APPROVE_AGENTS_POLICY_12_0_0 1779 4aeb8cf4e`, §20; PR #1779 comment by PatsKiller 2026-10-15T21:12:48Z); merged #1779 as `818d6d9c4`, ratified by this edit. |
| 11.0.0 | 2026-10-14 | ACTIVE | MAJOR | Operator-directed 2026-10-14: n8n is the primary orchestration and automation layer, with "a mandatory standard framework for every n8n workflow, contract, integration and automation". §23.24 "Mandatory n8n workflow framework" added: every workflow in `m8m-n8n` declares a class (business-critical, resilience, AI/LLM, monitoring/compliance) and an owner, and meets six areas, each element with a check that exists (E) or is proposed (P): Monitoring (success joined by `run_id`, failure = error workflow, performance = timeout + p95 bound, capacity = class caps + start lag, dependency = `connects_to`); Alerting (failure, SLA breach watched outside n8n, performance degradation, integration failure routed by class with refusals as data, AI/LLM exception, `runbook_id` on every page; delivery stays with the host comms gateway, P0/P1 never via n8n); Logging (execution, error, audit with a non-superuser n8n DB role, security, change = generated from git + scheduled drift check paging P1); Recovery (one retry owner = Run Lane once built, half-open breakers, declared fallback, dead-letter, manual-recovery runbook, semantic effect key); Security (authN, authZ with one reconciled live authority, secrets, data protection, audit trail); AI/LLM governance (registered template, process id only, caps, closed schema, host re-check and grounding, output guardrails, HITL with host-record authority). Activation bar once ACTIVE: no activation or stage promotion without passing; active non-compliant workflows remediated or archived within 30 days; proposed check `scripts/check_n8n_workflow_framework.py`. Reference documents listed in §23.24 (informational). Measured 2026-10-14: 16 active workflows, none compliant in any area (39% of checks partly met); re-measured 2026-10-15: 18, none compliant (40%). Grants nothing. §0, §2, §2A, §7A, §17, §22, §23.14 and §23.23 byte-identical. Tests: `tests/test_agents_policy_11_0_0_workflow_framework.py`. Numbered 11.0.0 after 10.0.0 (#1736; ACTIVE by #1740); renumbers to 10.1.0 if ruled MINOR; the ratifying edit set the header to 11.0.0 ACTIVE, `Supersedes` 10.0.0. | **RATIFIED 2026-10-15** (`APPROVE_AGENTS_POLICY_11_0_0 1747 89fb642cd`, §20; PR #1747 comment by PatsKiller 2026-10-15T11:51:39Z); content merged via #1754 (`94601ff69`), ratified by this edit. |
| 10.0.0 | 2026-10-14 | ACTIVE | MAJOR | Operator-directed 2026-10-14, verbatim: n8n is "a centralized, intelligent automation fabric that provides: Workflow orchestration, Dependency management, Observability, Alerting, Human approvals, Agent coordination, LLM integration, Event-driven automation, Operational visibility, Auditability, Governance, Centralized controls." and "Do not tell me whether cron is a better scheduler. Tell me whether we are building the right platform." §23.23 "n8n is the automation fabric" added. n8n owns FLOW: sequencing and dependencies, event triggers, retries/backoff/dead-letter decisions through a Run Lane sub-workflow, error workflows, approval timelines (Wait nodes), escalation timers, invoking LLM judgment steps. The host owns AUTHORITY, EXECUTION and EVIDENCE: allowlist, live/dry authority, idempotency keys, secrets, the ledger as audit of record, the comms chokepoint for every send (n8n requests sends through a host intent API and never holds bot tokens). Broker: n8n never holds broker credentials or calls broker/order routes; reads only through the broker gateway (§23.22); writes only through the execution service behind the trading lock plus a per-order operator hardware-key or TOTP assertion over the intent hash; an n8n approval is a request, authority is the host record. LLM steps: governed bridge only, closed schema, branch on enumerated fields only, host re-check, bounded (read-only by default) tools, prompt/response/decision in one audit row joined by run_id ↔ execution_id, never an unlisted action, ingested text is data. Agents are judgment functions invoked by workflows; no side-effect tool without an approval gate; long-running loops retired into event-triggered workflows. Workflow governance: generated from git, never edited in the UI, drift pages P1, successes saved with run_id, an error workflow on every workflow, refusals are data, community nodes off, n8n DB role not superuser. Node enablement: the NODES_EXCLUDE / N8N_DISABLED_MODULES relaxation only for Execute Workflow / sub-workflows, Wait, Form or webhook-resume, Switch/Merge/If, Error Trigger and the AI Agent node restricted to the bridge-backed credential, one reviewed PR each; messaging nodes with their own credentials stay excluded. P0/P1 dead-man and pages never depend on n8n. Migration: timer-only leaf-lane cutovers FROZEN until the Run Lane sub-workflow, the async run-outcome callback and this amendment ACTIVE; then progress = business processes owned and orchestration owners retired; consolidate before migrating (WS2 families); cutover keeps the §23.21 standard plus a fenced single-owner switch. Preconditions before any money-touching flow: CC auth, trading lock served, uid separation for execution, DB role split, signed grants and unlock. WS9 controls C1–C10 bind before each new power. Supersedes, with notes in place and no text deleted, the restrictive parts of §23.1 ("a scheduler and a requester"), §23.11 ("decide nothing", six-workflow ceiling) and §24.1 ("fires host lanes and decides nothing"); one route note added to §23.3 (send-intent, approval-request and run-outcome callback routes, each its own PR). §0, §2, §2A, §7A, §17, §22 and §23.14 byte-identical (§23.14's never-eligible list stands; invoking an agent is a workflow step, not a dispatcher lane). Tests: `tests/test_agents_policy_10_0_0_n8n_fabric.py`. Numbered 10.0.0 after PR #1697 (6.0.0), PR #1727 (8.0.0) and branch `n8nmat/schwab-read-lanes-20261014` (9.0.0), all PROPOSED; header stays 7.0.0 ACTIVE until ratification. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279` (operator, PR #1736 comment by PatsKiller 2026-10-14T23:25:56Z, verbatim: "APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279"); merged #1736 as `3e9dc5e14` while PROPOSED; per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. |
| 7.0.0 | 2026-10-14 | ACTIVE | MAJOR | Operator-directed 2026-10-14 ("move to n8n i approve if i need to make amendment propose its just looking at level 2 on moomoo no trading"): §23.20 "Advisory market-data lanes on the dispatcher" added and one exception bullet added to §23.3. A lane in the code ceiling `lane_dispatch.ADVISORY_MARKET_DATA_LANES` is dispatcher-eligible only when (a) its reach uses market data only (moomoo OpenD quote context; no trade context, order verb, account/position read or broker client module), (b) it writes advisory output only and carries no sandbox/broker submit switch, (c) it sends only through the host `send_telegram` chokepoint (`bypass_router=True` only at sites already on the 5.1.0 allowlist), (d) n8n carries no secret and its `env_names` name no broker credential; class `pipeline`, lock = the cron lock, §23.12 ladder. Enforced by `scripts/lib/advisory_lane_guard.py`, `lane_dispatch.advisory_md_admission` / `advisory_md_static_errors` and `tests/test_agents_policy_7_0_0_advisory_market_data.py`, which also closes the dispatcher sender gap with a shrink-only baseline. §0, §2, §2A, §7A, §17 and §23.14 byte-identical. Numbered 7.0.0 after PR #1697 (6.0.0, PROPOSED); `Supersedes` 5.1.0. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1` (operator, PR #1725 comment by PatsKiller 2026-10-14T14:54:21Z, verbatim: "APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1"; re-approved for the merged head after the chokepoint-exemption commit: `APPROVE_AGENTS_POLICY_7_0_0 1725 1cdcdc7e3`, PR #1725 comment by PatsKiller 2026-10-14T16:09:44Z); merged #1725 as `712478bea`; per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. |
| 5.2.0 | 2026-10-11 | WITHDRAWN (never ratified; §8.1 binding from 25.0.0) | MINOR | §8.1 "Working means validated now — tests, dry run, forced run; natural schedules are monitored, never awaited" added: before an agent calls a build, change or install working it quotes (1) the unit/regression tests for what it touched under `TRADE_AI_CI=1`, (2) a dry run (§0 rule 7, §6), and (3) a forced run — the installed job, stage or workflow triggered on demand exactly as its schedule would (same command, environment, cwd rule, wrappers and locks; an n8n lane through `coordination/run` in the mode its stage allows), proven by a durable artifact dated after the trigger (§0 rule 8). Natural fires are then monitored, never the first proof and never awaited; the first natural fire still settles the separate on-schedule claim, and a failing one reopens the change. Gates already conditioned on natural evidence keep their condition (onboarding step 8, §23.12 last bullet, registry `PAUSED` → `ACTIVE` after natural-slot verification, §23.3 three clean market days, §15). No forced run for broker/order/stop/session/2FA paths (§0 rule 2, §2, §22, §24.10), operator-only surfaces (§17) or a double send to the operator (senders go through the router with dedupe on or use their dry run); clock-gated jobs pass through their wrapper with no override, and a deferral receipt is the proof. A forced run of an `--apply` job needs the grant the install needed; an overlapping natural fire must skip on its lock or run harmlessly; the forced run is recorded in the change record. One-line pointers in §6, §8, §9.3, §16, §23.12 and §23.19; `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` proof steps restate it. §0, §2, §2A, §7A, §17 and §23.14 byte-identical; no adapter changes (a §0 rule 7/8 pointer is proposed in the PR body only). Tests: `tests/test_agents_policy_5_2_0_validation.py`. Cause: 2026-10-10/11 C1 stage-runner manifest flips — flip 1's proof deferred to its 10:50 ET natural fire, flip 2 waited, the grant expired first; operator request 2026-10-11 ~09:22 ET. MINOR: a new proof obligation that widens no authority — forced runs are bounded by existing grants and gates (read as MAJOR, it becomes 6.0.0 unchanged otherwise). | **PENDING** operator ratification `APPROVE_AGENTS_POLICY_5_2_0 <pr_number> <head_sha>` (§20); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. Until then the 5.1.0 text governs. |
| 5.1.0 | 2026-10-11 | ACTIVE | MINOR | §9.1 "Anything the operator must act on bypasses the router" replaced: an operator-action message (asks the operator to approve, deny or decide, or carries a button that does) is sent as a P1 notification intent with dedupe off (`send_telegram(..., priority="P1", dedupe_minutes=0)`, `telegram_alert_router.route_intent`) — never text-classified, capped, quiet-held, archived or suppressed, with a `NotificationIntentRoute@v1` receipt per decision, and still reported *accepted for interrupt delivery*, never *sent*. Two bullets added: `bypass_router=True` is legacy, allowlisted and shrink-only (`BYPASS_ALLOWLIST`, `tests/test_notification_intents_20261010.py`), with the four broker-execution sender units (`alpaca_stop_manager.py` ×2, `defense_execution.py`, `moomoo/opend_health.py`) and `active_trader/momentum_alerts.py` keeping their bypass until an `execution-engineering` grant names them, and `guard_request_approval.py` allowlisted; a P2 intent is held 22:00–07:00 ET (the incident notifier's window) to the Reports archive (`notification_intent_p2`) and folded into the advice digest, delivered if the hold cannot be archived, and anything that must reach the operator in the quiet window is P1. One sentence each added to the §8 remote-approval paragraph and the §24.1 "Senders emit notification intents" bullet, pointing to §9.1. Cause: PR #1685 (`n8nmat/bypass-senders-to-intents`, head `1d9eba216`, held for this amendment) moves 25 of the 30 measured `bypass_router=True` senders to intents (operator 2026-10-10). Merge order: #1685 first. Open item for #1685: `stop_decision_brief.py` is P1 with the default 60-minute dedupe; the operator classifies it before #1685 merges. MINOR: it replaces a mechanism with an equal guarantee for operator-action messages plus a receipt, and adds a declared dedupe window and a never-dropped hold for the rest; no authority rail, operator-only boundary, role, broker reach or egress changes. §0, §2, §2A, §7A, §17 and §23.14 byte-identical; no adapter, `CLAUDE.md` or `AI_WORK_POLICY.md` change. Read as MAJOR, it becomes 6.0.0 unchanged otherwise. Tests: `tests/test_agents_policy_5_1_0_notification_intents.py`. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_5_1_0 1689 b0f0c6eeb` (operator, PR #1689 comment by PatsKiller 2026-10-11T13:12:31Z, verbatim: "APPROVE_AGENTS_POLICY_5_1_0 1689 b0f0c6eeb"); merged #1689 as `26cf80f606e5bb797d5a5b714b23acb3ff95a9c6` (auto-merged 2026-10-11T13:15:17Z); ratification edit on the operator's in-session word 2026-10-11 ("yes - ratify 5.1.0"); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. |
| 5.0.0 | 2026-10-10 | ACTIVE | MAJOR | §24.10 "Broker-adjacent daemon operations — the `execution-ops` grant" added, and one sentence added to §0 rule 2 pointing to it (binding only once 5.0.0 is ACTIVE). Under a per-incident `execution-ops` guard grant (≤ 6 h, remotely grantable by Telegram `/approve`, reason naming the unit, the actions and the incident), an agent may operate a broker-execution unit — a user unit whose `ExecStart` runs `scripts/active_trader/**` or `scripts/brokers/**`; measured: `tradeai-active-trader-motion.service` only. It may inspect status, journal, cwd and drop-ins (never `Environment` or env files). It may re-point the code root by `95-code-root-current.conf` to `portfolio-server/CURRENT`, archiving the superseded drop-in by rename. It may run `daemon-reload` with the restart, and `restart`. It may create or archive the unit's enable flag only under the operator's home (`/etc` flags stay operator-only). Every mutation runs only while `cio_market_session` says `CLOSED`, failing closed. A quoted preflight comes first: grant, market state, the unit's tests at CURRENT under `TRADE_AI_CI=1`, no store or `output_signal` move (unit-code-roots checks; `STORE_RISK` goes to the operator, §0 rule 5), `systemd-analyze verify`, and a dry run. Proof is by cwd readback and a receipt; rollback restores the archived drop-in. Never code edits, credentials, live/paper flags or modes, a restart into live mode (A4), order, stop, session-grant or 2FA paths, or broker calls. OpenD (`scripts/moomoo/**`), `--mode live` units, system units and root actions are out of reach. Guard scope installed by the operator-run `packets/agents-4-7-0/install_execution_ops_scope.py` (`bin/guard` `ALL_TIERS` plus a 6 h cap, `guard-lib.sh` scope text and classifier, hook rule `broker.execution_ops`); open gaps stated (unit binding is by reason text; other verbs still classify `service`; Claude hook not installed; the remote grant needs the scope in the poller's release). The §0 change is exactly that one sentence: the 4.1.0, 4.3.0, 4.4.0 and 4.6.0 tests strip it before hashing, and their §0 digest is unchanged. §2, §2A, §7A, §17 and §23.14 are byte-identical; the four adapters must carry the same sentence byte for byte (`tests/test_agents_section_zero_parity.py`); the operator applies it with the packet's `apply_adapters.py` before push, because `CLAUDE.md` is the operator's file. Tests: `tests/test_agents_policy_5_0_0_execution_ops.py`. Causes: the 2026-10-10 ~21:30–21:49 ET motion-unit incident (exact-SHA drop-in archived by hand, start skipped on the missing `/etc` flag, unit inactive on the dev-tree root); operator requests of 2026-10-10 ~21:50 and ~21:52 ET. MAJOR: it narrows §0 rule 2 for one operational purpose (version policy: authority rails and broker access, classified by the weakest guarantee); requested as 4.7.0 (MINOR) and renumbered. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_5_0_0 1686 d51b6c50e` (operator, PR #1686 comment by PatsKiller 2026-10-11T12:33:56Z, verbatim: "APPROVE_AGENTS_POLICY_5_0_0 1686 d51b6c50e"); merged #1686 as `0ec32048669b6a8329b6ab60818cbf527e01f30b` (operator-merged 2026-10-11T12:33:58Z); ratification edit on the operator's in-session word 2026-10-11 ~08:40 ET ("ratify 5.0.0"); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md` §0. Effective 2026-10-11. |
| 4.6.0 | 2026-10-10 | ACTIVE | MINOR | §24 "Platform rules from the 2026-10-10 consolidation" added, outside the §23 carve-out: §24.1 notifications — n8n orchestrates (fires host routing, digest, escalation and callback lanes; decides nothing), the host communications gateway (`send_telegram` + delivery ledger + `check_comms_gateway_enforcement.py` ratchets) is the only sender, the P1 path does not depend on n8n, new or changed senders emit notification intents (~66 direct senders are inventory migration work) (backlog A3); §24.2 search source routing — free lane first, paid Brave only on measured insufficiency, `config/search_routing_policy.json` authoritative once merged (#1676, engine OFF by default), dollar lines $20 account / $18 local ceiling / $15 target / $12 non-priority stop, pools scalp 50% / operator 20% / catalyst 20% / other 10%, request breaker raise approved (≥3,000/month; registry still 120/day 1,500/month), SearXNG never names a Brave engine, one Alpha Vantage owner at ≤23/day with scope A1–A3 + B1 + B2 (#1675), NewsAPI retired (A4); §24.3 data broker — owner lanes are single writers, consumers read `BrokerReadEnvelope@v1` projections, lane-script direct reads become a checked violation (checker extension required), approved domains listed (A5); §24.4 other applications (NYC DOF) are not Trade AI lanes and never use Trade AI resources or the `trade_ai` role (`dof_app`); §0 and §17 still bind (A6); §24.5 no push, PR or remote write from a scheduled job (#1672) (A7); §24.6 tests never touch production state, `TRADE_AI_CI=1` (RC7, RC1 link) (A8); §24.7 agents never read, copy or symlink `.env` or credential files (A9); §24.8 a release grant names the SHA or PR (`ReleaseGrantBinding@v1`) (A10); §24.9 Supabase / n8n Cloud portability (A11). In-place correction (PATCH-level, §12): the `braveapi` engine row records the 2,357 uncounted HTTP 422 calls and the approved, pending disable. One-line pointers to §24 added in §8A, §9.1, §9.3, §12 and the operator-approval section. §0, §2, §2A, §7A, §17 and §23.14 byte-identical; no allowlist `never`, `CLAUDE.md` or `AI_WORK_POLICY.md` change. Numbered after 4.4.1 / 4.5.0 in open PR #1666; renumbers to 4.5.0 if #1666 is withdrawn or this is ratified first. Tests: `tests/test_agents_policy_4_6_0_platform_rules.py`. Causes: operator rulings 2026-10-10 ~13:00, ~17:45, ~18:03, ~18:28, ~18:35, ~18:40 ET and two later the same evening (session record; logged as ~19:05 and ~19:45, stamps ahead of the host clock); REMEDIATION_PLAN §8 RC1/RC7; JOB_REDUCTION_DEEP_PASS §11; CONSOLIDATION_PLAN §E; the 2026-10-10 ~17:07 ET release-grant refusal; the `.env` symlink incident. MINOR: every item adds an obligation or a restriction; nothing widens n8n, broker, egress, §17 or role authority (read as MAJOR, it becomes 5.0.0 unchanged otherwise). | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_4_6_0 1682 9dd9e7d6b` (operator, PR #1682 comment by PatsKiller 2026-10-11T02:58:29Z, verbatim: "APPROVE_AGENTS_POLICY_4_6_0 1682 9dd9e7d6b"); merged #1682 as `6943506029adc622930bf63c189a11729c8e151d` (operator-merged 2026-10-11T03:10:07Z); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. |
| 4.5.0 | 2026-10-10 | ACTIVE | MINOR | §23.19 added: `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` is the mandatory procedure for adding or changing anything n8n fires, watches or calls (lane at any stage, dispatch / `r1_pending` row, generic workflow, relay route, gateway lane, executor setting), with the checklist evidence and per-lane template in the PR; no lane enters shadow, canary or cutover without a workflow health contract in `config/n8n_health_contracts.json` (gate `scripts/check_n8n_health_contracts.py`; new lanes REVIEWED before the registry PR; canary/cutover REVIEWED with no UNKNOWN; 2026-10-10 DRAFTs grandfathered at their stage of that day); `scripts/check_n8n_relay_contract.py` passes before any n8n import and import verification never reads an n8n execution status. Adds obligations and grants nothing; §0, §2, §2A, §7A, §17 and §23.14 byte-identical. Tests: `tests/test_n8n_onboarding_standard_20261010.py`, `tests/test_n8n_health_contracts_20261010.py`. Causes: W0 rollback 2026-10-10 15:58 ET (RC8/RC9); operator 2026-10-10 ~16:35, ~16:40, ~16:45 ET. MINOR: a new mandatory operating and evidence rule, weakening nothing. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_4_5_0 1666 987bf94da` (operator, PR #1666 comment by PatsKiller 2026-10-11T01:46:33Z, verbatim: "APPROVE_AGENTS_POLICY_4_5_0 1666 987bf94da — and yes to the 4.4.1 PATCH"); merged #1666 as `dd8f4cff1f37be5e27d344acdfa7cfbe8a386285`; ratification edit on the operator's in-session word 2026-10-10 ~21:55 ET ("Yes, I ratify 4.50"); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md`. |
| 4.4.1 | 2026-10-10 | ACTIVE on merge | PATCH | §12 off-peak arming restated as measured 2026-10-10: the crontab header sets `LLM_DEFER_OFFPEAK=1` for every cron line (operator, 2026-09-20), systemd units set it per unit (portfolio-server, cio-reactive, nightly-reflection drop-ins and the executor and health-tick units `=1`; hermes-cio-worker `=0`); the 2026-09-20 "exactly one place" sentence is replaced, and "never arm it in passing" now reads arm, widen or disarm. The process-boundary wrapper count is re-measured (19 active lines: 2 `--scheduled`, 8 `--official`, 9 default; 17 on the older `~/.config/tradeai/bin` copy) and `--defer-in-process` (#1652) is named. §23 gains an informational pointer to `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md`, `N8N_ONBOARDING_STANDARD.md` and `N8N_MONITORING_AND_REMEDIATION_STANDARD.md` (restate §23, add no rule). No required behaviour changes; §0, §2, §2A, §7A, §17 and §23.14 byte-identical. Cause: REMEDIATION_PLAN §8 "crontab header sets LLM_DEFER_OFFPEAK=1 for all lines (AGENTS §12 drift)"; the W0 rollback. | **Operator-directed** 2026-10-10 ~16:35 ET ("Make sure you totally update the documentation on this and the agents.md or any other files that need to know these baseline configurations"). PATCH outside §0/§2/§17: rides `APPROVE_AGENTS_POLICY_1_2_0`, ACTIVE on merge; merge needs the operator's per-PR word (§23.13 excludes `AGENTS.md`). |
| 4.4.0 | 2026-10-10 | ACTIVE | MAJOR | R1 shadow and canary row shape (§23.11, §23.18 (c)). A §23.11 dispatcher row (`kind: n8n`, `expression: "dispatcher"`) fails `CRON_PRESENT_WHILE_SCHEDULER_N8N` and the inactive-n8n-row check while its cron line is live, which is true through shadow and canary. The shadow wave is therefore built as cron rows, and 4.3.0 §23.18 (c) refused every R1 lane in that shape. Now an `ingest`, `llm` or `learn` lane may use the cron row at `shadow` (`dispatch.mode: dry_run`, allowlist `live_arg` null) and at `canary` (`dispatch.mode: live`, `live_arg` set, `lock_kind: flock`, allowlist lock equal to every `flock` lock in `scheduler.command_text`, so the lock proves no double run, §23.12). Cutover keeps the dispatcher row. Gate in code: `lane_dispatch.r1_shadow_on_cron_shape`, `r1_canary_lock_matches` and `r1_class_admission`, inert until `R1_SHADOW_SHAPE_STATUS = "ACTIVE"`. Every other R1 condition is unchanged: R1 ACTIVE, `dispatch_eligible`, no daemon, `dry_run_arg`, LaneRunReceipt@v1, no broker credential, and for `llm` the governed bridge. Naming: `dispatcher` is the row expression; `tradeai-dispatcher` (the workflow id; design 02 §12.2 wrote it as the expression) is refused by the gate and the registry check, clamped to `dry_run` by the stage clamp, and refused as `_cutover.py --workflow-id`. `--workflow-id dispatcher` leaves the row at stage `cutover`. The allowlist `never` sentence for the three classes names both cron rows; every never-under-any-class entry is word for word. No sentence of §0, §2, §2A, §7A, §17 or §23.14 changes. Tests: `tests/test_agents_policy_4_4_0_r1_shadow_shape.py`, `tests/test_r1_shadow_shape_20261010.py`. Causes: Agent A finding 2026-10-10 (no R1 lane could shadow); operator ruling 2026-10-10 ~14:00 ET ("All yes": extend 4.4.0 to canary). MAJOR: the R1 admission widens by two row shapes, one of them a live fire. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_4_4_0 1660 463535dfe` (operator, PR #1660 comment by PatsKiller 2026-10-10T20:04:37Z, verbatim: "APPROVE_AGENTS_POLICY_4_4_0 1660 463535dfe"); merged #1660 as `40e445d790c4b8294c3f2e3fb64cbb9f1658e9d9`; approved in principle 2026-10-10 ~14:00 ET ("All yes"); per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md` and the allowlist `never` list. The ratifying edit sets `R1_SHADOW_SHAPE_STATUS = "ACTIVE"`. |
| 4.3.0 | 2026-10-10 | ACTIVE | MAJOR | R1 (§23.18): `ingest`, `llm` and `learn` become dispatcher-eligible classes, always shadow → canary → cutover by §23.11 registry PR and §23.12 waves. Gate in code: `scripts/lib/lane_dispatch.py` `r1_class_admission`. It requires R1 ACTIVE (`R1_STATUS`), `dispatch_eligible`, a dispatcher row at stage shadow/canary/cutover, a non-empty `dry_run_arg`, a `LaneRunReceipt@v1` `output_signal` that matches the allowlist, and no broker credential in `env_names`. An `llm` job also needs `llm_route` via `cio-governed-bridge` with a registered process and no provider/model argv. `n8n_due` and `validate_dispatch_block` both ask the gate, and `send` stays refused. `EXTRA_FORBIDDEN_SUBSTRINGS` gains `render_env`, `rotation_daemon` and `bitwarden` (measured: `render_env.py --write` passed `dispatch_eligible`); this only tightens the matcher. The governed DeepSeek route is approved for L401 overnight only; measured: today it calls `llm_lane` in-process, not the bridge, so it stays on cron until rerouted or ruled. Ruling 4: `alert_events` rows are not a send; `paper_trade_proposals` backtest fields are not paper execution; the L504 `symbol_profiles` and L205 `market_regime` writers are approved for dispatch. Rulings 2 (whole-word/path-segment token matching) and 3 (entry planner via the data broker; no broker credentials in lanes) land as separate code PRs. Allowlist `never` reworded: broker/order/stop/paper/sender/secret/guard/deploy/agent-loop stay never under any class; the three classes are excepted only once 4.3.0 is ACTIVE; "Sole exception: trade-ai-scalp-live" kept. No sentence of §0, §2, §2A, §7A, §17 or §23.14 changes. Numbered after 4.2.0 PROPOSED (#1634). Tests: `tests/test_agents_policy_4_3_0_r1_classes.py`. Causes: the cron inventory of 2026-10-09 (247 active rows needing refactoring, mostly policy-blocked); refactor wave 1 #1641 (36 rows needed dry-run and receipts); wave 2 V3 (L401 governed route missing). MAJOR: the n8n actor may cause three more classes of host work; broker, secret and delete rails unchanged. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_4_3_0 1642 64c9210e1` (operator, 2026-10-10 ~09:10 ET, in session, verbatim: "APPROVE_AGENTS_POLICY_4_3_0 1642 64c9210e1"); re-approved by the operator 2026-10-10 ~09:25 ET, in session, verbatim: "approved", for PR #1642 head `c3d5e895d4de5eb16f43f90ce8f43dc61a0cadfc` after the conflict merge with #1643 (which changed only the forbidden-token list in `scripts/lib/lane_dispatch.py`; `AGENTS.md` and `config/n8n_run_allowlist.json` byte-identical to `64c9210e1`); merged #1642 as `203b469146154c6729620a2428fcb76740a4d0a8`; the ratifying edit sets `R1_STATUS = "ACTIVE"`; per-PR word, excluded from the §23.13 standing merge approval because it changes `AGENTS.md` and the allowlist `never` list. Operator rulings recorded 2026-10-10 ~00:20 ET: (1) ingest writers, governed LLM jobs and learning/memory writers are dispatcher-eligible, always shadow → canary → cutover; governed DeepSeek route approved for L401; (2) whole-word / path-segment forbidden-token matching; (3) entry planner (L473/L474) via the host data broker, no broker credentials in lanes; (4) `alert_events` rows not a sender, `paper_trade_proposals` backtest fields not execution, L504 and L205 approved for n8n. |
| 4.1.0 | 2026-10-09 | ACTIVE | MAJOR | §23 amended for the N8N Maturity Acceleration program (`docs/implementation/n8n-maturity/00-MASTER-PROGRAM.md`): §23.11 registry-driven dispatch (six generic workflows — dispatcher, event router, heartbeat watcher, incident router, digest scheduler, approval router — activated once under one `cron` grant listing their ids; a lane is enabled by a reviewed PR adding its registry row `kind: n8n`, `expression: "dispatcher"`, `cadence`, `match`, `wave`, `stage` plus its `config/n8n_run_allowlist.json` entry, no per-lane import or grant; gateway read route `coordination/due` computes due lanes with `cron_schedule.next_run`; mode clamped to stage; lane identity server-side; the five non-dispatcher workflows send nothing and the approval router never mints or approves a grant; one registry PR at a time); §23.12 wave ladder (whole-wave dry_run then live-with-cron fire, receipts per lane per fire, failing lanes stay on cron, cutover per wave under one `cron` grant naming every lane, per-lane `CutoverReceipt@v1`, per-line rollback, natural-schedule evidence still owed); §23.13 program window (push budget 4 for `n8nmat/*` until 2026-10-12T23:59:59-04:00 via `.githooks/pre-push` + `scripts/lib/tradeai_push_budget.py`; no merge queue (user-owned repository) and strict protection off; standing 48 h merge approval — Agent A's review verdict on the program board, the three required checks green on the exact head, nothing live until main CI is green on the merged SHA — with `Expires-At` set at ratification + 48 h, excluding governance, hook, guard, branch-protection, broker, secret and allowlist-`never` changes; merge only, never deploy or grant); §23.14 broker, order, secret and daemon lanes never dispatcher-eligible, by test (`tests/test_agents_policy_4_1_0_amendment.py`); `trade-ai-scalp-live` stays the single named exception, only on its 4.0.0 §23.3 terms; read-only guard carve-out — the approval-router lane may read pending guard requests and grant expiry through `scripts/lib/approval_board_projection.py`, never request, grant, revoke or consume, test-pinned; the guard `never` entry still blocks every guard write. Replaced in place: §23.2 "Registry row first", "Install, activate, edit or retire…" (one grant tier, `cron`; audit E D5) and "Shadow before canary before cutover"; §9.3 scheduler-entry bullet; §17 n8n fragment; §23.5 present-tense facts (rotation unscheduled; relay credential created 2026-10-08T16:45:48Z with MFA off and DB role `n8n` superuser, still open; P13 open); `AI_WORK_POLICY.md` §3/§17; `scripts/check_n8n_activation_grants.py` tiers `cron` only. Causes: due-diligence audits A–F of 2026-10-09 (audit E C2, C3, C4, C5, C6, C8, D5, D7); 438 cron lines, 321 undeclared, 4 lanes moved. MAJOR: §17 and merge/push authority change; nothing in §0, §2, §2A or §7A or the broker, secret or delete rails is weakened. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_4_1_0 1592 2f824b4f789110d6ccc5f3c7d5783aa9e995a079` (operator, 2026-10-09 ~17:30 ET, in session: "Approve agents 4.1.0"); merged #1592 as 71d27c799; standing merge approval expires 2026-10-11T17:30:03-04:00; operator decisions recorded 2026-10-09: (1) registry-driven dispatch — one `cron` grant activates the six generic workflows, lanes enabled by reviewed registry PR; (2) wave ladder with one `cron` grant per wave cutover; (3) push budget 4 for `n8nmat/*` until 2026-10-12T23:59:59-04:00, hook-enforced; (4) standing 48 h merge approval for `n8nmat/*` PRs with a board review verdict, green on the exact head, nothing live until main CI is green on the merged SHA, merge only; (5) 16:40 ET: read-only guard projection for the approval router, never a guard write. |
| 4.0.0 | 2026-10-09 | ACTIVE | MAJOR | §23.3 gains one named live-lane exception: `trade-ai-scalp-live` (Finviz ingest via the data broker, `trade_ai_scans` writer, `send_telegram` caller) may run `live` from n8n, only under the cron line's argv, lock, 295 s timeout and market gate, no provider key in n8n, relay live-lane listing and a workflow-id grant; cron stays the fallback until 3 clean market days. §23 status line corrected (stale 3.0.0 "awaiting" sentence). Allowlist `never` names the exception; `live_arg: []`. Evidence: `docs/implementation/n8n-parallel/lanes/scalp-lane-20261009.md`, PR #1573, `tests/test_agents_policy_4_0_0_scalp_lane.py`. | Operator 2026-10-09 15:25 ET in session: "APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix" (`APPROVE_AGENTS_POLICY_4_0_0`), after "n8n drives a governed lane (Recommended)". |
| 3.0.0 | 2026-10-09 | ACTIVE | MAJOR | §23 amended for governed LLM and Agent capability in n8n: §23.3 first bullet replaced (n8n workflows **and Agent nodes** cause host work only through the relay → gateway `coordination/run` for allowlisted lanes and the read-only coordination endpoints; Agent tools = those endpoints; never-list incl. DOF SQL applies to Agent tools; per-process tool allowlist enforced at the bridge with typed refusal; container internet egress BLOCKED by a DOCKER-USER rule, host reach only `172.19.0.1:18092`); §23.4 replaced (capability not provider: registered `n8n_*` process + versioned template + optional routing policy through the governed bridge; default routing Grok OAuth → ChatGPT OAuth → DeepSeek metered; free text only after `sanitise_for_external` for `free_text_allowed` processes; output schema + behaviour-field scan at the bridge; caps and typed refusal kept); §23.5 first bullet replaced (at most two credentials — relay bearer, and a bridge token only after §23.10; owner MFA waived; non-superuser `n8n_app` role still required); §23.8 n8n Agent nodes (registry row, receipt per turn, grant naming the workflow id, model node → bridge only, tool nodes excluded, turn/token/wall caps, no streaming until audit B H1 is fixed; first Agent read-only "explain why lane X failed", coordination-read tools only, shadowed first); §23.9 governance parity; §23.10 preconditions P2–P9, P11–P13, P15–P22 as a checklist that grants nothing until each is measured true with a receipt. §17 gains Agent-node activation / bridge-token creation; §23 and top-of-file 2.0.0 status lines corrected; ADR_COORDINATION_SECRETS Policy line fixed + 3.0.0 addendum. Proposal `docs/implementation/n8n-parallel/proposals/agents-3-0-0-governed-n8n-agents-20261009.md`; audits `docs/implementation/n8n-parallel/audits/guardrail-audit-a-config-20261009.md`, `guardrail-audit-b-code-20261009.md`, `guardrail-audit-c-policy-n8n-20261009.md`. MAJOR: egress policy and the n8n actor's authority change; nothing in §0, §2, §2A, §2B or §7A is weakened for any actor. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_3_0_0 1547 a0984546181d316f92931c7b87218b55b3b836d9` (operator, 2026-10-09, in session); proposed text merged #1547 as `3b5c24856`; ratification (the activation event) merged #1552 as `377e9b536`; operator decisions recorded 2026-10-09: (1) ratify the proposal's §3 text as 3.0.0; (2) routing Grok → ChatGPT → DeepSeek; (3) container internet egress blocked, not proxied; (4) first Agent read-only lane-failure explainer, shadowed first; (5) owner MFA waived, `n8n_app` role still required. |
| 2.0.1 | 2026-10-08 | ACTIVE on merge | PATCH | On top of 2.0.0: Telegram/Communications section gains the Investment Command Center rule: opportunity rules in `config/opportunity_conviction.yaml`; curated assessments persisted only by `cio_opportunity_curator.py` into the CIO opportunity store (never as a thesis version); no behaviour keys; the Telegram opportunity line only via `send_telegram`. Adds obligations, weakens nothing; §0/§2/§17 untouched. | Operator-directed 2026-10-08 (/plan Investment Command Center; "make sure all data is curated by and persistent in CIO memory"; "resonate in telegram alerts"). |
| 2.0.0 | 2026-10-08 | ACTIVE | MAJOR | §23 "n8n: scheduler-of-record and governed routing (carve-out, n8n only)" added: scope limited to the `m8m-n8n` compose project; n8n workflows are §9.3 scheduler entries (registry row with `output_signal` first, grant-gated install/activate/edit/retire, shadow → canary → cutover → per-line rollback, `# RETIRED <date> n8n-cutover <lane_id>` never deleted, double scheduler fails the registry gate); the only trigger path is the gateway `coordination/run` operation for lanes in `config/n8n_run_allowlist.json` (never broker/order/stop/position/paper-execution/sender/secret-render/guard/release-deploy/destructive-retention/memory-writer/authoritative-ingest), gateway never spawns, executor reuses the lane's lock, RunReceipt is the evidence; n8n may pick registered `n8n_*` process ids, versioned template ids and named routing policies but never a model, provider, raw prompt or caller identity, every call capped by the process registry and the $2.00/day cap with typed refusal; exactly one n8n credential (relay bearer from Bitwarden SM, weekly rotation, valid only at the relay), HMAC key host-side, `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` + prune ≤168 h as the precondition; n8n is replaceable. §9.3 and §17 amended in place; ADR_COORDINATION_SECRETS moves to ACCEPTED (one credential). MAJOR: routing and scheduler reach widen for one actor; nothing weakened for any other. | **ACTIVE** — ratified `APPROVE_AGENTS_POLICY_2_0_0 1513 20d8b5f0d88ac4943612b6703402f638ba3ed9af` (operator, 2026-10-08, in session: "i approve"); merged #1513 at 2026-10-08T09:06:46-04:00; operator direction 2026-10-08 ("make agents.md carve out just for n8n"; decisions 1–3 of the n8n program plan). |
| 1.6.1 | 2026-10-08 | ACTIVE on merge | PATCH | Telegram/Communications rule extended to the Watchlist: Watch decision standards live in `config/watch_decision_standards.yaml` via `lib/data_broker/watch_decision.py`; the signal expires, never the membership. No rule weakened; §0/§2/§17 untouched. | Operator-directed 2026-10-07 ("watchlist etc"; "start the watchlist"). |
| 1.6.0 | 2026-10-07 | ACTIVE on merge | MINOR | Telegram section gains "Communications is the single record of operator message traffic": every operator send/receive is recorded in `communication_events` (`send_telegram` or `record_operator_message`); classification and TTLs live in `config/comms_categories.yaml`; removal only through `comms_lifecycle.py` archive-then-delete. Adds obligations, weakens nothing; §0/§2/§17 untouched. | **Operator-directed** 2026-10-07 (Communications hub spec; "Same TTL as everything"; "Archive, then remove"). |
| 1.5.1 | 2026-10-06 | ACTIVE on merge | PATCH | §7A positions known-gaps measurement updated: reinvestments no longer merged by a missing orderId, broker precision kept, per-account replace window; ledger lots reproduce the broker for every Schwab position. No rule change. | Operator-directed 2026-10-06 ("fix the lot transfer direction gap now"). |
| 1.5.0 | 2026-10-06 | ACTIVE on merge | MINOR | §7A positions "Known gaps" rewritten after the fix: the Schwab ingest dropped transfer/journal direction (abs() of the security leg); outflows are now `Security Transfer Out` / `Journaled Shares Out`, and agents must never take abs() of a broker leg. Lots reproduce the broker except 3 explained rows. Adds an obligation, weakens nothing; §0/§2/§17 untouched. | **Operator-directed** 2026-10-06 ("fix the lot transfer direction gap now"; earlier "edit agents.md with correct source of truth"). |
| 1.4.0 | 2026-10-06 | ACTIVE on merge | MINOR | §7A gains "Positions, cost basis and portfolio value — the source of truth": the truth per fact (shares/cash = broker read; basis = broker average × shares for the same account; price = data-broker quote at read time; realized = broker-matched sells), the shadow positions store and its single writer `scripts/positions_sync.py`, seven enforced rules (no new holdings.json writer; shared write lock; per (account, symbol) comparisons; broker basis applied not reverted; no hard-coded thresholds; read-only broker clients only; validate with `portfolio_reconcile.py`), the `config/portfolio_positions.yaml` rule table, and measured known gaps. Adds obligations, weakens nothing; §0, §2, §17 and role authority untouched. | **Operator-directed** 2026-10-06 ("edit agents.md with correct source of truth so no other agents changes and see the config rules"). |
| 1.3.0 | 2026-09-27 | ACTIVE | MAJOR | §22 added: operator-directed resolution of the §0/§1 broker prohibition vs architecture v3.3 — authority hierarchy, five distinct authorities (coding, simulation, deployment, live activation, broker order authority), LLMs never hold live activation or order authority, `TradingSessionGrant@v1` verified at the broker mutation boundary (pure verifier + 26 negative tests; not wired until ratified), Stage 14 keeps its separate operator start, and AI_WORK_POLICY.md's push budget outranks the implementation program (v1.2). §0/§1/§2B/§17 text unchanged until ratification; replacement text in `docs/governance/agent-standards/AUTHORITY_AMENDMENT_1_3_0.md`. Adds companion `AGENT_OPERATING_STANDARDS_v1.md`, `REPOSITORY_PROTECTION_ADMIN_ACTIONS.md`, `.github/CODEOWNERS` (advisory until code-owner review is required), `.github/pull_request_template.md`. | **RATIFIED 2026-09-27** — `APPROVE_AGENTS_POLICY_1_3_0 1232 1ea66d24912b4242a49d42cc92e94b0030ec4173`; operator direction 2026-09-25 ("Yes, mine, draft it"); independent review confirmed by the operator 2026-09-27; ratification condition: A1/A2 on the execution file set only under an active per-task `execution-engineering` grant ("approve the amendment with a process of the approval to do when we need"). Ratifying edit: §0 rule 2 (and the four adapters), §1, §2B, §17, §22 status. |
| 1.2.7 | 2026-09-24 | ACTIVE — merged PR #1227 `756eb977e` 2026-09-24T21:31:15-04:00 | PATCH | §13.4 corrected to what shipped in PRs #1223/#1225/#1226 (live 2026-09-24 as `7a9dcec26`): `InstrumentRecord@v1` gains the shipped `beliefs[]` block (`InstrumentBelief@v1`, written only by `cio_belief_writer` through `apply_belief`, read by the research gate / L3 question / `default_decide`) and retires the `priors` / `scored_lessons[]` SPECIFIED lines; `last_outcome` documented as the research-gate route; subject-key namespace records `INDUSTRY:`/`THEME:` tags-only by policy (`is_mintable` → `tags_only_by_policy`) and `SECTOR:` mintable-with-no-producer; narrative-subject table gains `OPTION_CONTRACT` (a `security_guid`, `share_class="option"`, no options id prefix; `expiration_guid`/`strike_guid` not minted). Lanes `commitment-outcome-sweep` (18:20) and `instrument-belief-writer` (18:50) installed under an operator cron grant and declared ACTIVE. No rule added, nothing weakened; §0/§2/§17 untouched. | Rides `APPROVE_AGENTS_POLICY_1_2_0` (sections outside §0/§2/§17) |
| 1.2.6 | 2026-09-20 | ACTIVE — merged PR #1145 2026-09-20T15:13:47-04:00 (amended by PR #1153, 19:18:34-04:00, no bump) | MINOR | §6: a dry run must not be able to REACH the mutation — `--dry-run` called `claim_due()` and stranded the row it previewed (PR #1143) — and anything that claims work owes a reclaimer. §12: `should_scheduled_skip` superseded by `lib/llm_deferral`; out-of-window paid work is queued in `llm_deferred_requests` and drained by lane `llm-deferred-drain`; three operator-set caller tiers; `LLM_DEFER_OFFPEAK` arming; measured 21% (965/4,590) blast radius of arming globally (PR #1134), and records that the process-boundary wrapper (25 active crontab lines) still DROPS. §9.3: a refused scheduled call is queued not dropped; `llm-deferred-drain` and `llm-provider-health` declared. No change to §0, §2, §17 or role authority. **Amendment (PR #1153, same version):** Research lanes + §13.4 dark list: `hermes_advisory_event_enqueue` → **RETIRED** after Operator-Token `APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE` (PR #1151) and follow-on `lane_registry` row `hermes-advisory-event-enqueue` (EXPECTED_SILENT; manual CLI retained; no archive). No change to §0, §2, §17 or role authority. | **Operator-directed** 2026-09-20 ("update documentation agents.md"). MINOR — adds proof obligations, weakens nothing; rides `APPROVE_AGENTS_POLICY_1_2_0`. |
| 1.2.5 | 2026-09-20 | ACTIVE | PATCH | §13.4: dark-contracts list + AgentView/AGENT_COMMITMENT “no producer” prose corrected to match ledger CLOSED (load-by-subject, OUTCOME, AgentView, commitment, librarian index OBSERVED). hermes enqueue remains KNOWN DARK — PROPOSED RETIRE. No change to §0, §2, §17 or role authority. | PATCH stale measurements; rides `APPROVE_AGENTS_POLICY_1_2_0`. |
| 1.2.4 | 2026-09-18 | ACTIVE | PATCH | §10: default `TRADEAI_CURRENT_BOUND_UNITS` documents `cio-governed-bridge.service` beside the health agent; cites 2026-09-18 bridge vs portfolio-server pin drift and `docs/ops/BRIDGE_PIN_ALIGNMENT.md`. No change to §0, §2, §17 or role authority. | PATCH documentation of deploy default; rides `APPROVE_AGENTS_POLICY_1_2_0`. |
| 1.2.3 | 2026-09-18 | ACTIVE | MINOR | Adds "What 2026-09-18 taught — Agent controls audit" (router `WRITE_WORDS` miss buy/sell/order; BehaviorWriteRefused ≠ router HITL; prompt-injection PARTIAL on Telegram/watchlist/router ingress despite admission/partition/MCP probes; failed oneshot+timer churn especially `tradeai-cio-reactive` */2m; alert `runtime_mode` measured SHADOW not OFF; grounding 0%-flag caution; RAG empty-vs-cited verify). Does not touch §0, §2, §17 or role authority. | **Operator-directed** 2026-09-18 ("read update agents.md" after agent-controls audit). **ACTIVE** on operator-directed merge/promote of PR #1069 (2026-09-18). |
| 1.2.2 | 2026-09-18 | ACTIVE on main (not yet on CURRENT) | MINOR | Adds "What 2026-09-18 taught — Postgres ENOSPC → Command Center false-green" (symptoms, ordered root cause, immediate + lasting fix, verify commands). Records that `/api/health` ok is not Postgres liveness; hygiene reclaim does not restart `postgresql@17-main`; PARTIAL `primary(0) vs alternate(N)` after an outage is honesty until scans refill; watchdog + sudoers must cover `/usr/bin/systemctl`; health-agent cannot auto-start Postgres under `NoNewPrivileges`. Does not touch §0, §2, §17 or role authority. | **Operator-directed** 2026-09-18 ("also update the agents.md with root cause fix and symptoms"). **Merged** PR #1068 2026-09-18; **live CURRENT still serves 1.2.1** until explicit promote. |
| 1.2.1 | 2026-09-16 | ACTIVE | PATCH | Corrections only, no rule change. §7 "Research and operator replies" corrected: "Brave spills to SearXNG only on quota or rate limit" was factually incomplete after PR #1045 — `CALLER_DAILY_CAP` remains out of `spill_on` (operator decision 2026-09-13), but a caller refused by it is now answered by a separate governed free call (`scripts/lib/free_search.py`, behind `RESEARCH_FREE_FALLBACK=1`), not a spill. §12 gains a `[VERIFIED]` 2026-09-16 note recording the first measured free-web result and that free usage is now metered in the same ledger as paid. Adds no restriction and weakens nothing; does not touch §0, §2, §17 or role authority. | **Operator-directed** 2026-09-16 ("make sure that if the agents.md needs to be updated it's updated ... add was validated"). PATCH corrections outside the operator-gated sections; rides the existing `APPROVE_AGENTS_POLICY_1_2_0` ratification. |
| 1.2.0 | 2026-09-14 | ACTIVE — ratified 2026-09-14 (`APPROVE_AGENTS_POLICY_1_2_0 1022 ad5c533b2abc0150feba19c071aa0ea56364b251`) | MAJOR | One version, one activation event (the ratification). Constituent changes, in the order recorded: (2026-09-14, MINOR) §9.1 gains "Replies and alerts on the phone" (4,096 UTF-16 parts, `REPLY_NOT_DELIVERED`, one rich layout, collapsed provenance). §9.2 gains: every bridge caller names itself; the bridge answers while calls are in flight (deadline, slots, `/health`, watchdog); stalls are diagnosed at the bridge first; logged cost is checked against the provider balance. §9.3 gains the operator's scheduled-work window and "a backfill is scheduled work". §7 gains six tooling traps (CRLF via `read_text`, JSON re-dump escaping, `sys.modules` stubs, worktree data, docs index after merge, SOP bound files). §12 re-verifies DeepSeek prices (flash repriced 2026-09-10), records that the Pro policy binds to deepseek-flash, and adds the binding operator window. Records merged work from PRs #1011–#1019 and the scheduling/attribution PRs; does not touch §0, §2, §17 or role authority. · (2026-09-14, MINOR) §12 records the operator's new daily provider spend cap, **$2.00/day of actual spend** (was $0.50), with the measured enforcement footprint (6 crontab lines, host cap file, unit drop-ins). Still policy rather than a universally enforced control. Does not touch §0, §2, §17 or role authority. · (2026-09-13, MINOR) §7 gains "Operator replies, data gaps and agent numbers" (one reply chokepoint, house facts first, subject resolution, checked summaries, promise only what is queued, resolved means proven, rule G0, GUID-keyed memory) and two traps (duplicate `def` names; stored results lack the prompt). §9.3 gains "a crontab line edit is a lane registry edit". §10 gains the Telegram bot restart and "a deploy does not install new user units". Records merged work from PRs #992, #998–#1001; does not touch §0, §2, §17 or role authority. · (2026-09-13, MAJOR) §7A gains "Ownership and the grant" and rule 7; §17 gains **adding, replacing or retiring a data source or a writer of an authoritative store**. Registry schema `DataSourceAuthority@v2` requires an `approval` record on every provider and domain; `check_data_source_authority.py` fails an ungranted source (`UNAPPROVED_SOURCE`). Classified MAJOR because it widens §17 (version policy) — it adds a restriction and weakens nothing. Version number left at the unreleased 1.2.0 PROPOSED; whether the widening makes the release 2.0.0 is the operator's call at ratification. · (2026-09-09, MINOR) Adds §9.1 rule: `settle_delivery` must stamp `delivery_owner`/`gateway_mode` into `provider_coordinates` (PR #926). Does not activate 1.2.0; does not weaken §0/§2/§17. · (2026-09-03, MINOR) Multi-Agent SOP controls plus the operator-approval workflow for guarded remote push and live deployment. Does not weaken §0/§2/§17 or financial rails. | **RATIFIED** by the operator 2026-09-14: "APPROVE_AGENTS_POLICY_1_2_0" (sent without PR/sha; bound to `APPROVE_AGENTS_POLICY_1_2_0 1022 ad5c533b2abc0150feba19c071aa0ea56364b251`) |
| 1.1.0 | 2026-09-01 | ACTIVE | MINOR | Records the ratified daily provider spend cap ($0.50) in §12, with measured evidence that it binds on 6 of ~84 LLM lanes and is therefore policy rather than a universally enforced control. | **RATIFIED** by the operator, 2026-09-01 |
| 1.0.0 | 2026-09-01 | ACTIVE | MAJOR | Formal baseline. Document-control block and version policy; §13.5 duplicate merged; §13.6 numbering collision renumbered to §13.7 and section order restored; two "Where things go" tables merged; §2B role authority profiles added. | **APPROVED** — `APPROVE_AGENTS_POLICY_1_0_0 841 0f00f928a6b3892ef838c8737cebfcb622fd53ae` |

**Why MAJOR.** §2B adds role authority profiles, which is authority semantics. The deduplication
alone would have been PATCH; the higher class wins, per the version policy above.

**No prior version to supersede.** `Policy-Version:` appeared zero times in this file before
1.0.0, measured on `origin/main` at the base of this change.

- **`gog drive upload --dry-run` uploads anyway** (gog v0.12.0, observed 2026-09-14). Never use it as a dry run; search the destination folder first and upload once.

## Version banners (moved here from the top of the file by 25.0.0; history, not binding)

**26.2.2 is ACTIVE (PATCH) — generated §7A source-of-truth table refreshed.** The two conflict-engine domains
`conflict_ledger` and `conflict_rule_proposals` were granted by the operator (§7A/§26.6, in-session 2026-10-29) and the
generated source-of-truth table in §7A now lists them as active; no rule-text change. Supersedes 26.2.1. *(moved here by 29.0.0)*

**26.1.0 is PROPOSED (MAJOR) — approved work pushes itself; "designed" = a task id; emergency merge/deploy bypasses
Mergify.** Awaiting `APPROVE_AGENTS_POLICY_26_1_0 <pr> <head_sha>` (§20). (1) §0 rule 4 / §28.15 item 8: an
operator-approved scope is the push authorization — no separate `git-push` grant for an approved-scope fast-forward
push of the agent's own non-`main` branch; budget and never-`main`/`release/*` still bind. (2) §28.3b: each buildable
unit is a registered task id, never prose. (3) §25.10 / §17: held PRs merge on the operator's per-PR tap (never
GitHub), and operator-initiated emergency merge/merge-and-deploy bypasses Mergify, SHA-bound; broker rails are never
bypassed. **Why MAJOR:** edits §0 rule 4 and widens merge/deploy authority. §2, §2A, §7A, §23.14 and the
broker/order/stop/sizing/secret rails are unchanged; `MBI_BEHAVIOR = 0`. Details: LESSONS L28-29/L28-30/L25-07; named
debt OI-131/133/134. *(moved here by 29.0.0; 26.1.0 was never ratified)*

**26.2.1 is ACTIVE (PATCH) — ratification of 26.2.0 (operator-delegated promote).** 26.2.0 was merged as
PROPOSED (a defect: the ratifying commit was not pushed before the operator's `--admin` merge, LESSONS L0-01/L0-02);
this PATCH is the §20 ratifying edit — header `Status: PROPOSED → ACTIVE`, `Effective-Date: 2026-10-29`, banner and
history row — with **no rule-text change**. Ratified by the operator
(`APPROVE_AGENTS_POLICY_26_2_0 2292 82259827cb7c35d75bef4c743995c188f734e5f7`), superseding 26.1.0. Adds §25.10.1: an agent hands the operator the exact deploy commands (already the rule, §28.4 — stated
explicitly, not new), and may run the promote (`scripts/emergency_manual_promote.sh` or
`scripts/cio_phase2_exact_main_deploy.sh` `prepare`+`promote`) on the operator's behalf after it presents the exact
command, the full 40-hex SHA and the dry-run output, and the operator types an explicit approval in that agent's own
session (§28.4). Adds §25.10.2: a lane, scheduled job or dispatcher row an agent built may be turned on live and
tested on the operator's in-session approval. **Why MAJOR (for 26.2.0):** widens deploy (promote) and §17 scheduling authority.
§0 rules 1–2 and §24.7 are never
overridable, even by the operator; the delegation never extends to pushing `main`/`release/*`, merging,
broker/order/stop/sizing/secret actions, arming/disarming the delegation, or clearing STOP; `ReleaseGrantBinding@v1`,
the STOP latch, `GlobalReleaseLock` and operator-set `TRADEAI_EMERGENCY_RELEASE_SHA` are unchanged. *(moved here by 29.0.0)*

**26.0.0 is ACTIVE (MAJOR) — consolidation.** Ratified 2026-10-28 by the operator
(`APPROVE_AGENTS_POLICY_26_0_0 2256 266f936f70b58db890ceccef2a413a22470200da`).
 Every rule that was true in 25.0.1 is kept, stated once. History,
incident narratives, measurements and open gaps moved out to `docs/governance/` (AGENTS_HISTORY.md,
LESSONS_LEARNED.md, OPEN_ITEMS.md); reference material moved to the document that owns its subject. Contradictions
were settled in favour of what the code does and what the operator ratified (the 2026-10-27 governance review).
**Why MAJOR:** it rewrites §0 rules 2, 4 and 6 (conditions on versions long ACTIVE removed; the push rule matched to
the hook), consolidates §17, aligns §2B and §22 with §25.10, and records the operator's 2026-10-26 ratification of
23.0.0 (Telegram remote grants retired). It also adds the operator's 2026-10-27 mandate that every PR explains
itself in plain English (§28.12). No rail is weakened: §0 rules 2 and 6 lose only dead conditions, rule 3 changes only a citation, rules 1, 5 and
7–11 are unchanged, and §2, §2A's "never leaves this
box" list, §7A, §23.14 and the broker, order, stop, sizing and secret rails keep their meaning; `MBI_BEHAVIOR = 0`.
Operator instruction, 2026-10-27, verbatim: "I want all of your recommendations done … I need to make sure that all
of the other documents are also in line." The complete 25.0.1 text is preserved byte-exact at
`tests/fixtures/agents_pre_26_0_0/AGENTS.md`; `docs/governance/AGENTS_HISTORY.md` maps every passage that left. *(moved here by 28.0.0)*

The 17.0.0 and 22.0.0 banners are not kept: the release train was retired 2026-10-27 by the operator and replaced by
§25.10. Their history rows remain above.

**4.4.0 is ACTIVE (MAJOR) — the R1 shadow and canary rows may be cron rows (§23.11, §23.18 (c)).**
Ratified by the operator 2026-10-10 (`APPROVE_AGENTS_POLICY_4_4_0 1660 463535dfe`, §20; PR #1660 comment
2026-10-10T20:04:37Z); merged #1660 as `40e445d79`. `scripts/lib/lane_dispatch.py`
`R1_SHADOW_SHAPE_STATUS` reads `ACTIVE`. It changes one condition of the R1 gate. While its
cron line is live, an R1 lane may use the row shape the shadow wave already uses:
`scheduler.kind = "cron"`. At `shadow` the row has `scheduler.stage = "shadow"`, a `dispatch` block in
mode `dry_run` and an allowlist `live_arg` of null. At `canary` (operator ruling 2026-10-10 ~14:00 ET)
it has `scheduler.stage = "canary"`, a `dispatch` block in mode `live`, an allowlist `live_arg` that is
set, and an allowlist `flock` lock equal to the cron line's lock. Cutover keeps the dispatcher row.
Every other R1 condition, §23.14 and the allowlist `never`
entries for broker, order, stop, paper, sender, secret, guard and daemon lanes are unchanged. It also
fixes the dispatcher's name: `dispatcher` is the row expression, and `tradeai-dispatcher` is the
workflow id, which is refused as an expression. MAJOR because it widens the R1 admission (version
policy: classify by the weakest guarantee); nothing in §0, §2, §2A, §7A or §17 changes.

**4.0.0 is ACTIVE (MAJOR) — one named n8n live-lane exception: `trade-ai-scalp-live` (§23.3).**
Ratified by the operator 2026-10-09 15:25 ET in session (`APPROVE_AGENTS_POLICY_4_0_0`, verbatim:
"APPROVE_AGENTS_POLICY_4_0_0 and build the finviz API fix"; §20), after the operator decision of the
same day "n8n drives a governed lane (Recommended)". The 5-minute Trade-AI scalp scan — a Finviz
ingest through the data broker, a `trade_ai_scans` writer and a `send_telegram` caller — may run in
`live` mode from n8n under the conditions in §23.3; it is the only such lane, and the never-list
is otherwise unchanged. MAJOR because it widens what the n8n actor may cause (version policy).

**4.6.0 is ACTIVE (MINOR) — platform rules from the 2026-10-10 consolidation (§24).** Ratified by the operator
2026-10-10 (`APPROVE_AGENTS_POLICY_4_6_0 1682 9dd9e7d6b`, §20; PR #1682 comment by PatsKiller 2026-10-11T02:58:29Z);
merged #1682 as `694350602`. §24
records nine operator rulings and findings of 2026-10-10: notifications — n8n orchestrates, the host communications
gateway is the only sender, the P1 path does not depend on n8n, senders emit notification intents (§24.1); search
source routing — free lane first, paid Brave only on measured insufficiency, inside a dollar budget of $20/month
account cap, $18 local ceiling, $15 target, $12 non-priority stop, with scalps about to fire first (§24.2); the data
broker — owner lanes write, consumers read projections, lane-script direct reads become a checked violation (§24.3);
other applications on this host (NYC DOF) are not Trade AI lanes and never use Trade AI resources (§24.4); no push,
PR or remote write from a scheduled job (§24.5); tests never touch production state (§24.6); agents never read, copy
or symlink `.env` or credential files (§24.7); a release grant names the SHA or PR it releases (§24.8); designs stay
Supabase- and n8n-Cloud-portable (§24.9). It also corrects the §12 `braveapi` engine row in place. **Why MINOR:**
every item adds an obligation or a restriction; nothing widens n8n, broker, egress, §17 or role authority, and §0,
§2, §2A, §7A, §17 and §23.14 are byte-identical (version policy; precedent: the §12 spend-cap change was recorded
MINOR inside 1.2.0). Two items could be read higher, and are written so they are not: in §24.1 "n8n orchestrates"
means it fires the host routing, digest, escalation and callback lanes through §23.3 and §23.11 exactly as today and
decides nothing; §24.4 is a scope boundary that only restricts — Trade AI resources never serve another application,
and §0 and the §17 host crontab, systemd and compose decisions still bind every agent for every application. If the
operator reads either as MAJOR, the number becomes 5.0.0 and nothing else changes. **Numbering dependency:**
numbered 4.6.0 because 4.4.1 (PATCH) and 4.5.0 (MINOR, §23.19) merged in PR #1666 (`dd8f4cff1`), and 4.5.0 is
ACTIVE: ratified `APPROVE_AGENTS_POLICY_4_5_0 1666 987bf94da`, ratification edit `316700266`, merged into this
branch. `Supersedes` is 4.5.0. If the number has to change, it is settled at ratification (§20): §24 keeps its
number and every `4.6.0` / `4_6_0` token in this file and its test is renamed. Operator approval phrase (§20), as
proposed: `APPROVE_AGENTS_POLICY_4_6_0 <pr_number> <head_sha>`.

**5.0.0 is ACTIVE (MAJOR) — broker-adjacent daemon operations under a per-incident `execution-ops` grant
(§24.10; one sentence added to §0 rule 2).** Ratified by the operator 2026-10-11 (`APPROVE_AGENTS_POLICY_5_0_0 1686
d51b6c50e`, §20; PR #1686 comment by PatsKiller 2026-10-11T12:33:56Z); merged #1686 as `0ec320486`; ratification
edit on the operator's in-session word 2026-10-11 ~08:40 ET ("ratify 5.0.0"). The added §0 sentence now binds. With an active
`execution-ops` grant naming the unit, the actions and the incident (≤ 6 h, grantable at the keyboard or by Telegram
`/approve`), an agent may inspect that unit's status and journal, re-point its code root to `portfolio-server/CURRENT`
by drop-in, `daemon-reload` and restart it, and handle its enable flag only when that flag is under the operator's
home — only while the market calendar says CLOSED, after a quoted preflight (the unit's tests pass at CURRENT, no store
path moves), with rollback by restoring the archived drop-in. Never its code, a credential, a live/paper flag, an order
or stop path, or a broker call. **Why MAJOR, and why 5.0.0 rather than the requested 4.7.0:** the operator asked for
"4.7.0 (MINOR)". The version policy names authority rails and broker access as MAJOR, makes any §0 change
operator-approved, says a rule that removes a restriction elsewhere is not MINOR, and gives an ambiguous change the
higher class. The sentence narrows §0 rule 2's "do not modify, test against or investigate it" for one operational
purpose, so the weakest guarantee after the change is weaker: MAJOR, so the number is 5.0.0. If the operator rules it
MINOR, it renumbers to 4.7.0 and nothing else changes. **Numbering dependency:** stacked on 4.6.0 (PR #1682, merged
`694350602`; ratified `APPROVE_AGENTS_POLICY_4_6_0 1682 9dd9e7d6b`, ratification edit `01736b9d7`, PR #1687) and after
4.4.1 / 4.5.0 (PR #1666, merged; 4.5.0 ACTIVE); `Supersedes` is the last ACTIVE version, 4.6.0. 4.6.0 has its own
token, and ratifying 5.0.0 does not ratify 4.6.0: merge 4.6.0 first. The guard scope is installed separately, by the operator
(`~/n8n-maturity-verification/packets/agents-4-7-0/`). Operator approval phrase (§20):
`APPROVE_AGENTS_POLICY_5_0_0 <pr_number> <head_sha>`.

**5.1.0 is ACTIVE (MINOR) — operator-action messages are P1 notification intents with dedupe off;
`bypass_router=True` is legacy, allowlisted and shrink-only (§9.1).** Ratified by the operator 2026-10-11
(`APPROVE_AGENTS_POLICY_5_1_0 1689 b0f0c6eeb`, §20; PR #1689 comment by PatsKiller 2026-10-11T13:12:31Z); merged #1689 as
`26cf80f60`; ratification edit on the operator's in-session word 2026-10-11 ("yes - ratify 5.1.0"). Approval phrase as
proposed: `APPROVE_AGENTS_POLICY_5_1_0 <pr_number> <head_sha>`. §9.1 said anything the operator must act on bypasses the router (`bypass_router=True`). PR
#1685 (`n8nmat/bypass-senders-to-intents`, head `1d9eba216`, held for this amendment) moves 25 bypass senders to
notification intents, which §24.1 (4.6.0) already requires of a changed sender. Under 5.1.0 an operator-action
message is a P1 intent with dedupe off: never capped, quiet-held, archived or suppressed, and receipted.
`bypass_router=True` stays only on allowlisted legacy sites (`tests/test_notification_intents_20261010.py`), and the
allowlist only shrinks. The four broker-execution sender units — `alpaca_stop_manager.py` (two sites),
`defense_execution.py`, `moomoo/opend_health.py` — keep their bypass until an `execution-engineering` grant migrates
them (§0 rule 2). A P2 intent is held 22:00–07:00 ET to the Reports archive and folded into the advice digest; a hold
that cannot be archived is delivered. **Why MINOR:** it replaces a mechanism and keeps the guarantee. Everything
`bypass_router=True` gave an operator-action message — not text-classified, not capped, not held, not suppressed — a
P1 intent with dedupe off also gives, and it adds a durable receipt for every route decision. For every other sender
the change adds what §9.1's first bullet already demands (a content dedupe key with a declared window); §9.1 never
promised informational sends immediate delivery, and a held P2 still reaches a surface (the advice digest) and is
never dropped. No operator-only boundary, authority rail, role, broker reach or egress changes; §0, §2, §2A, §7A,
§17 and §23.14 are byte-identical, and no adapter changes. The class could be read higher in one place, the P2 hold
(an informational send that was immediate can now arrive in the morning digest), and is written so it is not: §9.1
now requires anything that must reach the operator inside the quiet window to be P1. If the operator reads it as
MAJOR, the number becomes 6.0.0 and nothing else changes. **Merge order:** PR #1685 first. The rule names code that
only #1685 brings (`telegram_alert_router.route_intent`, the allowlist test); merged before it, the 25 senders would
still bypass with no allowlist holding them. **Open item for #1685:** under the §9.1 definition, a P1 sender that
asks the operator to decide needs `dedupe_minutes=0`; #1685 sets it only for `approval_package_reminder.py`, and
`stop_decision_brief.py` (a stop decision brief) is P1 with the default 60-minute exact-content dedupe — the
operator classifies it before #1685 merges. **Numbering:** follows 5.0.0 (ACTIVE, PR #1686, merged `0ec320486`);
`Supersedes` is 5.0.0. Operator approval phrase (§20): `APPROVE_AGENTS_POLICY_5_1_0 <pr_number> <head_sha>`.

**24.0.0 is ACTIVE (MAJOR) — Mergify merges; host `deploy_on_main` promotes; emergency is operator CLI + `release-write` (§25.10).**
Ratified by the operator 2026-10-26 in session (approved AGENTS 24.0.0 PROPOSED, then directed full cutover: install,
configure, commit the approval policy; `APPROVE_AGENTS_POLICY_24_0_0` to be bound to the cutover PR head on open, §20).
Mergify owns scheduled merge of green PRs; a thin host poller promotes exact `origin/main` SHAs under STOP +
GlobalReleaseLock + a standing **deploy** (promote-only) delegation; emergency promote is host CLI only with
`release-write` naming the SHA and `TRADEAI_EMERGENCY_RELEASE_SHA`. Agents remain PR-only. Retires the custom train
live merge/`train/*` push path, Ops → Controls **Run now**, and the train UI.
**Why MAJOR:** it replaces the 17.0.0 release-train merge actor and widens §17 (Mergify install, deploy-delegation arming,
emergency SHA promote). Numbered 24.0.0 after ACTIVE 22.0.0 (PR #2149); 23.x is reserved. §0, §2, §2A, §7A, §22 and §23.14
stay byte-identical. Foundation: `docs/ops/MERGIFY_DEPLOY_FOUNDATION.md`.

**21.0.0 is ACTIVE (MAJOR) — §28.13 design lifecycle, §28.14 self-heal monitor and fixer, §28.15 hands-off delivery.**
Ratified by the operator 2026-10-25 (`APPROVE_AGENTS_POLICY_21_0_0 2128 f8a89dc6b568406a3e7662e04fae9ef31fe559c3`, §20; PR #2128 comment by PatsKiller 2026-10-25T20:33:01Z, https://github.com/PatsKiller/tardeai/pull/2128#issuecomment-6402870834).
Designs live in `design/` with versioned pages and one-tap operator approval; a host-timer monitor and the self-heal
fixer correct small errors through ordinary PRs; an approved scope ships through solo trains without the operator, and
what still reaches the operator is the list in §28.15 item 9. MAJOR: it widens §17 and the §25.2 delegation; §0 text,
§2, §2A, §23.14 and the four adapters unchanged.

**20.3.0 is ACTIVE (MINOR) — §28.12 delivery lifecycle, claim to verified release.**
Ratified by the operator 2026-10-25 (`APPROVE_AGENTS_POLICY_20_3_0 2107 72bd48f46d3557501b3575002e741577ffff90f0`, §20; PR #2107 comment by PatsKiller 2026-10-25T17:17:38Z, https://github.com/PatsKiller/tardeai/pull/2107#issuecomment-6400701124).
One ordered path for every agent: claim, design, build, test, PR, CI green, queue, release; plus two obligations —
post-release verification after every release (`scripts/post_release_tester.py`) and immediate P1 failure paging by
Telegram, email and SMS (`scripts/delivery_failure_alerts.py`). Adds obligations only; §0, §2, §17 and role authority
unchanged.

**20.2.0 is ACTIVE (MINOR) — §28.9 lessons of 2026-10-23/24 and §28.10 one conflict engine under one rulebook.**
Ratified by the operator 2026-10-24 (`APPROVE_AGENTS_POLICY_20_2_0 2073 c17951846b3bd688a6ef1c082d208ae4970445fc`, §20; operator typed the token 2026-10-24 ~20:25 ET after reading PR #2073).
Adds restrictions only: no silent removal from operator surfaces; `[shared-infra]` PRs alone with real-layout proof; one
source per fact owned by the CIO record; health means the job ran; a read never acts; every writer a monitored n8n lane;
conflicts evaluated only by `scripts/lib/conflicts` under `config/conflict_rulebook.json`, the CIO always informed. §0, §2,
§17 and role authority unchanged.

**20.1.0 is ACTIVE (MINOR) — agent UI and validation traffic never targets the live server during market
hours (§28.8).** Operator decision 2026-10-23 ~11:05 ET, "approved", on the rule after five portfolio-server
SIGKILLs between 09:14 and 10:24 ET that agent crawls and previews drove (PR #2012). Between 04:00 and 16:15
America/New_York on a market day no agent sends Playwright, crawler, `vite preview` or dev-proxy traffic to the
served `/api` on `127.0.0.1:7777`; agents validate with fixtures or a mock or replay backend, and a live smoke check
runs after the close at no more than 1 request per second, GET only. **Why MINOR:** it adds one restriction and
removes none; no agent gains a permission and no guarantee weakens. **Byte-identical:** every section other than
§28.8, this banner, the header block and the 20.1.0 history row is byte-identical to 20.0.0, before and after
ratification; the ratifying edit changes only the header, this banner, the §28.8 status line and the row.
**Numbering:** after 20.0.0 (PR #2013, ACTIVE); `Supersedes` 20.0.0. Ratified by the operator 2026-10-23 (`APPROVE_AGENTS_POLICY_20_1_0 2019 d24a29054865a9bc09d3c50bb33dfe9c4be728af`, §20; PR #2019 comment by PatsKiller 2026-10-23T16:53:47Z, https://github.com/PatsKiller/tardeai/pull/2019#issuecomment-6370144385, verbatim: "APPROVE_AGENTS_POLICY_20_1_0 2019 d24a29054865a9bc09d3c50bb33dfe9c4be728af"); ratified by this edit, which set the header block
to 20.1.0 ACTIVE and §28.8 to ACTIVE, and changed nothing else. Approval phrase as proposed:
`APPROVE_AGENTS_POLICY_20_1_0 <pr_number> <head_sha>`.

**20.0.0 is ACTIVE (MAJOR) — agent operations and the read-only broker baseline (§28).** Operator decisions
2026-10-22, verbatim: "So can we do A through E? Is there any problem?", "approve sudo window", and "yes i approve
“approve all” (A–L)", covering the host `/tmp` hygiene lanes, measured caps and receipts for the automations that
end or rewrite a run (§28.1), agent temp discipline (§28.2), multi-vendor coordination and the claim board (§28.3),
approval provenance (§28.4), the Ops → Controls sudo window (§28.5), the read-only Schwab baseline (§28.6), the
installed release-train claimer, two stale references, §0 rule 11 "Claim, log, hand off", how any agent picks up work (§28.3a) and
design, phase and task ids (§28.3b) (operator 2026-10-23:
"We shouldn't lose anything just because different developers or agents working on it."). These were approved as a "19.1.0"; the version policy
numbers them 20.0.0 (§0 rule 10). Ratified by the operator 2026-10-23 (`APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497d5d63a49f08aad247f194f884a8030b1`, §20; PR #2013 comment by PatsKiller 2026-10-23T14:42:00Z, https://github.com/PatsKiller/tardeai/pull/2013#issuecomment-6367515961, verbatim: "APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497d5d63a49f08aad247f194f884a8030b1"); ratified by this edit, which set the header block
to 20.0.0 ACTIVE and made the nine clause edits quoted in §28.7. **Why MAJOR:** it narrows §0 rule 6 "Never delete" for
a second set of lanes (the host `/tmp` hygiene timers), and it relaxes §27.3's one passkey assertion per risky act
with a bounded sudo window; each removes a restriction, and a change that removes a restriction is classed by the
weakest guarantee after it (precedents 5.0.0, 14.0.0 and 15.0.0, each narrowing §0). It cannot be MINOR. Every rule
binds Claude, Codex/OpenAI, Cursor and any other agent equally; no agent outranks another. Ratification arms nothing
that is not already served: the sudo window ships behind `ops_controls.sudo_window_enabled` (default off), and claim
checks stay WARN-only until `scripts/agent_claim.py` and its pre-commit gate are on main. **Byte-identical:** §2A, §7A, §22,
§23 and §26; while PROPOSED §0, §2, §7, §13, §17, §24, §25, §27 and the four adapters are byte-identical too, and the
ratifying edit makes exactly the nine clause edits quoted in §28.7. **Numbering:** after 19.0.0 (PR #1962, ACTIVE);
`Supersedes` 19.0.0. Approval phrase as proposed: `APPROVE_AGENTS_POLICY_20_0_0 <pr_number> <head_sha>`.

**19.0.0 is ACTIVE (MAJOR) — n8n may schedule the audited read-only broker lanes (§27.1), and the operator's
Ops → Controls surface: the safe direction is one click, the risky direction a passkey plus a typed phrase
(§27.2–§27.3).** Operator decisions 2026-10-22, verbatim: "N8N can read the broker because right now we're only doing
reading of the broker. We're not doing any trading. So I want to amendment." and "yes on passkey"; the operator chose
("yes") that these rule changes ship as a diff the operator applies and commits. Ratified by the operator 2026-10-22 (`APPROVE_AGENTS_POLICY_19_0_0 1962 bb54a14a89347a1c17dd0d326b0720c882bbd61f`, §20; PR #1962 comment by PatsKiller 2026-10-22T22:10:31Z, https://github.com/PatsKiller/tardeai/pull/1962#issuecomment-6352416425, verbatim: "APPROVE_AGENTS_POLICY_19_0_0 1962 bb54a14a89347a1c17dd0d326b0720c882bbd61f"); ratified by this edit, which set the header block to 19.0.0 ACTIVE, made the four clause edits quoted in §27.5 and set `CARVEOUT_STATUS` to `ACTIVE`. Under 19.0.0 n8n may schedule and trigger only the closed set of read lanes in
`scripts/lib/n8n_broker_read_carveout.py` (the §24.11 steps
and market-data reads that pass the same audit), executed on the host through the allowlisted executor, only while
every broker trading lock is LOCKED and the Schwab access mode is `read_only`, with no credential in n8n; orders, stop
writes, cancel, replace, preflight, 2FA, `place_order`, live and paper flags and senders stay on the §23.14
never-list. Operator settings live in a Postgres `operator_settings` table with history (a proposed §26 registry
row); one governed host applier with backup, audit and undo changes the crontab, the n8n live list, settings and
grants; release-train STOP or pause and kill-switch ENGAGE are one click; arming, resuming or rescoping the train,
clearing the kill switch, resuming broker jobs, n8n live-list changes and grants need a WebAuthn passkey (several
named devices, each revocable) and a typed phrase; TOTP is recovery only and Telegram notification only. This
supersedes decision D3 (2026-10-21) and the kill switch's terminal-only clear; the host terminal stays the fallback;
agents never call the Controls endpoints. **Why MAJOR:** it gives an automated actor broker reach §23.14 forbade
(n8n triggering broker reads) and changes how operator-only (§17) acts are made (a web surface with a passkey
replaces D3's host CLI or Telegram confirmation); broker access and operator-only boundaries are MAJOR by the version
policy, and a change that removes a restriction is classed by the weakest guarantee after it (precedents 12.0.0,
14.0.0, 17.0.0). It cannot be MINOR. Ratification arms nothing: no lane, allowlist entry, dispatcher row, table,
endpoint or passkey exists until its own reviewed PR and §17 grant. **Byte-identical:** §0, §2, §2A, §7A, §22, §24,
§26 and the four adapters; while PROPOSED §17, §23.14 and §25 are byte-identical too, and the ratifying edit changes
exactly the clauses quoted in §27.5. **Numbering:** after 18.0.0 (PR #1931, ACTIVE); `Supersedes` 18.0.0. Approval
phrase as proposed: `APPROVE_AGENTS_POLICY_19_0_0 <pr_number> <head_sha>`.

**18.0.0 is ACTIVE (MAJOR) — the data foundation: one store, one writer, the CIO as integrator (§26).**
Operator direction 2026-10-22, verbatim: "The CIO agent is supposed to tie all of this together, and it should all be
in persistent memory. One data store with everything; use the CIO agent and n8n to accomplish this. This was supposed
to be the baseline of the site." and "Make sure this is the foundation of the data in the site. Make sure that this is
hard-coded in agents.md and you set the architecture of how this should work. And we should also have a data
dictionary that shows one source of data." Ratified by the operator 2026-10-22 (`APPROVE_AGENTS_POLICY_18_0_0 1931 894bbd954ca174453e7339d30157e082d4403c84`, §20; PR #1931 comment by PatsKiller 2026-10-22T16:59:09Z, https://github.com/PatsKiller/tardeai/pull/1931#issuecomment-6346416104, verbatim: "APPROVE_AGENTS_POLICY_18_0_0 1931 894bbd954ca174453e7339d30157e082d4403c84"); ratified by this edit, which set the header block to 18.0.0 ACTIVE and replaced the NO SILOS clause quoted in §26.7. Under 18.0.0 the
CIO prospect record — `InstrumentRecord@v1` extended, one row per `security_guid`, written only by
`InstrumentRecordStore` — is the single per-security truth; every fact has exactly one authoritative store and one
writer in the §7A registry, and the data dictionary rendered from it (`docs/architecture/DATA_DICTIONARY.md`) binds
row by row as the operator grants each row; pages, APIs and alerts read only through registered projections; n8n
schedules the gathering inside the §23.14 never-list; conflicting inputs are recorded and shown, never silently
resolved; new stores and writers stay operator-only (§17); a retired copy is archived with a tripwire. **Why MAJOR:**
it changes agent role authority — no desk, lane or agent other than the CIO may keep its own per-security judgment
store, and the CIO agent becomes the only writer of the per-security record — and it changes what operator surfaces
may read (version policy: role authority is MAJOR; an ambiguous class takes the higher one). It weakens nothing and
grants nothing: no broker, order, stop, egress, n8n or §17 authority widens, `MBI_BEHAVIOR = 0` and the behaviour rail
are untouched, ratification grants none of the proposed registry rows (each is its own §17 grant), and no runtime
behaviour changes until those grants and their PRs land. If the operator rules it MINOR, it renumbers to 17.1.0 and
nothing else changes. **Byte-identical:** §0, §2, §2A, §7A, §17, §22, §23.14, §24, §25 and the four adapters; §26
extends §7A the way §24.3 does, without editing it. While PROPOSED the NO SILOS section is byte-identical too; the
ratifying edit replaces exactly one clause there (its methodology rule 1, quoted in §26.7). **Numbering:** after
17.0.0 (PR #1914, ACTIVE); `Supersedes` 17.0.0. Approval phrase as proposed:
`APPROVE_AGENTS_POLICY_18_0_0 <pr_number> <head_sha>`.

**16.0.0 is ACTIVE (MAJOR) — the n8n cutover standard: defect fixed, dry run, regression tests, one live n8n
run with the cron line present; no multi-day soak (§23.21; five clauses replaced in place by the ratifying edit).**
Rebuilt on 2026-10-21 from 8.0.0 (PR #1727, closed unratified) on the operator's word "yes rebuild 1727". Operator ruling
2026-10-14 ~11:05 ET, in session, verbatim: "new standards apply when i say so fix and dry and regression testing, yes it should run live successful to many road blocks to testing". Ratified by the operator 2026-10-21
(`APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1416ab9f240a69def0523dd125afbc18`, §20; PR #1911 comment by PatsKiller 2026-10-22T02:33:20Z,
https://github.com/PatsKiller/tardeai/pull/1911#issuecomment-6331278599, verbatim: "APPROVE_AGENTS_POLICY_16_0_0 1911 527a9bdc1416ab9f240a69def0523dd125afbc18");
ratified by this edit on #1911's branch, which set the header block to 16.0.0 ACTIVE with `Supersedes` 15.0.0 and
replaced the five clauses quoted in §23.21 "Ratifying edit" (§23.3's three clean market days for
`trade-ai-scalp-live`, §23.14's restatement, the §8.1 gate list, a §23.12 pointer, the §23.23 (4) citation);
onboarding step 8's natural shadow slot is no longer a gate. Main already depends on it: §23.23 (4) and §23.25 cite "§23.21 cutover standard", and
`scripts/n8n_cutover_wave.py` describes its waves as "§23.21: fix + dry run + regression + at least one live n8n run
with the cron line still present; no soaks". An n8n lane is ready to cut over when (1) the defect that held it is
fixed and served, (2) its n8n dry run passes (a forced `dry_run` fire counts), (3) its regression tests pass under
`TRADE_AI_CI=1`, and (4) it has at least one successful `live` n8n run with the cron line still present under the
shared lock — the dispatcher's slot, or a live fire the operator forces inside the lane's window. The cron line is
then commented, never deleted, and the commented line is the fallback. **Why MAJOR:** it removes a restriction 4.0.0
(MAJOR) set on a lane that ingests and sends, so the weakest guarantee after the change is weaker (version policy:
classify by the weakest guarantee). It grants nothing: no lane, allowlist `never` entry, grant tier or §17 item
changes, and §0, §2, §2A, §7A, §17 and §22 are byte-identical, as are the four adapters. **§23.14 changes by one
clause at ratification**, which §23.14's last bullet permits only to a new MAJOR made outside a program window; the
window closed 2026-10-12T23:59:59-04:00. **Pattern (as 14.0.0 and 15.0.0, plus the header):** the PROPOSED patch added the
banner, §23.21 and a PENDING row, and set the header block to 16.0.0 PROPOSED with `Effective-Date` PENDING; §8.1,
§23.3, §23.12, §23.14 and §23.23 stayed byte-identical until the ratifying edit, which replaced exactly the five clauses
quoted in §23.21 "Ratifying edit", whose SHA-256 digests `tests/test_agents_policy_16_0_0_cutover_standard.py` pins.
**Numbering:** 8.0.0 was never ratified and its number is retired with #1727; 15.0.0 (PR #1852) was ratified on
2026-10-21 and was the last ACTIVE version, so this takes 16.0.0. `Supersedes` is the last ACTIVE version, 15.0.0
(settled at ratification, §20). Approval phrase as proposed: `APPROVE_AGENTS_POLICY_16_0_0 <pr_number> <head_sha>`.

**15.0.0 is ACTIVE (MAJOR) — one automated deletion: the weekly n8n lane `disk-hygiene` may remove the
reclaimable items its reviewed rules select, and nothing else (§24.12; one sentence added to §0 rule 6).**
Ratified by the operator 2026-10-21 (`APPROVE_AGENTS_POLICY_15_0_0 1852 fc56728962fd51c94b3dc8cfd67e2df334eda88f`,
§20; PR #1852 comment by PatsKiller 2026-10-21T19:37:58Z, https://github.com/PatsKiller/tardeai/pull/1852#issuecomment-6324859562, verbatim:
"APPROVE_AGENTS_POLICY_15_0_0 1852 fc56728962fd51c94b3dc8cfd67e2df334eda88f"); ratified by this edit on #1852's
branch, which set the header block to 15.0.0 ACTIVE with `Supersedes` 14.0.0, inserted the §0 rule 6 sentence in
`AGENTS.md` and the four adapters, and inserted the §17 entry. Approval phrase as proposed:
`APPROVE_AGENTS_POLICY_15_0_0 <pr_number> <head_sha>`. Operator directive 2026-10-18, verbatim: "i approve automatic
deletion would need an AGENTS.md amendment". The directive approved drafting this amendment; it is not the §20 token,
which was a per-PR word because the ratifying edit changes §0 and §17. Context, measured 2026-10-18: the root disk is
at 89%, with about 100 GB in stale repository clones and worktrees and 36 GB in old releases. Only
`scripts/disk_hygiene.py` under `config/disk_hygiene_rules.json`, run by the `disk-hygiene` lane or by the operator,
may remove anything: a git clone or worktree only when it is clean, has no untracked files and no unpushed commits, is
merged into `origin/main`, is referenced by nothing and holds no process cwd, and has been idle past the rule's
threshold; a release directory only outside `CURRENT`, the previous release and the newest N. A code-enforced
never-touch list (backups, `persistent-state`, models, credentials, `.ssh`, `.config`, Docker and n8n volumes) holds
whatever the rules say; every apply re-validates a fresh manifest, respects per-run caps and writes a receipt; the
first live apply follows the operator's review of a manifest. Data, backups, database rows and credentials stay under
"Never delete". **Why MAJOR:** it narrows §0 rule 6 "Never delete" for one lane, so the weakest guarantee after the
change is weaker (version policy: classify by the weakest guarantee; precedent 5.0.0 and 14.0.0, each narrowing §0
rule 2 by one sentence). §0 changes by exactly that one sentence and §17 by one entry ("changing the disk-hygiene
rules or never-touch list"); everything else in §0, and §2, §2A, §7A and §22, is byte-identical. The script and rules
file come in their own PR (branch `feat/disk-hygiene-n8n-20261018`); ratifying 15.0.0 neither merges nor activates
it, and until it merges and its lane is allowlisted nothing is removed. **Numbering:** after 14.0.0 (ACTIVE); 12.1.0
and 13.0.0 stay PROPOSED with their own tokens, and ratifying 15.0.0 ratifies neither. `Supersedes` is the last
ACTIVE version, 14.0.0.

**14.0.0 is ACTIVE (MAJOR) — agents may run the read-only broker sync, and only it, under a `broker-read`
grant (§24.11; one sentence added to §0 rule 2).** Ratified by the operator 2026-10-16
(`APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda`, §20; PR #1838 comment by PatsKiller 2026-10-16T22:44:55Z, verbatim:
"APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda"); merged #1838 as `0c5998042` while PROPOSED, ratified by this edit,
which set the header block to 14.0.0 ACTIVE with `Supersedes` 12.0.0 and inserted the §0 rule 2 sentence in
`AGENTS.md` and the four adapters. Approval phrase as proposed: `APPROVE_AGENTS_POLICY_14_0_0 <pr_number> <head_sha>`.
Operator request 2026-10-16, verbatim: "make that bash so agents can run, make amendment, not trading just reading,
update agents.md". With an active operator `broker-read` grant, an agent may invoke `scripts/ops/broker_read_sync.sh` —
the repo form of the operator-run `~/n8n-maturity-verification/sync_all_readonly.sh`, a closed eight-step allowlist of
position and transaction reads from Schwab, Alpaca, moomoo and SnapTrade into our own stores — and nothing else that
reads a broker. It holds only while the trading lock is LOCKED, the Schwab access mode is `read_only` for the run, no
credential value enters the agent's context, no re-auth, 2FA, token refresh or flag change is reachable, and no order
route is reachable; each condition is a refusal in code and the last is pinned by CI
(`tests/test_broker_read_sync_20261016.py`). **Why MAJOR:** it narrows §0 rule 2's "No agent ever calls a live broker"
for one read-only purpose, so the weakest guarantee after the change is weaker (version policy: authority rails and
broker access are MAJOR; precedent 5.0.0). §0 changes by exactly that one sentence; everything else in §0, and §2,
§2A, §7A, §17 and §22, is byte-identical. **Numbering:** 12.1.0 is claimed by the nightly cutover controller
(`docs/ops/packets/nightly-cutover-controller-20261016/README.md`, PROPOSED MINOR) and 13.0.0 by the self-heal fixer
(PR #1830, `docs/ops/self_heal_claude_fixer.md` §9, PROPOSED); both stay PROPOSED with their own tokens, and ratifying
14.0.0 ratifies neither. If either is ratified later it takes its own row; the header only moves forward. The scope is
live once the release serving the guard carries `broker-read` (§24.11 "Open gaps").

**12.0.0 is ACTIVE (MAJOR) — the n8n cutover directive: every lane family moves to n8n except F07 daemons and
registry_systemd assets (§23.25).** Operator directive 2026-10-15 ("N8N Cutover Decision"), verbatim: "This is not a
discussion item, not a recommendation, and not a request for further analysis. It is a direct architectural decision
and implementation directive." Approved for cutover: F09, F36, F41, F06, F40, F10, F07w (monitoring independence
preserved through architecture and implementation), F37, F49, F08, F23, F33, F22 and every other non-F07 family;
deferred this iteration: F07 long-running daemons and @reboot services, and all registry_systemd assets (unchanged on
the server). **Why MAJOR:** it supersedes, for the approved families, the scheduling restriction of §23.14 and the
"P0/P1 never via n8n" placement of §24.1, and it reverses the host-side placement rationales in the inventory. It
grants nothing beyond scheduling: §0, §2, §2A, §7A, §17 and §22 are byte-identical — no agent calls a live broker,
reads a secret or sets a live flag; n8n still never holds a broker credential or calls an order route itself (it
triggers host lanes; the host executes under the trading lock and `config/schwab_access_mode.yaml`). Ratified by the
operator 2026-10-15 (`APPROVE_AGENTS_POLICY_12_0_0 1779 4aeb8cf4e`, §20; PR #1779 comment by PatsKiller 2026-10-15T21:12:48Z, verbatim: "APPROVE_AGENTS_POLICY_12_0_0 1779 4aeb8cf4e");
merged #1779 as `818d6d9c4` while PROPOSED, ratified by this edit. §23.25 binds. **Numbering:** after 11.0.0; the
ratifying edit set the header block to 12.0.0 ACTIVE with `Supersedes` 11.0.0.

**11.0.0 is ACTIVE (MAJOR) — a mandatory framework for every n8n workflow: monitoring, alerting, logging,
recovery, security and AI/LLM governance, each element with an enforceable check (§23.24).** Operator-directed
2026-10-14, in session: establish n8n as the primary orchestration and automation layer and define "a mandatory
standard framework for every n8n workflow, contract, integration and automation" covering monitoring (success,
failure, performance, capacity, dependency), alerting (failure, SLA breach, performance degradation, integration
failure, AI/LLM exception), logging (execution, error, audit, security, change), recovery (retry, circuit breakers,
fallback, dead-letter, manual recovery), security (authN, authZ, secrets, data protection, audit trails) and AI/LLM
governance (prompt management, model selection and fallback, cost and token monitoring, response validation,
hallucination controls, output guardrails, HITL escalation). Ratified by the operator 2026-10-15 (`APPROVE_AGENTS_POLICY_11_0_0 1747 89fb642cd`, §20; PR
#1747 comment by PatsKiller 2026-10-15T11:51:39Z, verbatim: "APPROVE_AGENTS_POLICY_11_0_0 1747 89fb642cd"); #1747's content merged via the merge train
#1754 as `94601ff69` while PROPOSED, ratified by this edit. §23.24 binds.
Measured against it on 2026-10-14, no active workflow is compliant in any area (16 workflows, 39% of checks partly
met; re-measured 2026-10-15 at served `5aa61048d`: 18 workflows with the fabric Run Lane and error workflow, 40%;
`docs/implementation/n8n-maturity/N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md` §4). **Why MAJOR:** once
ACTIVE it changes what may stay active — every workflow that fails the framework is remediated or archived by a
deadline, and no workflow is activated or promoted a stage without passing it — and it is the control set the
§23.23 powers (LLM steps, approvals, events) must meet before they exist. Its content adds obligations only; the
operator named the number, and an ambiguous class takes the higher one (version policy). If the operator rules it
MINOR, it renumbers to 10.1.0 and nothing else changes. It grants nothing: no node, workflow, route, credential,
broker, order, stop, secret, grant or §17 authority, and §0, §2, §2A, §7A, §17, §22, §23.14 and §23.23 are
byte-identical. **Numbering:** after 10.0.0 (ACTIVE: #1740, ratified by PR comment 2026-10-14T23:25:56Z); the ratifying
edit set the header block to 11.0.0 ACTIVE with `Supersedes` 10.0.0, the last ACTIVE version.

**10.0.0 is ACTIVE (MAJOR) — n8n becomes the automation fabric: n8n owns flow; the host owns authority,
execution and evidence (§23.23; supersedes the restrictive parts of §23.1, §23.11 and §24.1, each marked in place,
plus one route note in §23.3).** Operator-directed 2026-10-14, in session, verbatim: n8n is "a centralized,
intelligent automation fabric that provides: Workflow orchestration, Dependency management, Observability, Alerting,
Human approvals, Agent coordination, LLM integration, Event-driven automation, Operational visibility, Auditability,
Governance, Centralized controls." and "Do not tell me whether cron is a better scheduler. Tell me whether we are
building the right platform." Ratified by the operator 2026-10-14 (`APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279`, §20; PR #1736 comment by PatsKiller 2026-10-14T23:25:56Z, verbatim: "APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279"); merged #1736 as `3e9dc5e14` while PROPOSED, ratified by this edit. §23.23 binds; the restrictive parts of §23.1, §23.11 and
§24.1 are superseded as marked in place, and §23.3 carries its route note. The
architecture review of 2026-10-14 (`~/n8n-maturity-verification/arch-review-20261014/`: `EXECUTIVE_SUMMARY.md`,
`TARGET_ARCHITECTURE.md`, `DECISIONS_FOR_OPERATOR.md` decision 1) measured n8n as a one-minute clock — 16 active
workflows, all schedule-started, no sub-workflow, approval wait or AI node, successful runs not saved — because §23.1,
§23.11, §24.1 and the generator's `NODES_EXCLUDE` made the fabric impossible by construction. Under 10.0.0 n8n owns
flow: sequencing and dependencies, event triggers, retries, backoff and dead-letter decisions through a Run Lane
sub-workflow, error workflows, approval timelines, escalation timers and the invocation of LLM judgment steps. The
host keeps authority, execution and evidence: the allowlist, live/dry authority, idempotency keys, secrets, the
ledger as audit of record, and the comms chokepoint for every send. n8n never holds a broker credential or calls a
broker or order route; an n8n approval is a request, and authority is the host record. Timer-only leaf-lane
cutovers are frozen until the Run Lane sub-workflow, the async run-outcome callback and this amendment exist.
**Why MAJOR:** it widens what the n8n actor may cause — flow decisions, approval timelines, LLM judgment steps, agent
invocation, event triggers and a bounded node-enablement relaxation (version policy: classify by the weakest
guarantee). It grants no broker, order, stop, secret, grant or §17 authority to n8n or to any agent, and §0, §2, §2A,
§7A, §17, §22 and §23.14 are byte-identical. Ratification activates no node, workflow, route or credential: each is
its own reviewed PR and grant, behind the controls in §23.23. **Numbering:** 6.0.0 is claimed by PR #1697
(PROPOSED), 8.0.0 by PR #1727 (PROPOSED, §23.21) and 9.0.0 by branch `n8nmat/schwab-read-lanes-20261014` (PROPOSED,
§23.22); this takes 10.0.0 and §23.23. The ratifying edit set the header block to 10.0.0 ACTIVE with `Supersedes` 7.0.0,
the last ACTIVE version; 6.0.0, 8.0.0 and 9.0.0 remain PROPOSED, each with its own token. If an earlier number is withdrawn the number is settled at ratification
(§20). Operator approval phrase (§20): `APPROVE_AGENTS_POLICY_10_0_0 <pr_number> <head_sha>`.

**7.0.0 is ACTIVE (MAJOR) — advisory market-data lanes may run from the n8n dispatcher (§23.20; one exception
bullet in §23.3).** Operator-directed 2026-10-14, in session: "move to n8n i approve if i need to make amendment propose
its just looking at level 2 on moomoo no trading". Ratified by the operator 2026-10-14 (`APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1`, §20; PR #1725 comment by PatsKiller 2026-10-14T14:54:21Z; re-approved for the merged head after the chokepoint-exemption commit: `APPROVE_AGENTS_POLICY_7_0_0 1725 1cdcdc7e3`, PR #1725 comment by PatsKiller 2026-10-14T16:09:44Z); merged #1725 as `712478bea` (filled by a one-line amend after #1725 merges). Approval phrase as proposed:
`APPROVE_AGENTS_POLICY_7_0_0 <pr_number> <head_sha>`. `scripts/lib/lane_dispatch.py` `ADVISORY_MD_STATUS` reads
`ACTIVE`, so the gate now admits a §23.20 row that passes every condition. A lane in
the code ceiling `lane_dispatch.ADVISORY_MARKET_DATA_LANES` (`active-trader-premarket-watch`,
`finviz-momentum-scalp-early-lane`, `momentum-scalp-advisory-alerts`) becomes dispatcher-eligible only when four
conditions hold, each a code check, not judgement: (a) its broker contact is market data only — a moomoo OpenD quote
context (L2 book and tape subscriptions), never a trade context, `unlock_trade`, an order verb or an account or position
read; (b) its writes are advisory only — journals, alert rows, the PENDING `paper_trade_proposals` review queue, and no
sandbox or broker submit switch in its argv or env; (c) every send goes through the host `send_telegram` chokepoint,
with `bypass_router=True` only at a call site the 5.1.0 shrink-only allowlist already holds; (d) n8n carries no secret —
the host executor runs the lane, which reads its own environment as under cron, and its `env_names` name no broker
credential. **Why MAJOR:** it widens what the n8n actor may cause and reaches a broker data API (version policy: broker
access is MAJOR; classify by the weakest guarantee). It grants no order, stop, position, account, session or 2FA
authority, and §0, §2, §2A, §7A, §17 and §23.14 are byte-identical: like §23.18 (4.3.0) it admits a class by its own
conditions and an operator ruling, not by analogy, so every §23.14 sentence still binds every lane outside it.
**Measured by the gate on 2026-10-14:** only `active-trader-premarket-watch` passes (a). The other two reach
`account_policy.equity_for_account` (Alpaca paper `get_account`, a Schwab account read) through
`auto_proposal_generator.py`, and the early lane also reaches `proposal_paper_submitter` through the paper fast-path
hook, so they stay on cron until that read moves behind a data-broker projection. **Numbering:** 6.0.0 is claimed by
PR #1697 (PROPOSED); this takes 7.0.0 and `Supersedes` is the last ACTIVE version, 5.1.0. If #1697 is withdrawn the
number becomes 6.0.0 and nothing else changes; it is settled at ratification (§20). Operator approval phrase (§20):
`APPROVE_AGENTS_POLICY_7_0_0 <pr_number> <head_sha>`.

**5.2.0 is PROPOSED (MINOR) — "working" means validated now: tests, a dry run and a forced run; natural
schedules are monitored, never awaited (§8.1).** Awaiting the operator's
`APPROVE_AGENTS_POLICY_5_2_0 <pr_number> <head_sha>` (§20); until it is ratified and merged, nothing here binds and
the 5.1.0 text governs. Before an agent calls a build, change or install working, it quotes (1) the unit and
regression tests for what it touched under `TRADE_AI_CI=1`, (2) a dry run, and (3) a forced run — the installed job,
stage or workflow triggered on demand exactly as its schedule would trigger it, proven by a durable artifact dated
after the trigger (§0 rule 8). Natural fires are then monitored and are never the first proof; nobody waits for one.
No forced run for broker, order, stop, session or 2FA paths (§0 rule 2, §2, §22, §24.10), operator-only surfaces
(§17), or a run that would double-send to the operator; a clock-gated job's forced run goes through its wrapper and,
if deferred, the deferral receipt is the proof. A forced run of an `--apply` job needs the grant the install needed,
an overlapping natural fire must skip on its lock or run harmlessly, and the forced run is recorded in the change
record. One-line pointers in §6, §8, §9.3, §16, §23.12 and §23.19; `N8N_ONBOARDING_STANDARD.md` restates it.
**Why MINOR:** it adds a proof obligation and tightens evidence (version policy: "a new proof obligation"). It
widens nothing: a forced run is bounded by the grants and gates that already bind the job and its trigger, it is
forbidden wherever §0 rule 2, §17 or a send would make it unsafe, and §8 already counted a hand run from the served
release as settling a runtime claim — 5.2.0 only demands that it take the schedule's exact form. The claim that a
job runs *on its schedule* still needs a natural fire (§8, §9.3, §16), and every gate this file or a standard
conditions on natural evidence keeps that condition (onboarding step 8, §23.12, a registry `PAUSED` → `ACTIVE` flip,
§23.3's three clean market days, §15). What changes is that no agent waits on a natural fire where no gate requires
it. §0, §2, §2A, §7A, §17 and §23.14 are byte-identical and no adapter changes; a §0 rule 7/8 pointer is proposed
in the PR body only. If the operator reads it as MAJOR (for example, if a dependent step starting on the forced-run
proof is read as a lifted gate), the number becomes 6.0.0 and nothing else changes. **Numbering:** follows 5.1.0
(merged `26cf80f60`, ratified `APPROVE_AGENTS_POLICY_5_1_0 1689 b0f0c6eeb`; its ratification edit, PR #1691, was open
when this branch was cut from `origin/main` `26cf80f60`); `Supersedes` is 5.1.0. Operator approval phrase (§20):
`APPROVE_AGENTS_POLICY_5_2_0 <pr_number> <head_sha>`.

**4.5.0 is ACTIVE (MINOR) — every n8n addition follows the onboarding standard and carries a workflow health
contract (§23.19).** Ratified by the operator 2026-10-10 (`APPROVE_AGENTS_POLICY_4_5_0 1666 987bf94da`, §20; PR #1666
comment by PatsKiller 2026-10-11T01:46:33Z, verbatim: "APPROVE_AGENTS_POLICY_4_5_0 1666 987bf94da — and yes to the
4.4.1 PATCH"); merged #1666 as `dd8f4cff1`; ratification recorded on the operator's in-session word 2026-10-10 ~21:55
ET ("Yes, I ratify 4.50"). It makes
`docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` the mandatory procedure for adding or changing
anything n8n fires, watches or calls; requires a workflow health contract (`config/n8n_health_contracts.json`,
gate `scripts/check_n8n_health_contracts.py`) before a lane enters shadow, canary or cutover; and requires the relay
contract check before any n8n import. It adds obligations and grants nothing: no grant tier, §17 item or never-list
entry changes, and §0, §2, §2A, §7A, §17 and §23.14 are byte-identical.

**4.4.1 is ACTIVE on merge (PATCH) — §12 off-peak arming restated as measured; §23 points at the n8n
configuration and procedure documents.** Operator-directed 2026-10-10 ~16:35 ET ("make sure you totally update the
documentation on this and the agents.md ..."). §12: the crontab header arms `LLM_DEFER_OFFPEAK=1` for every cron
line (operator, 2026-09-20), not one systemd drop-in; the wrapper count is re-measured. §23: an informational
pointer to `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md`, `N8N_ONBOARDING_STANDARD.md` and
`N8N_MONITORING_AND_REMEDIATION_STANDARD.md`, which restate §23 and add no rule. No required behaviour changes; §0,
§2, §2A, §7A, §17 and §23.14 are byte-identical. Rides `APPROVE_AGENTS_POLICY_1_2_0` (PATCH outside §0/§2/§17); the
merge still needs the operator's per-PR word (§23.13 excludes `AGENTS.md`).

**4.3.0 is ACTIVE (MAJOR) — R1: three dispatcher classes — ingest writers, governed LLM jobs,
learning/memory writers (§23.18).** Ratified by the operator 2026-10-10 (`APPROVE_AGENTS_POLICY_4_3_0 1642 64c9210e1`, §20,
~09:10 ET in session; re-approved ~09:25 ET in session, "approved", for head `c3d5e895d` after the #1643
conflict merge); merged #1642 as `203b46914`. `scripts/lib/lane_dispatch.py` `R1_STATUS` reads `ACTIVE`.
Numbered 4.3.0 because 4.2.0 is PROPOSED in the open PR #1634; whichever merges second takes the
other's history row on rebase, and if #1634 is withdrawn this becomes 4.2.0 and §23.18 becomes
§23.15. It records the operator's rulings of 2026-10-10 ~00:20 ET for all waves: (1) ingest writers,
governed LLM jobs and learning/memory writers are dispatcher-eligible classes, always shadow → canary
→ cutover, and the governed DeepSeek route is approved for the overnight trade reviewer (crontab
L401); (2) forbidden-token matching becomes whole-word / path-segment (a separate code PR);
(3) dispatched lanes carry no broker credential — the entry planner fetches bars through the data
broker (a separate code PR); (4) an `alert_events` row is not a send and backtest fields on
`paper_trade_proposals` are not paper execution; the `symbol_profiles` (L504) and `market_regime`
(L205) writers are approved for dispatch. Broker, order, stop, secret and daemon lanes stay never
dispatcher-eligible: no §23.14 sentence changes. MAJOR because what the n8n actor may cause widens by
three classes (version policy); nothing in §0, §2, §2A or §7A, and none of the broker, secret or
delete rails, is weakened.

**4.1.0 is ACTIVE (MAJOR) — registry-driven n8n dispatch, wave ladder, program push budget, 48 h
merge approval (§23.11–§23.14).** Ratified by the operator 2026-10-09 (`APPROVE_AGENTS_POLICY_4_1_0 1592 2f824b4f789110d6ccc5f3c7d5783aa9e995a079`, §20;
in session: "Approve agents 4.1.0"); the standing merge approval runs to the §23.13 `Expires-At`. It
records five operator decisions of 2026-10-09: (1) one `cron` grant activates six generic n8n
workflows once, and a lane is then enabled by a reviewed registry-row and allowlist PR, with no
per-lane import or grant (§23.11); (2) dispatcher lanes climb shadow → canary → cutover by wave,
with one `cron` grant per wave cutover (§23.12); (3) `n8nmat/*` branches get 4 pushes until
2026-10-12T23:59:59-04:00, enforced by the pre-push hook (§23.13); (4) a standing 48 h merge approval for `n8nmat/*` PRs with Agent A's review verdict on
the program board, green on the exact head, and nothing live until main CI is green on the merged SHA — merge only,
never deploy or grant (§23.13). §23.14 keeps broker,
order, secret and daemon lanes off the dispatcher by test; the 4.0.0 `trade-ai-scalp-live` exception
is kept unchanged and stays the only one. (5) Operator decision 16:40 ET: the approval-router lane
may read guard state (pending requests, grant expiry) through a read-only projection and never
request, grant, revoke or consume (§23.14). MAJOR because §17 changes (a merged
dispatcher-row PR becomes the operator's scheduling decision) and merge and push authority widen for
one program (version policy). Nothing in §0, §2, §2A or §7A, and none of the broker, secret or
delete rails, is weakened.

**3.0.0 is ACTIVE (MAJOR) — governed LLM and Agent capability in n8n (§23 amendment).** Ratified by
the operator 2026-10-09 (`APPROVE_AGENTS_POLICY_3_0_0 1547 a0984546181d316f92931c7b87218b55b3b836d9`, §20).
§23.10 still grants nothing until each precondition is measured true with a receipt. It replaces §23.3's first bullet, §23.4 and
§23.5's first bullet, and adds §23.8 (n8n Agent nodes), §23.9 (governance parity) and §23.10
(preconditions before the first Agent node, which grant nothing until each is measured true with a
receipt). It records five operator decisions of 2026-10-09: ratify the proposal's §3 text; n8n
routing order Grok (OAuth) → ChatGPT (OAuth) → DeepSeek (metered); container internet egress
BLOCKED, not proxied; the first Agent is read-only "explain why lane X failed", shadowed first;
owner MFA waived, the non-superuser DB role still required. MAJOR because egress policy and the
n8n actor's authority change (version policy).

**2.0.0 is ACTIVE from 2026-10-08 (MAJOR) — the n8n carve-out, §23.** Ratified by the operator
(`APPROVE_AGENTS_POLICY_2_0_0 1513 20d8b5f0d`, §20; merged #1513 2026-10-08T09:06:46-04:00; 2.0.1
PATCH on top). It adds §23 "n8n: scheduler-of-record and governed routing (carve-out, n8n
only)": n8n workflows are scheduler entries under §9.3; n8n may request a run only through the
gateway `coordination/run` operation for allowlisted lanes; n8n may choose among registered `n8n_*`
processes, template ids and routing policies but never a model, a provider or a raw prompt; n8n holds
exactly one credential (the relay bearer) on the precondition that execution data on success is not
retained; n8n is replaceable. MAJOR because routing and scheduler reach widen for one actor (version
policy: classify by the weakest guarantee); nothing in §0, §2, §2A, §7A is weakened for any actor. §9.3
and §17 are amended in place (§23.7). Operator direction 2026-10-08: "make agents.md carve out just
for n8n".

**1.5.0 (2026-10-06, MINOR, operator-directed)**: §7A positions gaps updated — never take `abs()` of a broker leg (transfer direction). **1.4.0 (2026-10-06, MINOR, operator-directed)** adds the positions source-of-truth rules to §7A ("Positions, cost basis and portfolio value"). Nothing else changes; the 1.3.0 text below still governs.

**1.3.0 is ACTIVE from 2026-09-27 — MAJOR.** Ratified by the operator 2026-09-27
(`APPROVE_AGENTS_POLICY_1_3_0 1232 1ea66d24912b4242a49d42cc92e94b0030ec4173`, amendment reviewed,
"yes" to the ratification edit). It resolves the conflict between the old blanket broker
prohibition and architecture v3.3: engineering agents may build and simulate broker-adjacent code
(A1/A2) **only while a per-task `execution-engineering` grant is active** (operator decision at
ratification); only the deterministic execution path may place a live order, and only inside a
verified 2FA session envelope or a per-order authorization; no LLM ever originates an order or holds
live activation (A4) or order authority (A5). `AI_WORK_POLICY.md`'s push budget outranks the
implementation program's per-stage pushes. Details: §22 and
`docs/governance/agent-standards/AUTHORITY_AMENDMENT_1_3_0.md`.

**1.2.7 is ACTIVE from 2026-09-24T21:31:15-04:00** (merge of PR #1227, `756eb977e`; a PATCH outside §0/§2/§17 is ACTIVE on merge under `APPROVE_AGENTS_POLICY_1_2_0`). A PATCH release: §13.4
is corrected to what shipped in PRs #1223, #1225 and #1226 (live 2026-09-24 as `7a9dcec26`) — the
`InstrumentRecord@v1` field list gains the shipped `beliefs[]` block (`InstrumentBelief@v1`, written
only by `cio_belief_writer` through `apply_belief`) and retires the "SPECIFIED — no producer" lines it
replaces; the subject-key namespace records the settled entity policy (`INDUSTRY:` / `THEME:` are
tags-only by policy, `SECTOR:` is mintable with no producer); the narrative-subject table gains
`OPTION_CONTRACT` (a `security_guid` with `share_class="option"`, minted by `options_identity`, no
options-specific id prefix). It adds no rule and weakens nothing; touches no §0/§2/§17 authority or
role profile; rides `APPROVE_AGENTS_POLICY_1_2_0`.

**1.2.6 is ACTIVE from 2026-09-20T15:13:47-04:00** (merge of PR #1145; amended without a version bump by PR #1153, merged 2026-09-20T19:18:34-04:00 — recorded as one version, one activation event). A version is ACTIVE
only after approval *and* merge, and an unmerged policy must never render as an affirmative one.
A MINOR release: §6 gains "a dry run must not be able to REACH the mutation" and the reclaim
obligation for claim-style queues (PR #1143); §12 retires the stale `should_scheduled_skip`
reference in favour of the off-peak deferral queue, its three operator-set caller tiers, its arming
switch and the measured 21% blast radius of arming it globally (PR #1134) — while stating plainly
that the process-boundary wrapper still drops on 25 active crontab lines, and that migrating them is
open work; §9.3 records that a call gated in-process is now queued rather than dropped, and names the
two lanes installed beside it. It adds proof
obligations and weakens nothing, and touches no §0/§2/§17 authority or role profile — so it rides
`APPROVE_AGENTS_POLICY_1_2_0` and needs no new approval token.

**1.2.5 is ACTIVE from 2026-09-20.** A PATCH release: §13.4 dark-contracts list and the
AgentView/AGENT_COMMITMENT “no producer” prose are corrected to match measured CLOSED rows in
`docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md` (load-by-subject / OUTCOME / AgentView /
commitment / librarian index OBSERVED). Touches no §0/§2/§17 authority; rides
`APPROVE_AGENTS_POLICY_1_2_0`.

**1.2.4 is ACTIVE from 2026-09-18.** A PATCH release: §10 documents that the default
`TRADEAI_CURRENT_BOUND_UNITS` includes `cio-governed-bridge.service` (promote must re-resolve the
bridge after CURRENT moves; observed 2026-09-18 pin drift vs portfolio-server). See
`docs/ops/BRIDGE_PIN_ALIGNMENT.md`. Touches no §0/§2/§17 authority; rides
`APPROVE_AGENTS_POLICY_1_2_0`.

**1.2.3 is ACTIVE from 2026-09-18.** A MINOR release: it adds "What 2026-09-18 taught — Agent controls
audit" (router write-gate gaps, prompt-injection PARTIAL ingress, failed-unit timer churn, alert
`runtime_mode` SHADOW, grounding/RAG verify commands). It does not touch §0, §2, §17 or role authority.
Operator-directed merge/promote of PR #1069; rides the existing `APPROVE_AGENTS_POLICY_1_2_0`
ratification for sections outside §0/§2/§17. Merge ≠ deploy — CURRENT promote is a separate step.

**1.2.2 (ENOSPC false-green lesson) was ACTIVE on `main` via PR #1068** until superseded by 1.2.3.
A MINOR release: it records the Postgres ENOSPC → Command Center false-green outage under
"What 2026-09-18 taught — Postgres ENOSPC → Command Center false-green". It does not touch §0, §2,
§17 or role authority. **A served CURRENT pin may still carry an older Policy-Version until
explicitly promoted** — do not treat merge as live policy on the dashboard host.

**1.2.1 is ACTIVE from 2026-09-16 (live CURRENT).** A PATCH release: it corrects two statements in §7 that PR #1045 made
factually wrong and records the free-web result in §12. It touches no rule, adds no restriction, and does not
touch §0, §2, §17 or role authority — so it carries the operator's 2026-09-16 direction to update this file,
and does not require a new `APPROVE_AGENTS_POLICY` token.

**1.2.0 was ACTIVE from 2026-09-14.** The operator approved it with `APPROVE_AGENTS_POLICY_1_2_0`, bound to PR #1022 at
head `ad5c533b2abc0150feba19c071aa0ea56364b251`; it superseded 1.1.0 (see the version history).

**1.0.0 is the first formal baseline, not a rewrite.** The document was previously unversioned;
`Supersedes: UNVERSIONED` records that literally. It is **not** called 2.0.0 because no prior
formal 1.x policy exists to supersede — measured, not assumed: `Policy-Version:` appeared zero
times in this file before this change.

**1.0.0 is the first formal baseline, not a rewrite.** The document was previously unversioned;
`Supersedes: UNVERSIONED` records that literally. It is **not** called 2.0.0 because no prior
formal 1.x policy exists to supersede — measured, not assumed: `Policy-Version:` appeared zero
times in this file before this change.

## Ratifying edits (moved here from §26, §27 and §28 by 25.0.0; history, not binding)

### 26.7 Ratifying edit (18.0.0)

- **One clause of "Shared security research — NO SILOS" is replaced at ratification,** and nothing outside the
  header block, the banner, §26 and the 18.0.0 history row changes. Methodology rule 1 reads, while PROPOSED:

  ```
  1. **One security → one spine.** Key by `subject_guid` when known; always carry `symbol`.
     Identity rules above still apply (`issuer_guid` / `subject_guid` — never invent a second map).
  ```

  and the ratifying edit makes it:

  ```
  1. **One security → one spine → one prospect.** Key by `security_guid` (`subject_guid` is the same
     value for a security and is mapped, never a second key); carry `issuer_guid` and `symbol`.
     The spine feeds the CIO prospect record, the single per-security truth (§26).
  ```

  *Cause (§20): §20 — rules are replaced, not accumulated; until ratification the clause stays byte-identical, so no
  agent reads a PROPOSED rule as in force.*

### 27.5 Ratifying edit (19.0.0)

- **Four clause edits, and nothing else outside the header block, the banner, §27 and the 19.0.0 history row.** The
  ratifying edit also sets `CARVEOUT_STATUS = "ACTIVE"` in `scripts/lib/n8n_broker_read_carveout.py`.
  `tests/test_agents_policy_19_0_0_broker_read_controls.py` holds the anchors and digests. *Cause (§20): §20 — rules
  are replaced, not accumulated; until ratification the clauses stay byte-identical, so no agent reads a PROPOSED
  widening as in force.*

  (1) In §23.14, directly after the first bullet:

  ```
  - **One exception (19.0.0, §27.1): the audited read-only broker lanes.** n8n may schedule and trigger the closed
    set of read lanes in `scripts/lib/n8n_broker_read_carveout.py` `READ_LANES` — the §24.11 steps, and market-data
    reads that pass the same audit — each run on the host through the allowlisted executor, only while every broker
    trading lock is LOCKED and the Schwab access mode is `read_only`; n8n holds no credential. Orders, stop writes,
    cancel, replace, preflight, 2FA, `place_order`, live and paper flags, paper execution and senders stay on this
    never-list, and changing any read lane into one that writes is §17. *Cause (§20): operator 2026-10-22,
    verbatim: "N8N can read the broker because right now we're only doing reading of the broker. We're not doing
    any trading. So I want to amendment."*
  ```

  (2) and (3) [release-train clauses — removed with the release train by 25.0.0.]

  (4) In §17, directly after that paragraph:

  ```
  **Operator controls (19.0.0, §27):** clearing the trading kill switch · resuming broker jobs · changing the n8n
  relay live list · issuing a grant from Ops → Controls · registering or revoking a passkey · changing an n8n
  broker read lane into one that writes, or widening any read lane's reach (§27.1). A risky act is made by the
  operator on Ops → Controls with a passkey and a typed phrase, or at the host terminal; no agent ever calls a
  Controls endpoint or the host applier.
  ```

### 28.7 Ratifying edit (20.0.0)

- **These clause edits, and nothing else outside the header block, the banner, §28 and the 20.0.0 history row.**
  `tests/test_agents_policy_20_0_0_agent_operations.py` holds the anchors and digests. *Cause (§20): §20 — rules are
  replaced, not accumulated; until ratification the clauses stay byte-identical, so no agent reads a PROPOSED
  widening as in force.*

  (1) In §0 rule 6, directly after the 15.0.0 sentence, and the same sentence in each of the four adapters:

  ```
     A second exception, binding only once AGENTS.md 20.0.0 is ACTIVE: the host /tmp hygiene lanes
     may remove the /tmp items their reviewed tmp.* rules select (scripts/tmp_hygiene_auto.py),
     and nothing else (AGENTS.md §24.12).
  ```
  (2) In §24.12, directly after the "Scope" bullet:

  ```
  - **Named addition (20.0.0): the host `/tmp` hygiene lanes.** Besides `scripts/disk_hygiene.py`, exactly these may
    remove items under this exception: `scripts/tmp_hygiene_auto.py`, run on the host by the systemd user timers
    `tradeai-tmp-hygiene-apply` (hourly) and `tradeai-tmp-hygiene-pressure` (every 5 minutes; it acts only at 85% or
    more `/tmp` inode use, and at most once per 15 minutes). They remove only items the reviewed `tmp.*` rules in
    `config/disk_hygiene_rules.json` select, and only under `/tmp`; they never run under the n8n executor. The
    standing approval is `tmp.auto_apply.standing_approval` and the kill switch is `tmp.auto_apply.enabled`; a manual
    `scripts/tmp_hygiene.py --apply` still needs the grant. They never touch a dirty, unpushed or unregistered
    worktree, never run `git worktree remove --force`, and never touch a `tmp.never_touch_globs` path (including
    `tradeai-*`); every run writes a deletions ledger and a `LaneRunReceipt`. These lanes are named here; nothing
    broader is added, and no other deletion code is covered by analogy. *Cause (§20): operator 2026-10-22,
    verbatim: "It needs to be able to delete it. Just looking at it won't do anything." (`/tmp`, a tmpfs, at 99%
    inodes while the tmp lane ran plan-only), and "approve all" for the 20.0.0 package; PR #1954.*
  ```
  (3) [release-train clause — removed with the release train by 25.0.0.]

  (4) In §7, directly before "## Caches and derived stores — fail closed, never open":

  ```
  ## Timeouts, reaper caps and kill windows — measured, never guessed `[VERIFIED]` 2026-10-22

  Single reference: `docs/ops/PIPELINE_TIME_SETTINGS.md`. Pinned by
  `tests/test_pipeline_time_settings_20261022.py` (CI gate `pipeline_time_settings_20261022`).

  - **Never lower a timeout, reaper cap, orphan wait or tick deadline without measured runtime
    evidence in the PR**: the query, the window, the output. The test, the doc table and the setting
    change together. *Cause: two caps nobody had measured killed two `pipeline_critical` pipelines on
    every run.*
    - `trade_ai_orchestrator` at the 20 m reaper cap: every market-hours run on 2026-10-21/22 was SIGTERMed
      at 1216–1377 s (20 + 22 failed).
    - `symbol_enrichment` under the health tick's `orphan_wait_s: 30`: 224 failed / 1 success in 36 h.
  - **A runtime measured under a kill is censored, not a distribution.** If runs die at the cap, the longest
    "observed" runtime is the cap. Read the pre-cap era or the uncensored completions.
    - *Cause:* "enrichment takes 25–50 s" was the survivors of a 30 s kill.
    - The uncensored distribution, 2026-09-20..10-07 (n=3,178), is p50 136 s / p95 241 s / max 419 s.
    - The orchestrator's 1377 s is a floor.
  - **Current values; do not lower them:**
    - **orchestrator reaper cap.** `max_runtime_min` is **30** in `config/process_reaper_policy.json` and
      `scripts/process_reaper.py` `DEFAULT_RULES`, and the two must be equal. 30 m ≥ 1377 s + 300 s, and it stays
      under `continuous_runner.py`'s 2700 s.
    - **health tick.** `tick_deadline_s` is **300**; 300 + 10 s kill grace + receipt < unit `TimeoutStartSec=330`.
    - **watchdog enrichment.** The batch wait is **min(240 s, `HEALTH_TICK_STEP_TIMEOUT_S` − 15 s)**, and
      `pipeline-watchdog` runs **last** in the tick.
    - **`orphan_wait_s`.** It stays **30**, as a legacy safety net only.
  - **A step that needs its children to finish supervises them; it does not get a longer orphan wait.**
    `orphan_wait_s` is paid once per step against the shared 300 s tick.
    - A step that waits for children must run where waiting cannot defer the steps after it.
    - At 4th place, a 240 s wait would have deferred seven monitors on every even-hour tick.
  ```
  (5) Stale references (§0 rule 10), in §2, the §7 table, §13 and §17, each line or pair of lines

  ```
  > **The rail is the unconditional raise at `scripts/lib/cio_instrument_record.py:390`.** It
  ```
  becomes

  ```
  > **The rail is the unconditional `BehaviorWriteRefused` raise in `apply_cognition()`
  > (`scripts/lib/cio_instrument_record.py`).** It
  ```

  ```
  All 51 occurrences are prose. The rail is an unconditional raise at `cio_instrument_record.py:390`. |
  ```
  becomes

  ```
  All 51 occurrences are prose. The rail is the unconditional `BehaviorWriteRefused` raise in `cio_instrument_record.apply_cognition()`. |
  ```

  ```
                       Not an env var: an unconditional raise at cio_instrument_record.py:390.
  ```
  becomes

  ```
                       Not an env var: the unconditional raise in cio_instrument_record.apply_cognition().
  ```

  ```
  `BEHAVIOR_FIELDS`, altering or conditionalising the unconditional raise at
  `scripts/lib/cio_instrument_record.py:390`, or routing a cognition write around it; there is no
  ```
  becomes

  ```
  `BEHAVIOR_FIELDS`, altering or conditionalising the unconditional raise in
  `apply_cognition()` (`scripts/lib/cio_instrument_record.py`), or routing a cognition write around it; there is no
  ```

  (6) In §27.3, directly after the "Risky direction" bullet:

  ```
  - **Sudo window (20.0.0, §28.5).** One passkey assertion may open a window, bound to that browser session and
    that passkey, during which a risky act needs only its typed phrase. The window lasts the operator setting
    `ops_controls.sudo_window_minutes` (default 60, at most 120) and ends on 15 minutes idle, on logout or on "End
    window now"; the page shows the time left. Issuing a grant, clearing the kill switch, adding or revoking a
    passkey and changing the window settings always need a fresh assertion. Every act inside a window is audited
    with the assertion that opened it, and agents still never call a Controls endpoint. *Cause (§20): operator
    2026-10-22, verbatim: "we need a time to live for this. Maybe 1 hour or 2 hours. So it caches." and "approve
    sudo window".*
  ```
  (7) In §27.4, the "Nothing is built" bullet became "Ops → Controls is built and served" (the text in force is §27.4).

  (8) In §17, directly after the 19.0.0 "Operator controls" paragraph:

  ```
  **Schwab stays read-only (20.0.0, §28.6):** changing the Schwab access mode away from `read_only` · unlocking a
  broker trading lock · clearing a `live_submit` or `broker` kill switch. Each is the operator's alone, made with a
  passkey on Ops → Controls or at the host terminal; never by an agent, a release, Mergify, the deploy poller or n8n.
  ```
  (9) In §0, and the same in each of the four adapters: the intro sentence

  ```
  These ten prevent irreversible harm. They are repeated verbatim in every tool adapter, because an
  agent that reads fifteen lines and stops must still know them.
  ```
  becomes

  ```
  These ten prevent irreversible harm, and rule 11 keeps work recoverable. They are repeated verbatim
  in every tool adapter, because an agent that reads fifteen lines and stops must still know them.
  ```
  and rule 11 directly after rule 10:

  ```
  11. **Claim, log, hand off.** Before editing, read the claim board and the active worklogs
      (`scripts/agent_claim.py status`); claim your files; keep your worklog current (plan, changes,
      decisions, blockers, handoff); when you stop for any reason, leave the exact next step. Work in
      progress must be recoverable by any agent of any vendor: commit locally at least every hour,
      record branch, worktree path and head SHA in the worklog, and push a draft PR, within the push
      budget, for anything a cloud agent may need. Taking over a stale or abandoned claim is done with
      `agent_claim.py takeover`, never by starting over. How to pick up work: AGENTS.md §28.3a.
  ```

---

## Where the 25.0.1 text went

Every rule-bearing passage of AGENTS.md 25.0.1, by line range in `tests/fixtures/agents_pre_26_0_0/AGENTS.md`, and where 26.0.0 put it. *LESSONS* = `docs/governance/LESSONS_LEARNED.md`; *OPEN_ITEMS* = `docs/governance/OPEN_ITEMS.md`; *retired* = duplicate, superseded or stale, with the reason.

### §7 Standing traps

| 25.0.1 lines | rule (paraphrase) | 26.0.0 location |
|---|---|---|
| 476-477 | compile() not ast.parse for parse checks | §7 Tooling and shell |
| 478-479 | check exit codes for specific value; $? after pipe | §7 Tooling and shell |
| 480 | read tracebacks whole | §7 Tooling and shell |
| 481-483 | except of parent class launders diagnosis | §7 Tooling and shell |
| 484-486 | route edits through safe_text_edit; check encoding on big diffs | §7 Tooling and shell |
| 487-491 | read_text/write_text normalise CRLF; edit as bytes; known CRLF files | §7 Tooling and shell |
| 492-494 | re-dump JSON registry with original escaping | §7 Tooling and shell |
| 495-499 | path-load modules under test; register in sys.modules | §7 Tooling and shell |
| 500-502 | worktree has no live data; compare with main | §7 Tooling and shell |
| 503-505 | check docs index after merging main | §7 Tooling and shell (generated files) |
| 506-510 | never write control_surface_digest into SOP evidence | §7 Tooling and shell |
| 511-515 | reproduce cron sys.path form | §7 Tooling and shell |
| 516 | gate editing source verifies it compiles | §7 Tooling and shell (compile rule) |
| 517-523 | cross-invocation guarantees need durable state | §7 Caches and derived stores |
| 524-528 | mode flag disabling a control is a finding | §7 Controls whose name exceeds their code |
| 529-533 | never fix an alarm without fixing its cause | §7 Controls whose name exceeds their code |
| 534-539 | bound by the thing you bound | §7 Caches and derived stores |
| 540-543 | Finviz 200 without CSV header not cookie expiry | retired |
| 544-548 | session-cache heal is not data recovery | retired |
| 550-559 | detector shape further instances table | LESSONS |
| 563-564 | single reference PIPELINE_TIME_SETTINGS + pin test | §7 Timeouts, reaper caps and kill windows |
| 566-572 | never lower caps without measured evidence | §7 Timeouts, reaper caps and kill windows |
| 573-577 | runtime under a kill is censored | §7 Timeouts, reaper caps and kill windows |
| 578-585 | current values: reaper 30, tick 300, watchdog wait, orphan 30 | moved:docs/ops/PIPELINE_TIME_SETTINGS.md |
| 586-589 | steps supervise children, not longer orphan wait | §7 Timeouts, reaper caps and kill windows |
| 593-599 | fail-open cache: preserve prior value, record failure | §7 Caches and derived stores |
| 600-603 | freshness is not validity | §7 Caches and derived stores |
| 604-608 | never 'newest copy wins' on divergent stores | §7 Caches and derived stores |
| 609-610 | store surviving by breakage is not backed up | §7 Caches and derived stores |
| 611-619 | counter path resolves to one location; no __file__ paths | §7 Caches and derived stores |
| 620-627 | search_budget.json ledger is binding; alarms read it | §7 Caches and derived stores |
| 628-634 | provider limits from response headers | retired |
| 638-639 | follow symbols to the write call | §7 Investigation method |
| 640 | scheduler declaration: check cron and systemd | §7 Investigation method |
| 641 | atime is not evidence of consumer | §7 Investigation method |
| 642-643 | symlinked roots are not a control | §7 Investigation method |
| 644-648 | ask which component produced the result | §7 Investigation method |
| 649-653 | loud failures rarely the one to investigate | §7 Investigation method |
| 654-658 | configured is not registered | §7 Investigation method |
| 659-661 | rotated log is not empty | §7 Investigation method |
| 665-666 | verify a mechanism's scope by command | §7 Investigation method |
| 668-674 | scope table of five findings | LESSONS |
| 678-679 | state what detector keys on before trusting zero | §7 Investigation method |
| 681-691 | detector shape table | LESSONS |
| 693-698 | attempts_24h: never-started vs failed-first | §7 Investigation method |
| 699-700 | positive-control before publishing a zero | §7 Investigation method (points to §8A) |
| 704-705 | named control is not evidence of restriction | §7 Controls whose name exceeds their code |
| 707-713 | controls table (interdict, shadow, blocked actions, MBI_BEHAVIOR) | OPEN_ITEMS |
| 715-726 | three severities of name-exceeds-code | §7 Controls whose name exceeds their code |
| 728-729 | sweep is candidate generator; do not quote 212 | §7 Investigation method |
| 731-738 | fourth severity: always-on control | §7 Controls whose name exceeds their code |
| 740-744 | checker exception is not a system finding | §7 Controls whose name exceeds their code |
| 748-750 | litmus failures; path map pointer | §7 Operator replies, data gaps and agent numbers |
| 752-756 | one reply chokepoint finalize_operator_reply | §7 Operator replies, data gaps and agent numbers |
| 757-760 | house facts first; evidence contract | §7 Operator replies, data gaps and agent numbers |
| 761-764 | answer the named subject; one resolver; cashtag rules | §7 Operator replies, data gaps and agent numbers |
| 765-768 | Flash rewording only with grounded numbers | §7 Operator replies, data gaps and agent numbers |
| 769-773 | promise only what is queued; pending expiry | §7 Operator replies, data gaps and agent numbers |
| 774-779 | resolved means proven; one gap writer | §7 Operator replies, data gaps and agent numbers |
| 780-784 | rule G0 grounding modes and thresholds | §7 Operator replies, data gaps and agent numbers |
| 785-788 | chat memory GUID-keyed, read-only; name clash | §7 Operator replies, data gaps and agent numbers |
| 792-795 | second def silently replaces first | §7 Tooling and shell |
| 796-798 | stored results replay is upper bound | §7 Operator replies, data gaps and agent numbers |
| 802-803 | disabled spine part is an incident | §7 The identity and tagging spine — keep it on |
| 805-809 | tagger cron outage narrative | LESSONS |
| 813-832 | ticker is alias; issuer_guid default join; V example | §7 The identity and tagging spine — keep it on |
| 836-861 | names and CUSIPs from Schwab instruments; never hardcode | §7 The identity and tagging spine — keep it on |
| 863-877 | feed contracts; ambiguity returns nothing; no cross-issuer fuzz; suffix from end | §7 The identity and tagging spine — keep it on |
| 879-881 | model may only propose CANDIDATE | §7 The identity and tagging spine — keep it on |
| 883-899 | tagging is two-way; inbound tagger | §7 The identity and tagging spine — keep it on |
| 901-918 | identifier model table; prefer issuer_guid | moved:docs/architecture/IDENTITY_SPINE.md |
| 920-925 | judgment carries GUID; raw market data does not | §7 The identity and tagging spine — keep it on |
| 927-935 | coverage and untagged tables; tag with research_identity | OPEN_ITEMS |
| 937-946 | modules table and do-nots (re-mint, local recompute, null subject_guid) | §7 The identity and tagging spine — keep it on |
| 950-972 | mention roles deterministic; undecided never guessed; role_source | §7 The identity and tagging spine — keep it on |
| 974-975 | mention coverage counts | moved:docs/architecture/DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md |
| 977-980 | sources with no prose; filer_name never scanned | moved:docs/architecture/DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md |
| 984-1001 | mention has no lifetime; no model decides retention | §7 The identity and tagging spine — keep it on |
| 1003-1006 | mention jobs and cadence | moved:docs/architecture/MENTIONS_SCHEDULING_AND_RETENTION.md |
| 1008-1012 | retention inherited; refuse if unreadable; unwindowed reported | §7 The identity and tagging spine — keep it on |
| 1014-1016 | deleting a mention is not the never-delete rule | OPEN_ITEMS |
| 1018-1023 | guardrails: no longer lifetime, no model, new source with window | §7 The identity and tagging spine — keep it on |
| 1027-1033 | macro has no issuer; test keeps it out of SOURCES | §7 The identity and tagging spine — keep it on |
| 1035-1036 | fred_economic_data never created | OPEN_ITEMS |
| 1040-1047 | /caps is the operator surface; no CC page | §7 Model caps, the bridge and escalation |
| 1048-1058 | writes DB then registry; ceilings hold; drift reported | §7 Model caps, the bridge and escalation |
| 1059-1061 | global cap not settable via /caps | §7 Model caps, the bridge and escalation |
| 1065-1069 | bridge user unit; restart scope; not sudo | §7 Model caps, the bridge and escalation |
| 1071-1079 | four caps; read the error body, not status | §7 Model caps, the bridge and escalation |
| 1081-1084 | projections 17x actual | retired |
| 1086-1090 | caller identity server-side; caps rows; record previous values | moved:docs/architecture/GOVERNED_MODEL_BRIDGE.md |
| 1092-1093 | bridge code change live only after restart | §7 Model caps, the bridge and escalation |
| 1097-1108 | escalation ladder; step 3 hard stop | §7 Model caps, the bridge and escalation |
| 1110-1118 | one notification per run; bypass router; failed notify stops; process_id; NEVER_CHAIN | §7 Model caps, the bridge and escalation |
| 1125-1129 | deterministic custodian identity-spine alarms | moved:docs/architecture/IDENTITY_SPINE.md |
| 1131-1134 | no model in identity lane | §7 The identity and tagging spine — keep it on |
| 1136-1143 | model proposes CANDIDATE on free lane; CUSIP confirms | §7 The identity and tagging spine — keep it on |
| 1147-1149 | identity status travels; never downgrade | §7 The identity and tagging spine — keep it on |
| 1150-1153 | GICS and thesis vocabulary separate columns | §7 The identity and tagging spine — keep it on |
| 1154-1160 | sentinel needs TTL | §7 The identity and tagging spine — keep it on |
| 1161-1162 | schema changes additive | §7 The identity and tagging spine — keep it on |
| 1163-1164 | DDL once, off-peak, never recurring | §7 The identity and tagging spine — keep it on |
| 1168-1172 | ls scripts/lib before building; KNOWN_DARK never grows | §7 The identity and tagging spine — keep it on |
| 1176-1180 | research shared across silos; CIO owns; private cache is defect | §7 Shared security research — NO SILOS |
| 1182-1188 | canonical program docs | §7 Shared security research — NO SILOS |
| 1192-1194 | one security, one spine, one prospect | §7 Shared security research — NO SILOS (rule 1, verbatim) |
| 1195 | owner is cio; silos contribute | §7 Shared security research — NO SILOS (rule 2) |
| 1196-1198 | write path upsert_from_hermes/contribute; flag | §7 Shared security research — NO SILOS (rule 2) |
| 1199-1201 | every silo reads view_for_silo | §7 Shared security research — NO SILOS (rule 3) |
| 1202-1204 | options merges spine rows | §7 Shared security research — NO SILOS (rule 3) |
| 1205-1206 | SymbolDecisionObject prefers spine | §7 Shared security research — NO SILOS (rule 3) |
| 1207-1208 | expression ranking consumer, shadow-only | §7 Shared security research — NO SILOS (rule 3) |
| 1210-1215 | forbidden list | §7 Shared security research — NO SILOS (Forbidden) |
| 1217-1224 | before you build research for a desk | §7 Shared security research — NO SILOS (rule 4) |
| 1226-1227 | structural guard tests | §7 Shared security research — NO SILOS |
| 1229-1236 | wiring status table | OPEN_ITEMS |
| 1238-1239 | no OBSERVED_LIVE claim until end to end | §7 Shared security research — NO SILOS |
| 1243-1245 | read lane reason before switching ON | §7 Research lanes |
| 1247-1253 | lane state table (incl. retired enqueue, do not invent schedule) | §7 Research lanes |
| 1257-1261 | schedule and gate never overlap | retired |
| 1262-1265 | gate reads configured not effective | retired |
| 1266-1273 | credentials from env_bootstrap; run it and look | §7 Research lanes |
| 1277-1286 | no_match sentinel duplicate | retired |
| 1290-1293 | integrity sweep exists; db_retention unscheduled | §7 Research lanes |
| 1295-1297 | sweep reports, never repairs; test bans writes | §7 Research lanes |
| 1299-1300 | exit 0 means the check ran | §7 Research lanes |
| 1302-1305 | populations aggregate; spot-check sweep numbers | §7 Research lanes |
| 1309-1334 | output_tables must name existing written table | §7 Research lanes |
| 1338-1344 | discover columns; keep states distinct | §7 Research lanes |
| 1348-1360 | PR collision; recompute generated files | §7 Tooling and shell (generated files) |
| 1364-1372 | rows_produced unknown is not zero | §7 Investigation method |
| 1376-1390 | check producer schedule behind inner joins | §7 Investigation method |
| 1394 | count durable rows, not invocations | §7 Research lanes |
| 1395-1396 | ask which component produced result | retired |
| 1397 | sub-second drain Finished means empty queue | §7 Research lanes |
| 1398-1400 | zero_non_error_24h usually unemployed | §7 Research lanes |
| 1404 | never mint placeholder identity | §7 Data and identity |
| 1405 | never auto-remediate store divergence | retired |
| 1406-1407 | validate against known set; never normalise | §7 Data and identity |
| 1408-1413 | standard omitting vocabulary cannot enforce pre-build check | §7 Data and identity |
| 790 | intro: 'Traps this work paid for' | retired |
| 1120-1121 | design pointer DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md | §7 The identity and tagging spine — keep it on (pointer kept) |

**Retired**

| 25.0.1 lines | reason |
|---|---|
| 540-543 | duplicate of §13.6 'Finviz credentials' and §8 Verification traps (Finviz probe both auth modes) |
| 544-548 | duplicate of §13.6 'Cache heal trap' |
| 550-559 | history; detector-shape examples summarised in LESSONS L7-23 (attempts_24h row in L7-24); duplicate of 676-691 |
| 578-585 | moved: values live in docs/ops/PIPELINE_TIME_SETTINGS.md (already there); the one equality rule kept |
| 628-634 | duplicate of §12 Search providers 'One ledger' (ceilings from response headers); incident in LESSONS L7-18 |
| 649-653 | merged into §7 'Ask which component produced the result' |
| 668-674 | history; scope table summarised in LESSONS L7-22, mechanisms named inline in the rule |
| 681-691 | history; detector table summarised in LESSONS L7-23 |
| 699-700 | duplicate of §8A 'Positive-control every detector before publishing a zero' (cross-referenced) |
| 707-713 | table: broken rows to OPEN_ITEMS; BehaviorWriteRefused and MBI_BEHAVIOR rows duplicate §2; 'All 51 occurrences' count stale |
| 728 | stale count; candidate list to OPEN_ITEMS, rule 'candidate generator, not a count' kept |
| 733-744 | history; release-pin and PortfolioValidator incidents fixed (cio_phase2_exact_main_deploy.sh:848, portfolio_validator.py:18) — LESSONS L7-26 |
| 748-750 | history; LESSONS L7-27 |
| 805-809 | history; LESSONS L7-31 |
| 1003-1006 | moved (already in MENTIONS_SCHEDULING_AND_RETENTION.md §4); jobs now run under lane document-mentions-backfill and platform-maintenance-nightly |
| 1011-1012 | stale: config/data_retention_policy.json:615-618 gives hermes_external_research a 90-day window; pruner gap to OPEN_ITEMS |
| 1014-1016 | conflicts with §0 rule 6 / fixed fact 9 (only disk_hygiene.py and tmp_hygiene_auto.py delete); to OPEN_ITEMS for operator decision |
| 1035-1036 | open gap to OPEN_ITEMS (fred_economic_data declared, fred_economic_series written) |
| 1081-1084 | stale: bridge reserves calibrated_projected_usd (cio_governed_model_bridge.py:2609) |
| 1075-1077 | stale: COST_CAP_EXCEEDED now 429 with a logged reason (cio_governed_model_bridge.py:185, :2665) |
| 1092-1093 | history (bridge running from the 2026-08-27 release); restart rule kept |
| 1198 | stale: CROSS_ASSET_SPINE defaults ON (scripts/lib/cross_asset/events.py:26); fixed to 'on unless CROSS_ASSET_SPINE=0' |
| 1229-1236 | wiring-status table to OPEN_ITEMS; Bill A/B status is history |
| 1247-1253 | superseded: config/lane_registry.json holds each lane's state and reason; RI overnight times stale (lane run-research-intelligence-overnight '30 20 * * 1-5 + 15 2 * * *') |
| 1257-1261 | duplicate of §8 'A schedule and the gate it must pass can be disjoint' |
| 1262-1265 | duplicate of §8 'A gate must re-read what the run will actually do' |
| 1275-1286 | duplicate of §7 sentinel rule (old 1154-1160) |
| 1291-1293 | history; 'db_retention.py unscheduled' stale (lane db-retention-timer ACTIVE) |
| 1312-1327 | history; output_tables evidence in LESSONS L7-41, open gap in OPEN_ITEMS |
| 1348-1358 | stale: SOP digest files no longer bound (AT_HEAD since 2026-09-25), docs/INDEX.md merge=union (.gitattributes:9-16); contradicted old 503-510 |
| 1364-1371 | history; LESSONS L7-43 (PipelineRun._rows now None, scripts/pipeline_registry.py:197) |
| 1376-1389 | history; LESSONS L7-44; scheduling gap to OPEN_ITEMS |
| 1395-1396 | duplicate of §7 'Ask which component produced the result' (old 644) |
| 1405 | duplicate of §0 rule 5 |
| 790 | connective heading text; the two traps it introduced are kept |

**Moved to the document that owns the subject**

| 25.0.1 lines | to |
|---|---|
| 578-585 | `docs/ops/PIPELINE_TIME_SETTINGS.md` |
| 811-946,1025-1036,1123-1172 | `docs/architecture/IDENTITY_SPINE.md` |
| 948-980 | `docs/architecture/DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md` |
| 982-1023 | `docs/architecture/MENTIONS_SCHEDULING_AND_RETENTION.md` |
| 1038-1061 | `docs/architecture/GOVERNED_MODEL_BRIDGE.md` |
| 1063-1093 | `docs/architecture/GOVERNED_MODEL_BRIDGE.md` |
| 1095-1121 | `docs/architecture/DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md` |
| 752-798 | `docs/OPERATOR_REPLY_ROUTING.md` |

**Provenance moved here**

| 25.0.1 lines | what |
|---|---|
| 561 | §7 'Timeouts, reaper caps and kill windows' added by the 20.0.0 ratifying edit (R3), `[VERIFIED]` 2026-10-22 heading tag dropped. |
| 746 | §7 'Operator replies, data gaps and agent numbers' added in 1.2.0 (2026-09-13) from PRs #992, #998–#1001; heading provenance dropped. |
| 1174-1176 | NO SILOS: operator binding 2026-09-29; methodology rule 1 amended by 18.0.0 (§26.7 clause); 'CRITICAL PATH, CIO-owned' heading suffix dropped. |
| 1251 | hermes_advisory_event_enqueue retired: Operator-Token APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE (Cursor chat 2026-09-20T17:15 ET; PR #1151); manual CLI kept at scripts/hermes_advisory_event_enqueue.py. |
| 800-809 | Identity spine 'CRITICAL PATH, keep it on' section added 2026-09-06 after the taxonomy_tagger outage. |

### §7A, §8, §8A, §9

| 25.0.1 lines | rule (paraphrase) | 26.0.0 location |
|---|---|---|
| 1419-1422 | Registry is the only authority; gate enforces; SOURCE_OF_TRUTH.md rendered | §7A intro |
| 1424-1436 | Why: Finviz shift, served-copy split, dead chain slots | LESSONS |
| 1440-1443 | One writer per store; WRITER_COUNT_ROSE; baseline only falls | §7A rule 1 |
| 1444-1447 | One served copy; split monitor hourly; LINKED only OK | §7A rule 2 |
| 1448-1451 | One read path via projection; DIRECT_READ_ROSE; as_of/age/source/stale | §7A rule 3 |
| 1452-1455 | Retired provider zero call sites; refuse retired slot up front | §7A rule 4 |
| 1456-1460 | Backup answers same question; no_coverage, never wrong-place value | §7A rule 5 |
| 1461-1462 | Health decays to unknown | §7A rule 6 |
| 1463-1465 | Every row carries operator approval; UNAPPROVED_SOURCE | §7A rule 7 |
| 1469-1473 | Operator instruction on grants | LESSONS |
| 1475-1479 | Registry names single writer, cadence, projection; UNCONSOLIDATED ceiling | §7A rule 1 |
| 1480-1482 | Backups per domain only | §7A rule 5 |
| 1483-1488 | Adding/replacing/retiring a source or writer is operator-only; propose, grant, record | §7A Ownership and the grant |
| 1489-1493 | Gate fails ungranted rows; UNDECLARED_PROVIDER says propose, don't add host; render --check | §7A rule 7 + Ownership + intro |
| 1494-1497 | Proposed row must meet the methodology | §7A Ownership — procedure step (1) fields |
| 1499-1501 | Why it is a rule | LESSONS |
| 1507-1511 | Procedure 1: propose registry row first and stop | §7A Ownership — procedure |
| 1512-1513 | Procedure 2: operator grants into approval | §7A Ownership — procedure |
| 1514 | Procedure 3: add projection | §7A Ownership — procedure |
| 1515 | Procedure 4: add provider markers | §7A Ownership — procedure |
| 1516-1517 | Procedure 5: re-render in same PR | §7A Ownership — procedure |
| 1518-1520 | Procedure 6: retiring reverse, archive never delete | §7A Ownership — procedure |
| 1522-1524 | PR without registry fails UNDECLARED_PROVIDER/UNAPPROVED_SOURCE | retired |
| 1526-1593 | Generated domains-of-record table | §7A Domains of record (byte-exact) |
| 1595-1601 | Divergent copies never reconciled alone; archive tripwire; phase-1 story | §7A Ownership last bullet + LESSONS |
| 1605-1611 | Operator instruction and live Schwab check | LESSONS |
| 1613-1621 | Truth table per fact | §7A Positions table |
| 1623 | Fixes doc pointer | moved:docs/ops/POSITIONS_FIXES_2026-10-06.md |
| 1625-1629 | Positions store one writer; readers gated; plan of record | §7A Positions — the positions store |
| 1631 | Enforced by test and registry gate | §7A Positions |
| 1633-1635 | No new writer of holdings.json/positions tables | §7A Positions rule 1 |
| 1636-1638 | Hold holdings_write_lock for read-modify-write | §7A Positions rule 2 |
| 1639-1640 | Compare per (account, symbol) | §7A Positions rule 3 |
| 1641-1642 | Broker basis applied when cost_basis_truth=broker | §7A Positions rule 4 |
| 1643 | No hard-coded thresholds; config file | §7A Positions rule 5 |
| 1644-1646 | Broker data only via read clients | §7A Positions rule 6 |
| 1647-1648 | Validate with portfolio_reconcile before claiming | §7A Positions rule 8 |
| 1650 | Config key changes are operator decisions | §7A Positions rule 5 |
| 1652-1662 | Config key table | moved:config/portfolio_positions.yaml |
| 1664-1667 | Keep broker leg direction; never abs(); reinvestments separate | §7A Positions rule 7 + LESSONS |
| 1667-1669 | ACATS sells outside realized; three 'today' | OPEN_ITEMS |
| 1677-1678 | Local gates per AI_WORK_POLICY §5; acceptance and status scripts | §8 Local gates |
| 1680-1683 | Gate token block | OPEN_ITEMS |
| 1685-1694 | What counts as verified, six levels | §8 What counts as verified |
| 1696-1698 | Staged proof not schedule proof | §8 What counts as verified |
| 1702-1713 | Working only after tests, dry run, forced run | §8.1 |
| 1715-1723 | Natural schedules monitored, never awaited; gates kept; n8n exception | §8.1 |
| 1725-1735 | Forced run bounds: authority, overlap, change record | §8.1 |
| 1737-1750 | Where a forced run is not allowed | §8.1 |
| 1752-1756 | Cause and operator quote | §8.1 cause line + LESSONS |
| 1760-1762 | Verify live directory; resolve CURRENT | §8 Verification traps bullet 1 |
| 1763 | Confirm merge landed | §8 Verification traps bullet 1 (rewritten) |
| 1764-1765 | Red CI may be quota block | §8 Verification traps |
| 1766-1767 | Gate must go red where it runs | §8 Verification traps |
| 1768-1774 | Guard verified by presence is not a guard | §8 Verification traps + LESSONS |
| 1775-1780 | Repairing silence not evidence of firing | §8 Verification traps + LESSONS |
| 1781-1785 | Two states cannot express no input | §8 Verification traps + LESSONS |
| 1786-1790 | Surviving mutation may be invalid | §8 Verification traps + LESSONS |
| 1791-1793 | Testing helper is not testing wiring | §8A Test the caller |
| 1794-1796 | Finviz probe both auth modes | retired |
| 1797-1803 | Schedule and gate can be disjoint | §8 Verification traps + LESSONS |
| 1804-1810 | Gate re-reads effective run | §8 Verification traps + LESSONS |
| 1811-1815 | Accepted is not delivered | §9.1 accepted is not delivered |
| 1816-1819 | Two runtime paths test the deployment | §8A Test the caller |
| 1820-1822 | Prose-reading guard passes on comments | §8A Assert on behaviour |
| 1828-1840 | Research escalation not quality-based; spill rules; free fallback | §8 Subsystem traps — Research + OPEN_ITEMS + moved:docs/architecture/RESEARCH_ESCALATION_2026-09-14.md |
| 1841-1845 | Join pending answer by id | §8 Subsystem traps — Research + moved:docs/OPERATOR_REPLY_ROUTING.md |
| 1846 | Relative paths; dry runs from CURRENT | OPEN_ITEMS + retired |
| 1847-1851 | Source pills, LEGEND, MAX_SOURCE_LABELS 16 | moved:docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md |
| 1853-1862 | Measure research queue, not adjacent store | §8 Subsystem traps — Research + moved:docs/HEALTH_AGENT.md |
| 1863-1867 | Projection writers hold projection_transaction() | §8 Subsystem traps — Research |
| 1868-1870 | retryable=True does nothing alone | moved:docs/HEALTH_AGENT.md |
| 1871-1875 | READ_ONLY guard; never loosen _EXEC_RE | §8 Subsystem traps — Research + moved:docs/architecture/GOVERNED_MODEL_BRIDGE.md |
| 1876 | Worker 'failed to start' is a request failure | moved:docs/HEALTH_AGENT.md |
| 1877-1881 | Self-healing loop real only if retries exit 0 | §8 Verification traps + LESSONS |
| 1883 | Comms idempotency key identifies one observation | §9.1 dedupe key + LESSONS |
| 1886-1889 | Finviz exports by header name | §8 Subsystem traps — Finviz |
| 1890-1893 | Finviz units; read via helpers | §8 Subsystem traps — Finviz + OPEN_ITEMS |
| 1894-1896 | Sub-one-share Schwab price is value | §8 Subsystem traps — Prices + OPEN_ITEMS |
| 1897-1903 | prevDailyBar, like-with-like, Yahoo split, IEX, rvol | §8 Subsystem traps — Prices + moved:docs/architecture/lifecycles/LIFECYCLE_FACTBASE_A_DATA_2026-09-14.md |
| 1905-1910 | Real spend vs counted vs projected; name the number | §8 Subsystem traps — Spend |
| 1911-1912 | Caps project measured cost; no worst-case pre-check | §8 Subsystem traps — Spend |
| 1913-1915 | Global cap host file loaded last; env 0.50 | §8 Subsystem traps — Spend + OPEN_ITEMS |
| 1916 | Synthetic ledger prefixes | §8 Subsystem traps — Spend |
| 1917 | Peak definition; 'always off peak' | retired (corrected in §9.3) |
| 1920-1922 | Cron does not load .env; host-file switches | §8 Subsystem traps — Cron environment |
| 1923-1925 | Calendar-day windows break on Mondays | §8 Subsystem traps — Cron environment |
| 1926-1929 | Crontab edit needs lane registry; discover_all gate | §9.3 crontab line edit |
| 1930 | Retention fk_guard | LESSONS |
| 1931 | Unit files are copies; install steps | moved:docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md |
| 1934-1937 | One Telegram chokepoint; chat-id functions | §9.1 One chokepoint + moved:docs/ops/COMMS_HUB_2026-10-07.md |
| 1938 | Orphaned-stop alerts IMMEDIATE | §9.1 Orphaned-stop |
| 1939-1943 | Communications single record; classification config; TTL lifecycle; no other deletes | §9.1 chokepoint/classification + OPEN_ITEMS + moved:docs/ops/COMMS_HUB_2026-10-07.md |
| 1944 | Watchlist standards from config; signal expires, not membership | §9.5 Watchlist |
| 1945 | Opportunities curated; no cio_theses; no behaviour keys | §9.5 Opportunities |
| 1948-1950 | Update branch by merging origin/main; never --admin | §8 Subsystem traps — Git and shell |
| 1951 | / tail hides exit code | §8 Subsystem traps — Git and shell |
| 1952 | venv first on PATH | §8 Local gates |
| 1953 | pgrep -f matches own shell | §8 Subsystem traps — Git and shell |
| 1957-1986 | ENOSPC symptoms and root cause | LESSONS + moved:docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md |
| 1969-1970 | /api/health ok is not Postgres up | §8 Verification traps — green /api/health |
| 1977-1979 | Lab Postgres :5433 separate | §8 Verification traps — green /api/health |
| 1980-1982 | Free disk is not recovered DB | §8 Verification traps — green /api/health |
| 1988-1993 | Immediate restore commands | moved:docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md |
| 1994-1996 | Do not heal PARTIAL by overwriting run_label | §8 Verification traps — green /api/health |
| 1997-2007 | Lasting controls; sudoers both paths; soft outcomes exit 0 | moved:docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md |
| 2008-2012 | Release reclaim via enforcer; keep_n and sudoers operator-gated | retired + operator_only |
| 2014-2023 | Quick verify commands | moved:docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md |
| 2033-2036 | Router WRITE_WORDS lacks trade verbs | retired (stale) |
| 2037-2038 | read_only handoff not proof of no trade ask | §8 Subsystem traps — Router (rewritten) |
| 2039-2042 | BehaviorWriteRefused not a router substitute | §8 Subsystem traps — Router |
| 2043-2045 | Fix path; live approval mode is §17 | retired + operator_only |
| 2048-2052 | Admission, partition, MCP denylist passed probes | moved:docs/agent-intelligence/THREAT_MODEL.md |
| 2053-2059 | Never claim end-to-end PI protection; agent_collab lateral surface | §8 Subsystem traps — Router + OPEN_ITEMS |
| 2060-2061 | Low-confidence route is not a jailbreak block | §8 Subsystem traps — Router |
| 2064-2070 | Failed oneshot + armed timer is churn; triage; disabling timer §17 | §8 Verification traps + OPEN_ITEMS + operator_only |
| 2073-2075 | Re-read runtime_mode; ACTIVE operator-gated | §8 Verification traps — re-read a live mode |
| 2076-2078 | Freshness ≠ RAG age; local lane availability | §8 Verification traps — re-read a live mode + moved:docs/agent-intelligence/THREAT_MODEL.md |
| 2081-2083 | Refuse unsupported claims when RAG context empty | §8 Subsystem traps — Router |
| 2084-2086 | 0% grounding flag rate is a measurement to re-check | moved:docs/agent-intelligence/THREAT_MODEL.md |
| 2088-2105 | Audit quick-verify commands | retired |
| 2109-2114 | Telegram moves typing not deciding; never type confirmation word | §8 Guard grants bullet 1 |
| 2116-2145 | Telegram request mechanism and properties | retired (superseded, fact 6) + LESSONS |
| 2147-2165 | 12-hour window and bounds | retired + history |
| 2167-2172 | Two reply paths, one settlement | retired |
| 2173-2179 | chat_id enforced, from_id metadata; keep allowlist 1:1 | §8 Guard grants last bullet (merge digest) |
| 2181-2183 | Links read-only; URL button never approval | §8 Guard grants last bullet |
| 2185-2191 | Approval request must not be routed | retired (duplicate of §9.1 P1) |
| 2193-2197 | Auditable, not impregnable; unprovenanced grants | §8 Guard grants |
| 2199-2203 | CI green covers a hand-maintained subset; re-measure | §8 Know what CI green means + OPEN_ITEMS |
| 2207-2209 | Agents cannot grant themselves; continue/deploy is not approval | §8 Guard grants bullet 1 |
| 2211-2219 | Before requesting: root, guard path, proofs, validation, reasons | §8 Guard grants bullet 3 |
| 2221-2228 | Absolute guard path only | §8 Guard grants bullet 3 |
| 2230-2238 | Minimum scopes; forbidden scopes | §8 Guard grants bullet 4 |
| 2240-2241 | Operator types APPROVE; agent never automates it | §8 Guard grants bullet 1 |
| 2243-2249 | Short expiry, few uses, grant examples | §8 Guard grants bullet 3 (git-push example; release-write retired) |
| 2251-2258 | Show and verify grant; mismatch is hard stop | §8 Guard grants bullet 5 |
| 2260-2263 | Push and deploy separate stages; deploy exact merge SHA | §8 Guard grants bullet 4 + retired |
| 2265-2268 | Live deployment acceptance and auto rollback | retired (superseded by §25.10) |
| 2270-2279 | Path-resolution example | retired (duplicate) |
| 2281-2288 | Revoke unused grants in cleanup | §8 Guard grants bullet 5 |
| 2290-2292 | Evidence package receipts, no secrets | §8 Guard grants bullet 5 |
| 2294-2295 | release-write names SHA/PR | retired (superseded) |
| 2297-2298 | Absent guard: stop and report | §8 Guard grants bullet 3 |
| 2304 | Tests never touch production state | §8A intro |
| 2308-2311 | Every test file registered in CI | §8A bullet 1 |
| 2312-2314 | Assert on behaviour, not source strings | §8A bullet 2 |
| 2315-2316 | Expected value from artifact validates nothing | §8A bullet 3 |
| 2317-2320 | Pin floors, not adjudications | §8A bullet 3 |
| 2321-2324 | Mutation-test every guard | §8A bullet 4 |
| 2325-2328 | Positive-control detectors before a zero | §8A bullet 5 |
| 2329-2332 | Preserve-on-failure test | §8A bullet 6 |
| 2333-2335 | Skipped test is a failure | §8A bullet 7 |
| 2341-2342 | SOP preamble | retired |
| 2346-2347 | Notification model is §24.1 | §9.1 intro |
| 2349-2351 | Dedupe key with content and declared window | §9.1 dedupe key |
| 2352-2353 | Confirm digest suppression before batch | §9.1 |
| 2354-2355 | Never send internal policy text | §9.1 |
| 2356-2358 | Provenance and as_of per field; oldest balance | §9.5 bullet 1 |
| 2359-2360 | Nothing changed today is required | §9.1 |
| 2361-2362 | Failure must reach a surface | §9.1 |
| 2363-2364 | No template in a judgment register | §9.1 |
| 2365-2366 | Test sends need operator word; protect dedupe marker | §9.1 + operator_only |
| 2370-2376 | Accepted is not delivered; three words; default None | §9.1 |
| 2377-2380 | Every call site passes what it knows; guard scoped to module | §9.1 + LESSONS |
| 2381-2391 | Operator-action is P1 intent with dedupe off | §9.1 |
| 2392-2401 | bypass_router legacy, allowlisted, shrink-only; broker senders | §9.1 + OPEN_ITEMS |
| 2402-2407 | P2 held in quiet window, never dropped | §9.1 |
| 2408-2411 | Alerts curated; model writes prose only | §9.1 |
| 2412-2415 | Curation model order fixed; local never | §9.1 |
| 2416-2420 | Every alarm has a mutation-tested firing test | §9.1 |
| 2421-2422 | Alarm-path imports resolve | §9.1 |
| 2423-2425 | No bare except on alarm path | §9.1 |
| 2426 | Health check no-input verdict | retired (duplicate of §8 trap) |
| 2427-2432 | Operator-surface stores declare cadence/output_signal; one monitor | §9.1 |
| 2433-2435 | Log-only verdict has not reached operator; SILENT debt | §9.1 + OPEN_ITEMS |
| 2436-2440 | One chokepoint; bypass needs reason, CI-gated | §9.1 One chokepoint |
| 2441-2444 | Every send records a durable receipt | §9.1 |
| 2445-2454 | settle_delivery persists ownership coordinates | §9.1 + history |
| 2455-2458 | Absent field never affirmative | §9.1 |
| 2459-2462 | Computed completeness verdict is rendered | §9.1 |
| 2463-2466 | Silent request-changing retry is a swallow | §9.1 |
| 2467-2470 | Notify on transitions | §9.1 |
| 2474-2479 | Long answers as ordered parts | §9.1 + moved:docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md |
| 2480-2482 | Undelivered reply is a finding | §9.1 |
| 2483-2490 | Rich alert layout; symbols from producer | moved:docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md |
| 2491-2492 | Provenance collapsed | moved:docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md |
| 2496-2497 | Free-first | §9.2 |
| 2498-2499 | Lane per §12; probe live | §9.2 |
| 2500-2501 | Record measured cost, tier, cache hit | §9.2 |
| 2502 | Budget before call; never fail open | §9.2 |
| 2503 | Cron in UTC | §9.2 (corrected: Eastern cron + UTC-peak wrapper) |
| 2504-2505 | No bare except on model path | §9.2 |
| 2506-2507 | Generated fields labelled; writer is author | §9.2 |
| 2508-2517 | Bridge caller names itself; new caller checklist | §9.2 |
| 2518-2524 | Bridge answers while in flight; deadlines; watchdog | moved:docs/architecture/GOVERNED_MODEL_BRIDGE.md |
| 2525-2527 | Stall: look at bridge first; restart once | §9.2 |
| 2528-2531 | Logged cost checked against provider | §9.2 |
| 2535 | Scheduled job never pushes (§24.5) | §9.3 intro |
| 2537-2538 | Lane registry row with output_signal before install | §9.3 |
| 2539-2544 | Scheduler entries operator-only; n8n workflow and dispatcher row | §9.3 + operator_only |
| 2545-2546 | Dry-run under exact cron form from pinned release | §9.3 |
| 2547 | Verify both schedulers | §9.3 |
| 2548-2551 | Retirement carries reason; n8n-cutover form | §9.3 |
| 2552-2554 | Natural-schedule evidence; forced run first | §9.3 |
| 2555-2558 | Data-source lanes declare credentials | retired (duplicate of §13.6) |
| 2560-2565 | Crontab line edit is lane registry edit | §9.3 |
| 2566-2579 | Scheduled paid work in operator window; wrapper; timers; cadence; deferral | §9.3 |
| 2580-2582 | Backfill is scheduled work | §9.3 |
| 2586 | One declared writer per store | §9.4 |
| 2587-2588 | Byte snapshot; additive only | §9.4 |
| 2589 | Holdings through protected_holdings_write() | §9.4 |
| 2590 | Never merge divergent copies | retired (duplicate of §0 rule 5) |
| 2591-2592 | Fix path resolution at resolution layer | §9.4 |
| 2593-2594 | Writes land on served path | §9.4 |
| 2595-2605 | Writers resolve via persistent_state_root helpers | §9.4 + moved:docs/ops/CANONICAL_OBSERVATION_CONTRACT.md |
| 2609 | Provenance class at display | §9.5 |
| 2610 | as_of per block | §9.5 |
| 2611-2612 | One producer per number | §9.5 |
| 2613-2615 | Constant field is not judgment | §9.5 |
| 2616 | Provenance row before new field ships | §9.5 |

**Retired**

| 25.0.1 lines | reason |
|---|---|
| 1424-1436 | history: incident narrative → LESSONS L7A-01 |
| 1469-1473 | history: operator instruction verbatim → LESSONS L7A-02 |
| 1499-1501 | history: rationale → LESSONS L7A-02 |
| 1522-1524 | duplicate of §7A rule 7 and the UNDECLARED_PROVIDER bullet |
| 1605-1611 | history: incident narrative → LESSONS L7A-04 |
| 1613 | stale: 'today (plan phase 1, shadow)' — plan Status table shows phase 3 batch 1 approved 2026-10-22 |
| 1627-1628 | stale: 'Nothing reads them' — positions_store approved_readers[batch 1] (Watch held flag) exists in config/data_source_authority.json |
| 1664-1669 | known gaps → OPEN_ITEMS (ACATS, 'today'); fixed defect narrative → LESSONS L7A-05; rule kept as §7A positions rule 7 |
| 1680-1683 | stale: tokens emitted by no script (AI_WORK_POLICY.md §5 keeps them) → OPEN_ITEMS |
| 1752-1756 | history: cause narrative and operator quote → LESSONS L8-09; one-line cause kept |
| 1763 | stale: assumed agents run `gh pr merge`; superseded by §25.10 — rewritten as 'confirm a merge landed on origin/main' |
| 1794-1796 | duplicate of §7 Finviz trap (old 540-543) and §13.6 |
| 1811-1815 | duplicate of §9.1 'accepted is not delivered' |
| 1846 | stale: 'run dry runs from CURRENT' contradicts §9.3 (pinned release, never CURRENT); relative-path defect → OPEN_ITEMS |
| 1889 | describes enforcing code (finviz_csv.VIEW_CONTRACTS, check_finviz_view_contracts.py 06:05) — moved with 1886-1889 |
| 1917 | stale: 'always off DeepSeek peak' contradicts §12 (window touches peak Sun 21:00-24:00 ET and winter 20:00-21:00) and deepseek_offpeak.is_scheduled_deepseek_window; corrected rule is §9.3 |
| 1926-1929 | duplicate of §9.3 'A crontab line edit is a lane registry edit' (merged there) |
| 1930 | describes shipped code (scripts/db_retention.py fk_guard); no agent instruction → LESSONS L8-14 |
| 1950 | 'Never --admin' superseded by §25.10 (agents never merge) |
| 2008-2012 | superseded by §24.12 / brief fact 9: release reclaim is scripts/disk_hygiene.py only; disk_hygiene_enforcer.py removes nothing; operator-only parts → operator_only[] |
| 2033-2036 | stale: scripts/agent_router.py WRITE_WORDS and _TRADE_WRITE_RE (lines 44-68) include buy/sell/order/trade verbs and force multi-agent review (lines 386-401) |
| 2043-2045 | stale: the fix path shipped (trade verbs → pending_write + risk_agent/steph/orchestrator reviewers) |
| 2088-2105 | history: quick-verify command block from the 2026-09-18 audit; its router comment is stale; the rules are kept in §8 traps |
| 2107-2146 | superseded: Telegram remote grants retired (brief fact 6); still-true parts (never type the confirmation word; auditable not impregnable) kept in §8 Guard grants |
| 2147-2165 | superseded/history: 12-hour remote window (Telegram grants retired) |
| 2167-2172 | superseded: Telegram button settlement for guard grants retired |
| 2185-2191 | duplicate of §9.1 (P1 intent, accepted-not-delivered) |
| 2193-2197 | Telegram provenance retired; 'auditable, not impregnable' kept in §8 Guard grants |
| 2201-2203 | stale number: '59 of 1,027 test files — 5.74%' — 2026-10-27 measure 1,500 of 2,425 registered → OPEN_ITEMS |
| 2216 | superseded by §25.10: agents prove no deployment target or rollback release |
| 2233 | superseded by §25.10 (brief fact 3): agents never request release-write |
| 2248 | superseded by §25.10: release-write grant example |
| 2260-2263 | superseded by §25.10: agent deployment of the exact merge SHA; 'git-push never authorizes merge or deployment' kept |
| 2265-2268 | superseded by §25.10: the poller promotes and runs post_release_tester; rollback is an operator decision (brief fact 3) |
| 2270-2279 | duplicate of §8 Guard grants bullet 3 (absolute guard path) |
| 2286 | superseded: `revoke release-write` (agents never hold it) |
| 2294-2295 | superseded by §24.8/§25.10: release-write binding applies to the operator's emergency path only |
| 2341-2342 | preamble, no rule |
| 2426 | duplicate of §8 trap 'Two states cannot express no input' |
| 2433-2435 | SILENT-verdict gap → OPEN_ITEMS; rule 'a failure reaches a surface, not just a log' kept in §9.1 |
| 2503 | stale: 'Cron in UTC' — host crontab/timers are Eastern (TRADEAI_CRON_TZ default America/New_York); rewritten per coordinator fact |
| 2541-2542 | stale: §23.13 standing merge approval expired 2026-10-11T17:30:03-04:00; merges are §25.10 |
| 2555-2558 | duplicate of §13.6 Finviz credentials |
| 2574-2579 | 'refused call is QUEUED, not dropped' corrected (wrapper PEAK_SKIP drops); lane cron expression and install narrative → LESSONS L9-13 |
| 2590 | duplicate of §0 rule 5 |
| 2076-2078 | narrow measurement caveat; covered by §8 trap 'Re-read a live mode before stating it' and moved to THREAT_MODEL.md |

**Moved to the document that owns the subject**

| 25.0.1 lines | to |
|---|---|
| 1623 | `docs/ops/POSITIONS_FIXES_2026-10-06.md` |
| 1652-1662 | `config/portfolio_positions.yaml` |
| 1830-1833 | `docs/architecture/RESEARCH_ESCALATION_2026-09-14.md` |
| 1834-1838 | `docs/architecture/RESEARCH_ESCALATION_2026-09-14.md` |
| 1839-1840 | `docs/architecture/RESEARCH_ESCALATION_2026-09-14.md` |
| 1841-1845 | `docs/OPERATOR_REPLY_ROUTING.md` |
| 1847-1851 | `docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md` |
| 1853-1862 | `docs/HEALTH_AGENT.md` |
| 1863-1870 | `docs/HEALTH_AGENT.md` |
| 1871-1875 | `docs/architecture/GOVERNED_MODEL_BRIDGE.md` |
| 1876 | `docs/HEALTH_AGENT.md` |
| 1877-1881 | `docs/HEALTH_AGENT.md` |
| 1886-1889 | `docs/architecture/lifecycles/LIFECYCLE_FACTBASE_A_DATA_2026-09-14.md` |
| 1897-1903 | `docs/architecture/lifecycles/LIFECYCLE_FACTBASE_A_DATA_2026-09-14.md` |
| 1905-1916 | `docs/LLM_SPEND.md` |
| 1931 | `docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md` |
| 1933-1943 | `docs/ops/COMMS_HUB_2026-10-07.md` |
| 1944 | `docs/ops/WATCH_DECISION_STANDARDS_2026-10-08.md` |
| 1945 | `docs/ops/INVESTMENT_COMMAND_CENTER_2026-10-08.md` |
| 1955-2023 | `docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md` |
| 2047-2061 | `docs/agent-intelligence/THREAT_MODEL.md` |
| 2072-2086 | `docs/agent-intelligence/THREAT_MODEL.md` |
| 2474-2492 | `docs/cio/CIO_TELEGRAM_PRODUCT_STANDARD.md` |
| 2518-2524 | `docs/architecture/GOVERNED_MODEL_BRIDGE.md` |
| 2595-2605 | `docs/ops/CANONICAL_OBSERVATION_CONTRACT.md` |

**Provenance moved here**

| 25.0.1 lines | what |
|---|---|
| 1420 | `[VERIFIED]` 2026-09-13 tag on the registry rule |
| 1595-1601 | Served-copy reconcile phase 1 (2026-09-13): dry run quoted, operator-approved merge rule, receipt and archive paths |
| 1603 | `[VERIFIED]` 2026-10-06 tag on the positions heading |
| 1700 | §8.1 heading suffix '(binding from 25.0.0)' |
| 1823-1825 | 'What 2026-09-14 taught' banner (PRs #1006–#1009) |
| 1955 | 'What 2026-09-18 taught — Postgres ENOSPC' banner (PR #1068) |
| 2025-2030 | Agent controls audit 2026-09-18 banner: Pilot Ready (17/30) on CURRENT 2d4b6c0f0 |
| 2107-2197 | Remote approval by Telegram (2026-09-06 → retired by the 23.0.0 ratification 2026-10-26, APPROVE_AGENTS_POLICY_23_0_0 2185 c366dd8d1, PR #2185): request/settle split, SHA-256-only codes, 4 h answer deadline, REMOTE_FORBIDDEN_SCOPES, 12 h / 500-use ceilings raised 2026-09-06, button settlement proven 28e47322a7 and 7f112670b7 |
| 2189-2191 | 'Under 5.1.0 that bypass is an allowlisted legacy site (§9.1)' bookkeeping |
| 2294-2295 | ReleaseGrantBinding@v1 pointer '§24.8 (4.6.0, ACTIVE)' |
| 2304,2346-2347,2535 | '(4.6.0, ACTIVE)' tags on §24.6, §24.1 and §24.5 pointers |
| 2368 | 'The delivery ledger must say what happened — added 2026-09-05' subheading |
| 2381 | '(5.1.0)' tag on the P1 intent bullet |
| 2452-2454 | settle_delivery rule operator-approved for inclusion 2026-09-09 (live ceiling); proposed text evidence/proposed/AGENTS_MD_AMENDMENT_DELIVERY_OWNER_STAMP.md; landed PR #926 |
| 2472 | 'Replies and alerts on the phone — added 2026-09-14' subheading |
| 2541-2542 | §23.13 standing merge approval clause (expired 2026-10-11T17:30:03-04:00) |

### §12, §13, §17A, §18

| 25.0.1 lines | rule (paraphrase) | 26.0.0 location |
|---|---|---|
| 2689 | Global cap = 2.00, ratified | §12 The daily provider spend cap |
| 2692-2694 | Free-first is the order of operations | §12 The daily provider spend cap |
| 2696-2701 | Refused search rescued by free provider; free metered | LESSONS L12-03; §12 Search providers (one ledger, free included) |
| 2702-2703 | Thin free answer does not escalate | OPEN_ITEMS |
| 2707-2708 | Enforcement partial; say so | §12 not a universally enforced control |
| 2710-2715 | Cap enforcement measurement table | OPEN_ITEMS / retired |
| 2719-2725 | Risk/steph request caps raised | history; LESSONS L12-10 |
| 2727-2731 | Cost cap binds; throughput binds first | LESSONS L12-10; OPEN_ITEMS |
| 2735-2742 | DeepSeek 402 outage narrative | LESSONS L12-01 |
| 2744-2748 | Cap consumption is not evidence of work | §12 Cap consumption is not evidence of work |
| 2753-2764 | Provider-health monitor pages billing/auth; heartbeat every run | §12 Cap consumption is not evidence of work |
| 2765-2768 | OAuth fallback for risk/steph/tax after Flash fails | §12 (OAuth never silently pre-empts governed Flash) |
| 2770-2773 | Pre-empt Maria-only; fallback is degradation; provenance kept | §12 (condensed); retired detail |
| 2775-2777 | Most lanes run with global cap unset | §12 (restated from code); OPEN_ITEMS |
| 2779-2782 | $2.00 not universally enforced; named debt | §12 The daily provider spend cap |
| 2786-2797 | Provenance of the number | history; LESSONS L12-02; moved:docs/LLM_SPEND.md (already there) |
| 2802-2809 | Lane table | §12 Lanes |
| 2811-2814 | Selection: free-first, Ollama structural, OAuth peak/critique, flash default | §12 Lanes (Selection) |
| 2814-2815 | Pro binds to flash; v4-pro legacy | §12 deepseek-flash is the only DeepSeek model id |
| 2817 | Never route on readiness flag; probe live | §12 Lanes |
| 2821-2822 | Prices change; re-verify, never quote from memory | §12 DeepSeek pricing and scheduling |
| 2824-2825 | Peak hours UTC weekdays; off-peak half rate | §12 DeepSeek pricing and scheduling |
| 2827-2836 | ET conversion table; trading day off-peak | moved:docs/LLM_SPEND.md |
| 2838-2840 | Never schedule on local-time cron; schedule in UTC | §12 Host cron and timer expressions are Eastern (rewritten per fixed fact) |
| 2842-2850 | Rates table | moved:config/llm_model_registry.json (flash); v4-pro retired |
| 2852-2854 | Caching is the larger lever | §12 Get caching right before scheduling |
| 2856-2857 | Report a cap that starves a lane | §12 If a cap leaves a lane unable to run meaningfully |
| 2859-2864 | Operator window 09:00-21:00 ET weekdays/weekends | §12 Scheduled paid work runs weekdays 09:00-21:00 ET |
| 2865-2867 | Also refused inside DeepSeek peak (two crossings) | §12 Scheduled paid work ... |
| 2868-2871 | In-process gate queues | §12 Two gates, and only one queues |
| 2872-2883 | Process-boundary wrapper drops; defer-in-process; open migration | §12 Two gates; OPEN_ITEMS |
| 2882-2883 | should_scheduled_skip not dead code | retired detail (wrapper doc); §12 keeps the drop rule |
| 2884-2890 | Out-of-window work queued; drainer required | §12 Two gates (A queue is honest only while drained via llm-deferred-drain); LESSONS L12-04 |
| 2891-2894 | Three tiers; standard default | §12 Tiers per process_id |
| 2894-2897 | Nothing critical today | OPEN_ITEMS / retired |
| 2898-2904 | Armed for every cron line; systemd per unit | §12 Arming |
| 2907-2913 | Blast radius; arming is operator's call | LESSONS L12-11; §12 Arming; operator_only |
| 2914-2915 | Urgent operator-requested work exempt | §12 Scheduled paid work ... exempt |
| 2916-2918 | Measured before the rule | LESSONS L12-05 |
| 2922-2924 | Budget state persists to disk/DB per provider | §12 One ledger |
| 2924-2925 | Web search serves residual-web lane, not bulk news; degraded pool said | §12 Web search serves the residual-web lane |
| 2927-2940 | Engine pool table | moved:docs/RESEARCH_PROVIDER_ROUTING.md; LESSONS L12-07 |
| 2942-2945 | brave vs braveapi; monthly 0 means unmetered | §12 braveapi bullet (unmetered note dropped to moved doc) |
| 2946-2948 | inactive: separate from disabled: | §12 braveapi bullet |
| 2949-2950 | Rank on a real query | §12 braveapi bullet |
| 2951-2956 | Change pool only via install_searxng_config.sh | §12 braveapi bullet; LESSONS L12-07 |
| 2957-2958 | braveapi bypasses lib/search_budget | §12 braveapi bullet; OPEN_ITEMS |
| 2962-2966 | One ledger; second counter removed; ceilings from headers | §12 One ledger; LESSONS L12-06 |
| 2968 | Search routing/Brave budget: §24.2 | §12 Routing and the Brave dollar budget: §24.2 |
| 2977 | One canonical source of truth per concept | §13 |
| 2978 | No concurrent edits to shared files | §13 |
| 2979 | No frontend business logic | §13 |
| 2980-2981 | Every claim has ref, test, evidence class, repro | §13 |
| 2982 | Read-only by default | §13 |
| 2983 | Agents commit locally and hand off SHA; integrator reviews | §13 (rewritten: merge per §25.10); OPEN_ITEMS (INTEGRATION_RULES.md) |
| 2985-2988 | Hook-enforced hard rules; install hooks; verify | §13 Hook-enforced standards |
| 2992-2993 | Read vocabulary before proposing new type | §13.4 |
| 2995-3009 | Registered id types; option ids not new types | §13.4 Registered id types; history |
| 3011-3033 | Narrative subject identity cause; no new id type; tags not records | §13.4 Narrative subject identity; LESSONS L13-02 |
| 3035-3043 | Subject type namespace table | moved:docs/architecture/narrative-subject-identity.md (already there) |
| 3045-3064 | Six narrative identity rules | §13.4 (rules 1-3,6 condensed); moved:narrative-subject-identity.md (all six already there) |
| 3066-3088 | What each lane must stamp | moved:docs/architecture/narrative-subject-identity.md |
| 3091-3102 | Subject-key namespace | §13.4 Subject keys |
| 3104-3111 | Records vs tags; INDUSTRY/THEME tags by decision; no producer for a tag | §13.4 Subject keys; LESSONS L13-04; operator_only |
| 3113-3140 | InstrumentRecord@v1 fields | §13.4 InstrumentRecord@v1 (condensed); moved:docs/ops/INSTRUMENT_RECORD_V1.md |
| 3142-3144 | Loaded on every wake; ack writes back; checkpoints bind by subject_key/guid | §13.4 InstrumentRecord@v1 |
| 3146-3167 | Pipeline stages - extend, don't build alongside | §13.4 Pipeline stages; moved:docs/ops/INSTRUMENT_RECORD_V1.md |
| 3169-3182 | Artifact types incl. AgentView/AGENT_COMMITMENT | §13.4 Artifact types; moved:docs/ops/INSTRUMENT_RECORD_V1.md |
| 3184-3186 | AgentView/commitment have scheduled producers; extend AEC writers | §13.4 Artifact types |
| 3188-3196 | Provenance classes | §13.4 Provenance classes |
| 3198-3207 | Cognition boundary | retired (duplicate of §2); §13.4 pointer |
| 3209-3214 | Dark contracts definition; re-measure | §13.4 Dark contracts are not LIVE |
| 3218-3220 | CIO_TELEGRAM_INTERDICT is not the send gate | §13.4 Dark contracts; OPEN_ITEMS |
| 3222-3233 | Formerly dark - closed; do not rebuild | moved:docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md (already there); OPEN_ITEMS (hermes enqueue) |
| 3235-3244 | Before proposing anything new: five questions; PR incomplete without statement | §13.4 Before proposing anything new |
| 3248-3253 | Failure this prevents | LESSONS L13-01 |
| 3255-3257 | Unwired is not absent; wire it | §13.5 |
| 3259-3264 | Step 0 Read §13.4; extend exact match | §13.5 step 0 |
| 3265 | Read the documentation index | §13.5 step 1 |
| 3266-3267 | Search capability not filename | §13.5 step 2 |
| 3268-3270 | State ruled-out questions in PR | §13.5 step 6 |
| 3271-3272 | Check the registries | §13.5 step 3 |
| 3273-3274 | Check the dark inventory | §13.5 step 4 |
| 3275-3276 | Check archive/ and manifest | §13.5 step 5 |
| 3280-3285 | Record the search in PR body | §13.5 step 6 |
| 3289-3293 | Exists wired/unwired/wrong/nothing rules | §13.5 Then (delete-original fixed to archive) |
| 3299-3300 | Read before touching Finviz; RCA pointer | §13.6 |
| 3302-3312 | Two Finviz credentials; token backstop for screeners | §13.6 Screener path / Enrichment path |
| 3314-3323 | Screener vs enrichment path; green on one proves nothing | §13.6 |
| 3325-3332 | social_ingest vs social_scalp gate | §13.6 |
| 3334-3339 | Auto-remediation same store only | §13.6 Remediate only the store the detector read |
| 3341-3348 | Cache heal trap | §13.6 heal_trade_ai_session_cache.py; LESSONS L13-03 |
| 3354-3358 | Renumbering note | history |
| 3360-3366 | Who consumes it | §13.7 |
| 3367-3368 | What proves it ran | §13.7 |
| 3369-3370 | Which layer | §13.7 |
| 3371-3372 | Dry run for writes/sends/spend | §13.7 |
| 3373 | Number carries as_of and root | §13.7 |
| 3374 | Operator surface: provenance + as_of | §13.7 |
| 3375-3376 | Restriction read by code, tested | §13.7 |
| 3377-3378 | No silent failure | §13.7 |
| 3565-3566 | Orientation: several trees | §17A intro; LESSONS L17A-09 |
| 3570-3572 | Design pointer; stages; advisory only | §17A Material-change intelligence; OPEN_ITEMS (status) |
| 3574-3577 | Gap it closes | LESSONS L17A-01 |
| 3579-3584 | Script/contract table | §17A (named inline); moved:MATERIAL_CHANGE_TO_QUESTIONS.md (already there) |
| 3586-3588 | Stages 0-2 free; no model; test enforces | §17A Detection uses no model |
| 3590-3593 | Loop closed | LESSONS L17A-01 |
| 3595-3600 | Two lane policies; never unify | §17A Two lane policies |
| 3602-3615 | Bake-off measurements | moved:MATERIAL_CHANGE_TO_QUESTIONS.md; LESSONS L17A-05 |
| 3617-3620 | Curation inverted; ASK the operator hard stop | §17A Two lane policies; history |
| 3622-3633 | Research lanes ranked never hardcoded | §17A Two lane policies; LESSONS L17A-05 |
| 3637-3639 | Coverage decays; */30 sweep | §17A Coverage decays |
| 3640-3642 | identity_status NULL vs UNRESOLVABLE | §17A Coverage decays bullet |
| 3643-3645 | Topics are subjects, not securities | §17A Topics are subjects |
| 3646-3649 | Average daily move not ATR | §17A The baseline is average daily move |
| 3650-3651 | No fixed percent threshold; K tunable | §17A The baseline bullet |
| 3652-3655 | A NaN fires | §17A A NaN fires; LESSONS L17A-04 |
| 3656-3660 | ACCEPTED is not DELIVERED | §17A; LESSONS L17A-03 |
| 3661-3663 | material_change IMMEDIATE, not CRITICAL_IMMEDIATE_TYPES | §17A |
| 3664-3665 | Held is not dropped | §17A (material_change bullet) |
| 3666-3669 | Inherit detector's rejections | §17A; LESSONS L17A-02 |
| 3670-3674 | Grounding enforced in code | §17A Grounding |
| 3675-3677 | Strip own scoring | §17A Grounding bullet |
| 3678-3679 | Routing must not depend on new changes | §17A Routing never waits |
| 3680-3682 | Stamp answer onto the spine | §17A Routing bullet |
| 3683-3685 | PRECEDENCE tiers | §17A PRECEDENCE (values in material_change_detector.py) |
| 3686-3691 | Cap check in caller's process | §17A; §12; LESSONS L17A-06 |
| 3692-3695 | SAVEPOINT for optional probes | §17A; LESSONS L17A-08 |
| 3696-3698 | CREATE TABLE IF NOT EXISTS adds no columns | §17A |
| 3699-3701 | Addressable, append-only, uuid5 | §17A |
| 3705-3709 | Cost; cap refusal degrades, does not fail | §17A (cap bullet); moved:MATERIAL_CHANGE_TO_QUESTIONS.md (already there) |
| 3713-3720 | Trees table | §17A The trees (rewritten, deploy worktree removed, no counts) |
| 3722-3723 | Never quote CURRENT as identifier | §17A The trees |
| 3725-3727 | Four trees, four answers; wrong tree is not a write | §17A The trees |
| 3729-3744 | Glossary | §17A Glossary |
| 3752-3757 | Services; JSON-only mode | §18 Services, build and test |
| 3761-3766 | Lint/test/build commands | §18 Services, build and test |
| 3770-3771 | Holdings write guard MIN_TOTAL | §18 Gotchas (rewritten to holdings_sanity) |
| 3772 | Endpoints cache ~60s | §18 Gotchas (number dropped); OPEN_ITEMS |
| 3773-3776 | CC v3 stale-bundle reload | §18 Gotchas |
| 3777-3778 | Hot-reload only api_v2/reports_portal | §18 Gotchas |
| 3779 | Minimal .env for local dev | §18 Services, build and test |
| 3783-3787 | Repository stays public; budget before private | §18 Repository visibility is a CI invariant; LESSONS L18-01 |
| 3791-3793 | Pipeline writes canonical, server reads release; symlinks | §18 Data freshness |
| 3795-3800 | DATA_DIRS_TO_LINK list and gaps | §18 Data freshness; OPEN_ITEMS |
| 3802-3806 | Check last_repriced first; CRITICAL at 7 days | §18 Data freshness |
| 3808-3812 | Never copy state into release; symlink check; snapshot cache | §18 Data freshness / Gotchas (rewritten per §0 rules 5-6) |
| 3818-3822 | .env tmpfs, render_env, hand edit lost | §18 Operational realities; LESSONS L18-02 |
| 3823-3828 | Backups do not cover persistent-state; operator decision | §18 Operational realities; OPEN_ITEMS; operator_only; LESSONS L18-03 |
| 3829-3833 | Archive mechanism; never archive on single observation; UNKNOWN waits | §18 Operational realities |

**Retired**

| 25.0.1 lines | reason |
|---|---|
| 2688-2690 | code block replaced by a sentence keeping the pinned phrases; provenance to history |
| 2696-2703 | history: first live proof moved to LESSONS L12-03; remaining debt to OPEN_ITEMS |
| 2705-2715 | stale counts (30 caps / $18.05; registry now 71 caps / $107.95 on 2026-10-27); gap to OPEN_ITEMS |
| 2717-2731 | history + LESSONS L12-10; throughput gap to OPEN_ITEMS |
| 2733-2748 | incident narrative moved to LESSONS L12-01 |
| 2753-2764 | stale: lane llm-provider-health RETIRED 2026-10-07, the script now runs as a health-tick step; paging detail lives in scripts/lib/provider_health.py |
| 2770-2773 | Maria-only pre-empt detail condensed; LEGACY_WATCH_RESEARCH_NON_PROFESSIONAL provenance lives in process_watchlist_agent_jobs.py |
| 2775-2777 | stale: '78 of 84 fall back to per-process cap' is true only for bridge callers; the in-process path refuses (validate_paid_cap_config); restated from code |
| 2784-2797 | history |
| 2809, 2814-2815 | stale contradiction: deepseek-v4-pro listed as a lane and as rejected; code: EXACT_DEEPSEEK_MODELS={'deepseek-flash'}, deepseek-v4-pro rejected as model id, alias for PRO only |
| 2838-2840 | superseded: host cron is Eastern (TRADEAI_CRON_TZ); UTC peak enforced at run time by run_with_deepseek_offpeak.sh (coordinator fixed fact) |
| 2844-2850 | stale: deepseek-v4-pro column ('listed; not called') - Pro tier retired; flash rates and concurrency are in config/llm_model_registry.json |
| 2861-2862 | operator quote moved to history (LESSONS L12-05); rule kept |
| 2870 | stale line ref lib/llm_consumption.py:1109 (gate_and_generate is at scripts/lib/llm_consumption.py:1221); cite function names |
| 2876-2881 | dated counts moved to OPEN_ITEMS |
| 2894-2897 | stale: registry now declares offpeak_tier=critical for n8n_lane_failure_diagnosis; verification to OPEN_ITEMS |
| 2905-2913 | history + LESSONS L12-11 |
| 2916-2918 | measurement moved to LESSONS L12-05 |
| 2942-2956 | engine detail moved to docs/RESEARCH_PROVIDER_ROUTING.md; rules kept in §12 |
| 2968 | '(4.6.0, ACTIVE)' pointer replaced by plain §24.2 pointer |
| 2975 | provenance line dropped ('From docs/convergence/INTEGRATION_RULES.md') |
| 2983 | superseded by §25.10 ('the integrator reviews before merge') |
| 3198-3207 | duplicate of §2 (MBI_BEHAVIOR/BehaviorWriteRefused/MBI_COGNITION/CognitionNoOp) |
| 3283-3285 | worked example dropped; the rule (record the search) kept in §13.5 step 6 |
| 3268-3271 | duplicate step number '3.' fixed; merged into §13.5 step 6 |
| 3291 | contradicted §0 rule 6 ('delete the original in the same PR'); now 'retire by archive with a tripwire (§26.6)' |
| 3354-3358 | history |
| 3586-3593 | history/LESSONS L17A-01 |
| 3690-3691 | resolved against §12: true for the in-process path (gate_and_generate refuses), not for bridge callers; stated once in §12 |
| 3716 | stale: deploy worktree ~/r20-r24-exact-main-deploy no longer used; poller runs with --repo ~/trade-ai-v12-rebuild/trade-ai-v12-rebuild (config/systemd/user/tradeai-deploy-on-main.service) |
| 3717, 3718, 3720 | dated counts removed (249 releases, rotated three times, 303 worktrees) |
| 3770-3771 | stale: MIN_TOTAL=1_000_000 gone; scripts/lib/holdings_sanity.py validate_payload |
| 3772 | unverified ~60s cache number dropped; see OPEN_ITEMS |
| 3795-3796 | stale: deploy now via cio_phase2_exact_main_deploy.sh link_pipeline_data with persistent-state overlay; five-directory list outdated |
| 3804-3806, 3811-3812 | duplicate 7-day holdings warning stated twice; kept once |
| 3809-3811 | remediation 'remove and re-link' and 'delete portfolio_snapshot.json' conflict with §0 rules 5 and 6; replaced by report-both-paths and wait-out-the-cache |
| 3821-3822 | stale: trigger is tradeai-sm-render.timer (lane sm-render) |
| 3829 | stale: 'when it is built' - scripts/cio_archive_mechanism.py, archive/ARCHIVE_MANIFEST.json and scripts/lib/retention_tripwire.py exist |

**Moved to the document that owns the subject**

| 25.0.1 lines | to |
|---|---|
| 2827-2833 | `docs/LLM_SPEND.md` |
| 2842-2850 | `config/llm_model_registry.json` |
| 2927-2958 | `docs/RESEARCH_PROVIDER_ROUTING.md` |
| 2960-2966 | `docs/RESEARCH_PROVIDER_ROUTING.md` |
| 3035-3064 | `docs/architecture/narrative-subject-identity.md` |
| 3066-3088 | `docs/architecture/narrative-subject-identity.md` |
| 3113-3144 | `docs/ops/INSTRUMENT_RECORD_V1.md` |
| 3146-3182 | `docs/ops/INSTRUMENT_RECORD_V1.md` |
| 3188-3196 | `docs/architecture/DECISION_PROVENANCE_MATRIX.md` |
| 3222-3233 | `docs/audits/DARK_PARTIAL_CLOSURE_LEDGER_2026-09-19.md` |
| 3302-3348 | `docs/audits/STALE_DATA_RCA_AND_REMEDIATION_PLAN_2026-09-01.md` |
| 3579-3584 | `docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md` |
| 3602-3633 | `docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md` |
| 3703-3709 | `docs/architecture/MATERIAL_CHANGE_TO_QUESTIONS.md` |
| 3777-3778 | `OPERATIONS.md` |

**Provenance moved here**

| 25.0.1 lines | what |
|---|---|
| 2689 | Global cap history: 0.25 -> 0.50 (2026-08-12, attributed in llm_process_registry change notes, operator-ratified 2026-09-01) -> 2.00 of actual spend (ratified 2026-09-14). |
| 2784-2797 | Provenance of the cap: operator quote 2026-09-14 ('Make the caps count actual spend ... $2.00/day ... Retire the temporary $7 override'); one host file, 99-llm-global-cap.conf drop-ins, 6 crontab lines set to 2.00. |
| 2717-2726 | 2026-09-19 operator-directed raise of watchlist_risk_flash_narrative (60->220) and watchlist_steph_flash_narrative (40->180) request caps after PR #1088; operator accepted heavy-day overrun of $2.00 rather than raise the ceiling. |
| 2750-2769 | 2026-09-19 operator directed both controls ('both'): DeepSeek top-up and degrade-not-silent (llm-provider-health lane; watchlist_agent_oauth_fallback pool). llm-provider-health lane later RETIRED 2026-10-07, superseded by health-tick (PRs #1486/#1487). |
| 2898-2907 | LLM_DEFER_OFFPEAK armed globally for cron by the operator 2026-09-20 (crontab line 9 comment); 4.4.1 restated the 2026-09-20 'set in exactly one place' text as measured 2026-10-10. |
| 2939 | braveapi disable approved by the operator 2026-10-10 ~18:40 ET ('Yes, from one to six', item 1). |
| 3003-3009 | contract_guid / option_strategy_guid added to CANONICAL_ID_FIELDS 2026-09-24, PR #1225; not new id types. |
| 3106, 3125 | INDUSTRY:/THEME: tags-only by operator decision 2026-09-24; beliefs[] (InstrumentBelief@v1) shipped 2026-09-24 in PR #1226, superseding priors / scored_lessons[]. |
| 3184-3186, 3222-3233 | Dark-ledger closures 2026-09-19/20: AgentView/AGENT_COMMITMENT producers, load-by-subject schedule, OUTCOME settlement, librarian index; hermes_advisory_event_enqueue retire token APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE via PR #1151. |
| 3354-3358 | 1.0.0 (2026-09-01) renumbered the second §13.6 (conformance checklist) to §13.7. |
| 3617-3620 | Curation lane order inverted from free-first on operator instruction 2026-09-06. |
| 3783-3786 | Repository-visibility standing operator policy since 2026-07-18. |

### §23 n8n

| 25.0.1 lines | rule (paraphrase) | 26.0.0 location |
|---|---|---|
| 4038-4047 | Where the n8n baseline, procedure and monitoring are written down | §23 intro |
| 4051-4057 | Applies only to the m8m-n8n instance; loosens nothing for others | §23.1 Applies only to the n8n Community instance |
| 4058-4060 | Scheduler/requester never authority; execution row not evidence | §23.1 An n8n execution row is not evidence |
| 4061-4068 | n8n owns flow; host keeps authority and evidence | §23.23 n8n owns flow |
| 4072-4082 | Registry row with output_signal first; two row forms; --receipt flag | §23.2 Registry row first; moved:N8N_ONBOARDING_STANDARD.md §3 |
| 4083-4092 | Workflow changes only under a cron grant naming the id; one tier | §23.2 Install, activate … only under an operator cron grant |
| 4093-4100 | Shadow before canary before cutover, receipt per step | §23.12 Shadow, then canary, then cutover |
| 4101-4108 | Cutover comments, never deletes; rollback per line | §23.2 Cutover comments the cron line |
| 4109-4114 | One scheduler per lane; CRON_PRESENT_WHILE_SCHEDULER_N8N | §23.2 One scheduler per lane |
| 4115-4121 | Stage-aware double-schedule check before any wave | retired |
| 4122-4123 | Fixed retirement tag; owner in CutoverReceipt | §23.2 Cutover comments the cron line |
| 4127-4135 | Only trigger path: relay → coordination/run, {lane_id, mode} | §23.3 n8n workflows and n8n Agent nodes may cause host work only through |
| 4136-4142 | Agent prohibitions; never-list applies to Agent tools | §23.3 An Agent may not invoke …; §23.14 |
| 4143-4147 | Agent tool calls checked against per-process allowlist at bridge | §23.3 An Agent may not invoke … |
| 4148-4155 | Container internet egress blocked, not proxied | §23.3 The container's internet egress is blocked |
| 4156-4164 | Allowlist is data with a test; never broker/sender/secret/etc | §23.14 never-list and token test; OPEN_ITEMS (writer check) |
| 4165-4180 | trade-ai-scalp-live live exception on exact terms | §23.14 trade-ai-scalp-live runs live only on its exact cron argv |
| 4181-4188 | Advisory market-data lanes are the second exception class | §23.14 exceptions (3); §23.20 |
| 4189-4194 | Gateway never spawns; executor runs lane under its lock | §23.3 The gateway never spawns |
| 4195-4198 | Exit 0 not evidence; failures are typed rows | §23.1 An n8n execution row is not evidence |
| 4199-4201 | No sends from n8n; send_telegram chokepoint | §23.3 No sends from n8n |
| 4202-4210 | Send-intent, approval-request, run-outcome routes, each own PR | §23.3 n8n workflows … (new relay route is its own reviewed PR) |
| 4214-4221 | AI only via bridge by process + template (+ routing policy) | §23.4 A workflow or Agent requests AI only through the governed bridge |
| 4222-4227 | No provider/model/raw prompt/own identity; identity bound to credential | §23.4 A workflow or Agent requests AI …; OPEN_ITEMS (caller auth report mode) |
| 4228-4234 | Routing order is policy (Grok, ChatGPT, DeepSeek) | §23.4 (routing order is policy); moved:config/llm_routing_policy.json |
| 4235-4239 | Free text only after sanitiser and free_text_allowed | §23.4 A template id is the only prompt input; OPEN_ITEMS |
| 4240-4247 | Capped twice, typed refusals, deferral; global $2.00 cap | §23.4 Every call is capped twice |
| 4248-4253 | Outputs schema-validated, behaviour-scanned, advisory only | §23.4 Outputs are advisory drafts |
| 4257-4268 | At most two credentials; rotation unscheduled; others are defects | §23.5 n8n holds one credential; OPEN_ITEMS (rotation) |
| 4269-4274 | MFA waived; waiver excludes DB role | §23.5 No new n8n credential while … superuser |
| 4275-4277 | Gateway HMAC key stays host-side | §23.5 n8n holds one credential (HMAC key never enters n8n) |
| 4278-4290 | Execution data not retained; superuser breach open; no new credential before P13 | §23.5 (two bullets); OPEN_ITEMS (P13); LESSONS L23-11 |
| 4291-4292 | Never print a value | §23.5 n8n holds one credential (Never print a value) |
| 4296-4302 | Deleting compose project leaves production unchanged | §23.6 Deleting the compose project |
| 4303-4306 | Rollback triggers are findings; operator decides; per line | §23.6 Rollback triggers; moved:RUNBOOK_CUTOVER_ROLLBACK.md §5; OPEN_ITEMS (RUN_REFUSED) |
| 4308-4412 | Amended-in-place record | retired |
| 4423-4425 | Agent node needs registry row, receipt per turn, grant | §23.8 An Agent node runs only in a workflow with … |
| 4426-4427 | Agent model node points at the bridge | §23.8 An Agent node runs only … (uses only the bridge) |
| 4428-4432 | Agent tools limited; risky node types excluded | §23.8 An Agent node runs only … |
| 4433-4435 | Turns, tokens, wall time capped; streaming refused | §23.8 An Agent node runs only … |
| 4436-4438 | No egress for Agents | retired |
| 4439-4447 | First Agent read-only, explains lane failure | §23.8 The first Agent only explains a lane failure |
| 4451-4458 | Guardrail parity table before any move | §23.9 Before a lane or capability moves into n8n; OPEN_ITEMS (coverage) |
| 4462-4495 | Preconditions P2–P22 before first Agent/bridge token | §23.10 pointer; moved:docs/implementation/n8n-maturity/N8N_AGENT_NODE_PRECONDITIONS.md; OPEN_ITEMS |
| 4496-4501 | Closed/waived P1, P10, P14, P23 | retired |
| 4505-4512 | Six generic workflows activated once under one grant | §23.2 cron grant naming the id; moved:02-six-workflow-architecture.md |
| 4513-4521 | Enabling a lane is a reviewed row+allowlist PR; merge is the decision | §23.11 Enabling a dispatcher lane is one reviewed PR |
| 4522-4536 | Cron row at shadow/canary; dispatcher naming | §23.11 Shadow and canary rows stay cron rows; moved:N8N_ONBOARDING_STANDARD.md §3 |
| 4537-4544 | Gateway decides due; n8n supplies only lane id and mode; stage clamp | §23.11 The gateway decides what is due |
| 4545-4550 | Workflows send nothing; approval router never mints a grant | §23.11 The gateway decides … (no workflow mints, approves or extends a grant); §23.3 No sends |
| 4551-4560 | Flow decisions allowed; more workflows each under cron grant | §23.23 n8n owns flow; §23.2 cron grant |
| 4561-4564 | Editing one of the six needs cron grant + reviewed JSON | retired |
| 4565-4568 | One registry PR at a time | §23.11 One registry PR at a time |
| 4572 | Dispatcher rows use wave ladder | §23.12 |
| 4574-4580 | Wave climbs together; lock must match; receipt per fire | §23.12 Shadow, then canary, then cutover |
| 4581-4585 | A lane failing any fire leaves the wave | §23.12 A lane that fails any fire leaves the wave |
| 4586-4592 | Cutover per wave under one cron grant naming lanes; per-lane receipts | §23.12 Cutover is per wave |
| 4593-4597 | Wave fire is not natural evidence; monitored not awaited | §23.12 Cutover is per wave (natural fires monitored) |
| 4599-4644 | Program window push budget and standing merge approval | retired |
| 4647-4651 | Broker/order/secret/daemon lanes never dispatcher-eligible; watch only | §23.14 Broker, order, secret and daemon lanes are never dispatcher-eligible. |
| 4652-4659 | Read-only broker lane exception | §23.14 exceptions (4); §27.1 |
| 4660-4666 | Eligibility test is code: token lists, no daemons | §23.14 The test is code, not judgement |
| 4667-4676 | Scalp single named exception on 4.0.0 terms | §23.14 trade-ai-scalp-live runs live only … |
| 4677-4689 | Approval router lane may read guard state only | §23.14 The approval router's lane reads guard state only; OPEN_ITEMS (no registry row) |
| 4690-4691 | No program-window amendment can change §23.14 | §23.14 Widening this list is operator-only and needs a new MAJOR |
| 4700-4709 | ingest/llm/learn admitted by reviewed PR, ladder, cutover grant | §23.18; §23.11; §23.12 |
| 4710-4731 | r1_class_admission gate (a)–(e) | §23.18 An ingest, llm or learn row enters only through r1_class_admission; moved:lane_dispatch.py |
| 4732-4745 | llm rows via bridge only; L401 terms and gap | §23.18 (llm_route via cio-governed-bridge); OPEN_ITEMS (L401) |
| 4746-4751 | Dispatched lanes carry no broker credential; entry planner | §23.18 (r1_class_admission refuses broker env names); OPEN_ITEMS (entry planner) |
| 4752-4763 | alert_events not a send; backtest not execution; L504/L205 | §23.18 (alert_events/backtest); history (lane approvals) |
| 4764-4772 | Word matching in a separate PR with proof | retired (done); §23.14 The test is code |
| 4781-4789 | Onboarding standard mandatory; checklist with evidence | §23.19 The procedure is N8N_ONBOARDING_STANDARD.md, and it is mandatory |
| 4790-4798 | Health contract required; independent REVIEWED; no UNKNOWN at canary | §23.19 No lane enters shadow, canary or cutover without a workflow health contract |
| 4799-4803 | Relay contract check before import; verify via deletedAt/ledger | §23.19 Before any n8n import |
| 4814-4818 | Advisory ceiling is code; adding is operator decision | §23.20; operator_only |
| 4819-4829 | (a) Market data only | §23.20; moved:advisory_lane_guard.py |
| 4830-4835 | (b) Advisory writes only; no submit switch | §23.20; moved:lane_dispatch advisory_md_admission |
| 4836-4843 | (c) Sends via host chokepoint; bypass only in listed files | §23.20 (host sends); history (rationale) |
| 4844-4849 | (d) No secret through n8n; executor builds env | §23.20 (no secret via n8n); moved:n8n_run_executor.build_child_env |
| 4850-4857 | Class pipeline; lock equals cron lock; ladder; explicit --apply | §23.20; moved:lane_dispatch |
| 4858-4863 | CI reach scan fails dispatched senders/broker reach outside exceptions | §23.14 F09 … stay host-side (CI reach scan) |
| 4864-4866 | Not changed list | retired |
| 4877-4888 | Four cutover conditions | §23.21 Cut over only when all four hold |
| 4889-4899 | Where the live run comes from; OPERATOR_FORCED_LIVE; no agent F09 force | §23.21 The live run is the next dispatcher slot |
| 4900-4912 | Cutover factory; commented line is the fallback | §23.21 Use scripts/n8n_cutover_wave.py; moved:RUNBOOK_CUTOVER_ROLLBACK.md |
| 4913-4921 | No multi-day soak; waiver limits | §23.21 Cut over only when all four hold (no soak; no waiver covers …) |
| 4922-4928 | Unchanged rails list | retired |
| 4929-4932 | Why MAJOR | retired |
| 4933-4938 | Open gaps: checklist natural slots | OPEN_ITEMS |
| 4939-5000 | Ratifying edit | retired |
| 5017-5023 | n8n owns flow via one Run Lane sub-workflow | §23.23 n8n owns flow |
| 5024-5030 | Host owns authority, execution, evidence; no bot token | §23.23 n8n owns flow …; §23.3 No sends from n8n |
| 5031-5036 | No broker credential/route; writes via execution service + assertion; approval is a request | §23.23 n8n never holds a broker credential; §23.11 (approval is a request); OPEN_ITEMS (broker gateway) |
| 5037-5044 | LLM steps: bridge only, closed schema, host re-check, ingested text is data | §23.4 A workflow … / Outputs are advisory drafts; moved:N8N_REFERENCE_ARCHITECTURE.md |
| 5045-5050 | Agents are judgment functions; no side effect without approval gate | §23.8 (Agent node rules); §23.3 Agent prohibitions |
| 5051-5058 | Workflow governance (1)-(7) | §23.2 generated from git / drift P1; §23.5 execution data and superuser; §23.23 error workflow, refusals, community nodes; OPEN_ITEMS (drift) |
| 5059-5065 | Node enablement: each a reviewed PR; messaging nodes excluded | §23.23 Each WS9 control … (each node-type enablement its own reviewed PR); §23.8 excluded nodes |
| 5066-5068 | P0/P1 never depend on n8n; approvals fail closed | §23.6 P0/P1 never depend on n8n |
| 5069-5079 | Migration freeze, processes-owned metric, consolidate first, fenced switch | §23.21 Consolidate before migrating / Use scripts/n8n_cutover_wave.py; OPEN_ITEMS (freeze) |
| 5080-5085 | Money-flow preconditions before any money-touching workflow | §23.23 No workflow that can reach a broker account read …; moved:N8N_REFERENCE_ARCHITECTURE.md §9 |
| 5086-5093 | WS9 C1–C10 before the powers they guard | §23.23 Each WS9 control …; moved:N8N_REFERENCE_ARCHITECTURE.md §9 |
| 5094-5100 | Unchanged/why MAJOR | retired |
| 5116-5120 | Every workflow in scope; one class and owner; REVIEWED contract before leaving shadow | §23.24 Every workflow … meets the framework; §23.19 health contract |
| 5121-5163 | Framework elements and E/P checks | moved:N8N_CONFIGURATION.md §0.4; OPEN_ITEMS (SLA watcher, half-open breaker, drift) |
| 5164-5168 | Activation bar; 30-day remediate-or-archive | §23.24 None is activated … ; OPEN_ITEMS (deadline) |
| 5169-5181 | Reference documents | §23 intro; moved:N8N_CONFIGURATION.md header table |
| 5182-5184 | Unchanged list | retired |
| 5191-5194 | Scope: all families except F07 and registry_systemd | §23.25 Every family in lane_cutover_policy.json is a cutover target |
| 5195-5200 | Host-side rationale not a blocker; exceptions individually | §23.25 (not a blocker; other exceptions operator-only) |
| 5201-5207 | Cutover builds maturity: §23.21, §23.24, effect keys; F07w/F10 backstops | §23.25 Every family … (builds them in; F07w; F10) |
| 5208-5214 | F09: n8n schedules host lanes only; no broker credential; live proof from n8n schedule | §23.25 For F09, n8n schedules host lanes only, and only those §23.14 admits; §23.14 F09 bullet; OPEN_ITEMS (F09 code gap) |

**Retired**

| 25.0.1 lines | reason |
|---|---|
| 4011-4036 | history: status line, tokens, directions, Why MAJOR |
| 4061-4068 | history: 10.0.0 superseded note; its rule now stated once in §23.23 |
| 4115-4121 | stale: 4.4.0 made shadow/canary rows cron rows, so the stage-aware conflict check is moot; n8n_lane_host_conflict.classify_cron (lines 74-79) ignores stage and waves ran |
| 4122-4123 | duplicate: tag form kept in §23.2 cutover bullet |
| 4216-4217 | stale: registry has three n8n_* processes (adds n8n_lane_failure_diagnosis); draft cites the registry by prefix |
| 4237-4238 | stale: 'until that sanitiser is built' - scripts/lib/cio_egress_sanitiser.py exists and runs on the bridge path; remaining gap (free-text refusal) is an open item |
| 4305-4306 | stale: 'any RUN_REFUSED row' contradicts §23.23 (5) and §23.24 alerting (4); resolved toward refusals-are-data, open item Decide |
| 4308-4412 | history: §23.7 amendment bookkeeping |
| 4416-4421 | history: 3.0.0 evidence list |
| 4436-4438 | duplicate of §23.3 egress bullet |
| 4496-4501 | history: closed/waived preconditions |
| 4551-4560 | history: 10.0.0 superseded note; merged into §23.11/§23.23 |
| 4561-4564 | duplicate of §23.2 (cron grant naming the workflow id; generated from git, reviewed packet) |
| 4596-4597 | duplicate of §8.1/§15 (9.5 maturity stretch needs natural fires) |
| 4599-4644 | stale: §23.13 standing merge approval expired 2026-10-11T17:30:03-04:00 and the window 2026-10-12T23:59:59-04:00; superseded by §25.10 and AI_WORK_POLICY.md §3 |
| 4647-4648 | dropped count: 'About 99 such lines stay on cron or systemd' |
| 4652-4659 | duplicate of §27.1 (named once as exception (4) in §23.14) |
| 4690-4691 | stale: no program window exists; replaced by 'widening is operator-only and needs a new MAJOR' |
| 4695-4698 | history: R1 preamble and 4.2.0 numbering note |
| 4752-4763 | history: lane-specific R1 ruling-4 approvals (rule kept in §23.18) |
| 4764-4772 | stale: word matching is done - lane_dispatch.EXTRA_FORBIDDEN_WORDS 'matched by word, not substring' (lane_dispatch.py ~157-170); pins live in tests/test_lane_dispatch_word_boundary_20261010.py |
| 4776-4779 | history: numbering note |
| 4809-4812 | history: 7.0.0 status |
| 4836-4843 | history: bypass rationale (rule kept in §23.20 via ADVISORY_MD_BYPASS_FILES) |
| 4864-4866 | history: 7.0.0 not-changed list |
| 4870-4875 | history: 16.0.0 status |
| 4922-4928 | duplicate: restates §23.14, §23.12, §23.2, §23.23, §23.24 rules kept elsewhere |
| 4929-4932 | history: 16.0.0 Why MAJOR |
| 4939-5000 | history: 16.0.0 ratifying edit and digests |
| 5004-5015 | history/stale: directive text and numbering claims ('§23.21 is claimed by 8.0.0 … §23.22 by 9.0.0, both PROPOSED') |
| 5032 | stale: '(§23.22)' - no §23.22 exists (9.0.0 never ratified); replaced by §27.1 |
| 5091 | stale: 'C8 the broker gateway (§23.22)' - moved verbatim to N8N_REFERENCE_ARCHITECTURE.md §9; open item Decide |
| 5094-5100 | history: 10.0.0 unchanged list, Why MAJOR |
| 5104-5114 | history: 11.0.0 directive/status/E-P convention |
| 5146-5147 | stale: 'effect_claim.py served with #1739, lane list empty' - config/n8n_effect_keys.json has 70 entries, 31 n8n_claim and 37 cron_claim armed (2026-10-27) |
| 5164-5168 | stale: 'The proposed check is scripts/check_n8n_workflow_framework.py (P)' - it exists, with CI gate config/ci_gates/n8n_workflow_framework_20261015.json |
| 5182-5184 | history: 11.0.0 unchanged list |
| 5188-5189 | history: 12.0.0 status |

**Moved to the document that owns the subject**

| 25.0.1 lines | to |
|---|---|
| 4462-4501 | `docs/implementation/n8n-maturity/N8N_AGENT_NODE_PRECONDITIONS.md` |
| 4303-4306 | `docs/implementation/n8n-maturity/RUNBOOK_CUTOVER_ROLLBACK.md` |
| 5080-5085 | `docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` |
| 5086-5093 | `docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` |
| 5169-5181 | `docs/implementation/n8n-maturity/N8N_AGENT_NODE_PRECONDITIONS.md` |
| 5121-5163 | `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` |
| 4072-4082,4522-4536 | `docs/implementation/n8n-maturity/N8N_ONBOARDING_STANDARD.md` |
| 4505-4512 | `docs/implementation/n8n-maturity/02-six-workflow-architecture.md` |
| 4574-4592,4900-4912 | `docs/implementation/n8n-maturity/RUNBOOK_CUTOVER_ROLLBACK.md` |
| 4889-4899 | `docs/implementation/n8n-maturity/RUNBOOK_CUTOVER_ROLLBACK.md` |
| 4710-4731 | `scripts/lib/lane_dispatch.py` |
| 4819-4835,4844-4857 | `scripts/lib/advisory_lane_guard.py` |
| 5017-5023,5037-5044,5059-5065 | `docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md` |
| 4127-4135,4189-4194 | `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` |
| 4199-4201,4428-4432 | `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` |
| 4228-4234 | `config/llm_routing_policy.json` |
| 4257-4260,4275-4277 | `docs/architecture/n8n/ADR_COORDINATION_SECRETS.md` |
| 4790-4796 | `scripts/check_n8n_health_contracts.py` |

**Provenance moved here**

| 25.0.1 lines | what |
|---|---|
| 4011-4031 | §23 status line and banner: 2.0.0/3.0.0/4.0.0/4.1.0/4.3.0/4.4.0 ratification tokens; operator directions 2026-10-08 and 2026-10-09; program plan and lab AGENTS paths. |
| 4032-4036 | 2.0.0 'Why MAJOR' class reasoning. |
| 4046-4047 | Cause of the n8n baseline pointer (4.4.1): operator 2026-10-10 ~16:35 ET after the W0 rollback. |
| 4061-4068 | 10.0.0 superseded-in-place note on §23.1 'a scheduler and a requester'. |
| 4308-4412 | §23.7 record of sentences replaced by 2.0.0, 3.0.0, 4.0.0, 4.1.0, 4.3.0, 4.4.0 and 7.0.0, with readable origin/main SHAs. |
| 4416-4421 | 3.0.0 evidence list: guardrail audits A/B/C of a9fa8b89b and the 3.0.0 proposal path. |
| 4496-4501 | P1, P10, P14, P23 closed or waived before 3.0.0. |
| 4551-4560 | 10.0.0 superseded-in-place note on §23.11 'decide nothing' and the six-workflow ceiling. |
| 4599-4644 | §23.13 program window: n8nmat/* 4-push budget, Agent A standing merge approval (Expires-At 2026-10-11T17:30:03-04:00), exclusions; expired. |
| 4695-4698 | 4.3.0 R1 rulings preamble (2026-10-10 ~00:20 ET); 4.2.0 (PR #1634) never ratified, withdrawn by 25.0.0. |
| 4752-4763 | R1 ruling 4 lane approvals: L549 fee analyzer, L671 config governor, L606 backtest engine, L504 symbol_profiles writer, L205 market_regime writer. |
| 4776-4779 | §23.19 numbering note and 'restates §8.1' preamble (4.5.0). |
| 4809-4812 | 7.0.0 status and ratification token (APPROVE_AGENTS_POLICY_7_0_0 1725 73eebc5c1). |
| 4836-4843 | 7.0.0 rationale for keeping the momentum_alerts bypass (not routed) and its execution-engineering dependency. |
| 4864-4866 | 7.0.0 'Not changed' list. |
| 4870-4875 | 16.0.0 status, ratification token, operator ruling 2026-10-14 ~11:05 ET, rebuild of PR #1727. |
| 4929-4932 | 16.0.0 'Why MAJOR' and why §23.14 could change after the program window. |
| 4939-5000 | 16.0.0 ratifying edit: five quoted clause replacements with sha256 digests and the pin moves. |
| 5004-5015 | 10.0.0 operator directive text, numbering claims (§23.21/§23.22 PROPOSED, stale), ratification APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279, evidence paths. |
| 5094-5100 | 10.0.0 'Unchanged' list and 'Why MAJOR'. |
| 5104-5114 | 11.0.0 directive, ratification APPROVE_AGENTS_POLICY_11_0_0 1747 89fb642cd, E/P convention, gap-assessment evidence. |
| 5182-5184 | 11.0.0 'Unchanged' list. |
| 5188-5189 | 12.0.0 status, ratification APPROVE_AGENTS_POLICY_12_0_0 1779 4aeb8cf4e. |
| 5196-5200 | Operator verbatim quote 2026-10-15 (kept in full in N8N_REFERENCE_ARCHITECTURE.md §2a). |

### §24–§29

| 25.0.1 lines | rule (paraphrase) | 26.0.0 location |
|---|---|---|
| 5220-5228 | §24 status, ratification and scope banner | §24 intro / AGENTS_HISTORY |
| 5232-5238 | gateway is the only sender; baselines never grow | §24.1 The host communications gateway is the only sender |
| 5239-5244 | n8n fires host lanes; routing rules on host by PR | §24.1 n8n decides what and when; the host decides delivery |
| 5245-5254 | n8n decides what/when; host keeps delivery policy | §24.1 n8n decides what and when; the host decides delivery |
| 5255-5258 | P1 path never depends on n8n | §24.1 n8n decides what and when (last sentence) |
| 5259-5264 | senders emit notification intents | §24.1 The host communications gateway is the only sender |
| 5268-5274 | free lane first, paid Brave on measured insufficiency | §24.2 Free lane first |
| 5275-5281 | policy file authoritative; one engine; UNKNOWN_CALLER | §24.2 Free lane first / OPEN_ITEMS |
| 5282-5286 | Brave dollar lines and pools | §24.2 Dollars bound Brave / moved:docs/implementation/n8n-maturity/SEARCH_SOURCE_ROUTING.md |
| 5287-5291 | request breaker sits above dollar lines; registry PR | §24.2 Dollars bound Brave |
| 5292-5296 | SearXNG never names a Brave engine | §24.2 Free lane first / OPEN_ITEMS |
| 5297-5303 | Alpha Vantage one owner, 23/day | §24.2 Alpha Vantage has one owner |
| 5307-5311 | one owner lane per provider writes a domain | §24.3 One owner lane writes each broker-backed domain |
| 5312-5318 | consumers read projections, no silent provider calls | §24.3 One owner lane writes each broker-backed domain |
| 5319-5324 | lane direct reads are checked violations | §24.3 (LANE_DIRECT_READ_ROSE) |
| 5325-5328 | approved domains catalogue | AGENTS_HISTORY / OPEN_ITEMS |
| 5332-5340 | Trade AI resources never serve another application | §24.4 |
| 5341-5347 | boundary only restricts; other-app job changes operator-only | §24.4 / OPEN_ITEMS |
| 5351-5358 | scheduled jobs never push or open PRs | §24.5 |
| 5359-5362 | Mergify and poller are not scheduled pushes | §24.5 |
| 5366-5369 | tests set TRADE_AI_CI=1 and use tmp roots | §24.6 |
| 5370-5374 | production rows from tests archived, test fixed | §24.6 / OPEN_ITEMS |
| 5378-5384 | no agent reads or links .env or credentials | §24.7 |
| 5388-5395 | release-write grant names SHA/PR, one per release | §24.8 (emergency path only) |
| 5396-5399 | poller needs no grant; emergency does | §24.8 |
| 5403-5412 | designs stay Supabase and hosted-n8n portable | §24.9 / moved:docs/implementation/n8n-maturity/N8N_CONFIGURATION.md / OPEN_ITEMS |
| 5416-5419 | execution-ops is the only rule-2 exception, units not code | §24.10 bullet 1 |
| 5421-5432 | reach: broker-execution user units; exclusions operator-only | §24.10 bullet 1 |
| 5433-5441 | execution-ops per incident ≤6 h; reason binds | §24.10 bullet 2 |
| 5442-5463 | permitted actions 1–4 only; not-under list | §24.10 bullet 2 / moved:docs/ops/EXECUTION_OPS_GRANT.md |
| 5464-5469 | mutations only while market CLOSED, fail closed | §24.10 bullet 2 |
| 5470-5481 | preflight (a)–(f) quoted before first mutation | §24.10 bullet 2 / moved:docs/ops/EXECUTION_OPS_GRANT.md |
| 5482-5487 | proof checks; rollback by restoring archived drop-in | moved:docs/ops/EXECUTION_OPS_GRANT.md |
| 5488-5494 | never credentials, flags, orders, broker code | §24.10 bullet 3 |
| 5495-5505 | install mechanics and enforcement gaps | OPEN_ITEMS / AGENTS_HISTORY / moved:docs/ops/EXECUTION_OPS_GRANT.md |
| 5509-5513 | broker-read status; --plan only without grant | §24.11 bullet 1 / AGENTS_HISTORY |
| 5515-5524 | one entrypoint, closed step list, apply writes our stores | §24.11 bullet 1 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5525-5532 | broker-read ≤4 h, one use per run, revocable | §24.11 bullet 1 |
| 5533-5541 | conditions each a refusal in code | §24.11 bullet 2 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5542-5547 | no credential value reaches the agent | §24.11 bullet 2 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5548-5555 | no re-auth, 2FA, refresh or flag change reachable | §24.11 bullet 2 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5556-5570 | no order route or stop write; pinned by CI | §24.11 bullet 2 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5571-5573 | BrokerReadSyncReceipt@v1 proof | moved:docs/ops/BROKER_READ_SYNC.md |
| 5574-5577 | not under this grant: everything else in rule 2 | §24.11 bullet 2 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5578-5585 | broker-read open gaps | OPEN_ITEMS |
| 5586-5603 | 14.0.0 ratifying edit | AGENTS_HISTORY |
| 5607-5612 | disk hygiene status; agents dry-run only | §24.12 bullet 1 / AGENTS_HISTORY |
| 5614-5621 | one script, two callers, no hand deletion | §24.12 bullet 1 |
| 5622-5633 | /tmp hygiene lanes named addition | §24.12 bullets 1 and 3 |
| 5634-5642 | reclaimable: clean clones/worktrees, old releases | §24.12 bullet 2 / moved:docs/ops/DISK_HYGIENE.md |
| 5643-5649 | never-touch list enforced in code | §24.12 bullet 2 / moved:docs/ops/DISK_HYGIENE.md |
| 5650-5654 | rule changes operator-only | §24.12 bullet 3 |
| 5655-5661 | every apply: fresh manifest, re-validate, caps, receipt | §24.12 bullet 3 / moved:docs/ops/DISK_HYGIENE.md |
| 5662-5665 | first live apply reviewed by operator | §24.12 bullet 3 / OPEN_ITEMS |
| 5666-5670 | kill switch by live list or config | §24.12 bullet 3 (keys corrected) |
| 5671-5675 | everything else stays under Never delete | §24.12 bullet 2 |
| 5676-5683 | disk open gaps | OPEN_ITEMS |
| 5684-5687 | retire path | retired |
| 5688-5711 | 15.0.0 ratifying edit | AGENTS_HISTORY |
| 5726-5728 | §25.10 PROPOSED status line | AGENTS_HISTORY |
| 5730-5733 | agents queue, never merge or promote; no gh pr merge | §25.10 Agents queue |
| 5734-5737 | agent path: claim, build, ready PR, stop | §25.10 Agents queue / §28.12 |
| 5738-5744 | Approve all binds listed PRs to head SHAs | §25.10 "Approve all" |
| 5745-5758 | held classes never in Approve all; list in config | §25.10 Held classes / OPEN_ITEMS |
| 5759-5762 | Mergify merges in ET windows, market freeze | §25.10 Mergify merges in ET windows |
| 5763-5771 | poller promotes exact SHA under delegation; SOFT; P1 | §25.10 The host promotes / OPEN_ITEMS |
| 5772-5774 | delegation is promote-only; arming §17 | §25.10 The host promotes |
| 5775-5777 | one STOP latch and lock; clearing §17 | §25.10 The host promotes |
| 5778-5782 | emergency promote operator's; coordinator on own instruction | §25.10 The emergency promote |
| 5788-5793 | §26 status and doc pointers | §26 intro / AGENTS_HISTORY |
| 5797-5805 | one prospect row per security_guid, CIO writer | §26.1 / moved:docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md |
| 5806-5810 | security_guid key; aliases never second keys | §26.1 |
| 5811-5813 | MBI_BEHAVIOR = 0 for the record | §26.1 |
| 5817-5824 | dictionary is the §7A registry; proposals granted | §26.2 |
| 5825-5828 | CI fails second writers and non-authoritative reads | §26 intro (enforcement) / moved:docs/architecture/DATA_DICTIONARY.md |
| 5832-5836 | every surface reads via projection; ranking §17 | §26.3 |
| 5840-5843 | n8n gathers, decides and writes nothing | §26.4 |
| 5847-5851 | conflicts recorded and shown, never auto-merged | §26.5 |
| 5855-5859 | stores and writers §17; archive copies | §26.6 / AGENTS_HISTORY |
| 5865-5869 | §27 status and code note | AGENTS_HISTORY / retired |
| 5873-5879 | closed set of carve-out read lanes | §27.1 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5880-5885 | carve-out preconditions refused in code | §27.1 / moved:docs/ops/BROKER_READ_SYNC.md |
| 5886-5890 | execution on host, n8n holds no token | §27.1 |
| 5891-5896 | never-list does not move; agents never fire lanes | §27.1 |
| 5900-5905 | settings in Postgres; one governed applier | §27.2 / moved:docs/ops/OPS_CONTROLS.md / OPEN_ITEMS |
| 5906-5908 | agents never call Controls or the applier | §27.2 |
| 5912-5914 | safe direction one click | §27.3 |
| 5915-5920 | risky direction passkey and typed phrase | §27.3 |
| 5921-5928 | sudo window | §28.5 |
| 5929-5933 | named passkeys; TOTP recovery; Telegram notifies | §27.3 |
| 5937-5944 | §27.4 gaps | OPEN_ITEMS |
| 5950-5954 | §28 status; rules bind every vendor | §28.3 / AGENTS_HISTORY |
| 5958-5965 | four named automations only | §28.1 |
| 5966-5971 | caps measured, cited, changed by PR | §28.1 / moved:docs/ops/PIPELINE_TIME_SETTINGS.md |
| 5972-5976 | kills leave reasoned receipts; children finish in step | §28.1 |
| 5980-5985 | no new temp data under /tmp | §28.2 |
| 5989-5991 | look before building | §28.3 |
| 5992-5998 | claim before building; first claim owns; stale 2 h | §28.3 |
| 5999-6004 | claim lifecycle stages with timestamps | §28.3 / moved:docs/ops/AGENT_CLAIM_BOARD.md |
| 6005-6009 | worklog sections and commands | §28.3 |
| 6010-6012 | coordinator keeps a worklog | §28.3 |
| 6013-6018 | pre-commit gate with logged overrides | §28.3 |
| 6019-6021 | claims archived to claims_history.jsonl | §28.3 / moved:docs/ops/AGENT_CLAIM_BOARD.md |
| 6022-6030 | resume from board; takeover carries worklog | §28.3 |
| 6031-6033 | long session ends with emailed handoff | §28.3 |
| 6037-6051 | picking-up procedure | §28.3a |
| 6055-6062 | design ids, phases, tasks, trailer | §28.3b |
| 6063-6068 | one design registry in docs/designs | §28.3b / moved:docs/designs/README.md |
| 6069-6071 | design approval operator-only; unregistered work | §28.3b / OPEN_ITEMS |
| 6075-6078 | approval counts only in own session | §28.4 |
| 6079-6083 | hand over exact runnable command | §28.4 |
| 6087-6093 | sudo window rules | §28.5 |
| 6097-6108 | Schwab read-only, locks, kill switches operator's | §28.6 |
| 6112-6113 | §28.7 ratifying edit pointer | AGENTS_HISTORY |
| 6117-6118 | §28.8 status | AGENTS_HISTORY |
| 6120-6127 | no agent traffic to live server 04:00–16:15 ET | §28.8 |
| 6128-6130 | validate with fixtures or replay | §28.8 |
| 6131-6135 | after-close smoke GET only ≤1/s | §28.8 |
| 6136-6138 | binds agents only | §28.8 / retired |
| 6143-6145 | §28.9 status | AGENTS_HISTORY |
| 6147-6151 | no silent removal without approved mockup | §28.9 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6152-6158 | shared infrastructure alone with real-layout proof | §28.9 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6159-6164 | one source per fact, owned by CIO record | §28.9 |
| 6165-6168 | health means the job ran | §28.9 |
| 6169-6172 | a read never acts; probe limits | §28.9 |
| 6173-6176 | every writer a monitored n8n lane | §28.9 |
| 6181-6183 | §28.10 status | AGENTS_HISTORY |
| 6185-6189 | one conflict engine and rulebook | §28.10 / moved:docs/ops/CONFLICT_ENGINE.md |
| 6190-6192 | agreement and superseded never flag | §28.10 |
| 6193-6194 | gates are not conflicts | §28.10 |
| 6195-6198 | owner decides with recorded reason | §28.10 |
| 6199-6201 | CIO always informed | §28.10 |
| 6202-6203 | safety findings never auto-resolved | §28.10 |
| 6208-6211 | transition sunset 2026-12-31; no §0/§2/§17 exception | §28.11 |
| 6213-6216 | existing conflict producers until engine | §28.11 / OPEN_ITEMS |
| 6217-6219 | existing per-page readers until cio_truth | §28.11 / OPEN_ITEMS |
| 6220-6222 | presence-based health views labelled | §28.11 |
| 6223-6226 | host-cron writers until n8n lane live | §28.11 |
| 6227-6228 | known side-effecting GETs until fixed | §28.11 |
| 6229-6232 | in-flight branches; approved boards count as mockups | §28.13 (back-filled 2026-10-24 approvals) / retired |
| 6237-6241 | §28.12 status | AGENTS_HISTORY |
| 6243-6245 | step 1 claim | §28.12 bullet 1 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6246-6248 | step 2 design | §28.12 bullet 1 |
| 6249-6252 | step 3 build | §28.12 bullet 1 |
| 6253-6257 | step 4 test | §28.12 bullet 1 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6258-6261 | step 5 PR | §28.12 bullet 1 / §28.9 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6262-6264 | step 6 CI green; all-skipped fails | §28.12 bullet 1 / moved:docs/ops/DELIVERY_LIFECYCLE.md |
| 6265-6269 | step 7 queue | §28.12 bullet 1 / §25.10 |
| 6270-6273 | step 8 release | §28.12 bullet 1 / §25.10 |
| 6274-6280 | step 9 verify after every release | §28.12 bullet 2 / OPEN_ITEMS |
| 6281-6287 | step 10 failures page the operator | §28.12 bullet 2 / OPEN_ITEMS |
| 6291-6294 | §28.13 status | AGENTS_HISTORY |
| 6296-6303 | one home per page design, versioned | §28.13 bullet 1 / moved:design/README.md / OPEN_ITEMS |
| 6304-6309 | only operator approves design in ledger | §28.13 bullet 1 |
| 6310-6314 | build only approved version, cite it | §28.13 bullet 1 |
| 6315-6317 | no unlisted removal or hide | §28.13 bullet 1 |
| 6318-6328 | phone first, desktop same, measured | §28.13 bullet 2 / moved:design/README.md |
| 6329-6332 | logged-in pages checked by read-only reader | moved:design/README.md |
| 6333-6341 | design assets with real data stay private | §28.13 bullet 2 / moved:design/README.md |
| 6345-6351 | §28.14 status and arming | AGENTS_HISTORY |
| 6353-6355 | monitor independent of n8n | §28.14 bullet 1 / OPEN_ITEMS |
| 6356-6363 | four deterministic remediations once per incident | §28.14 bullet 1 |
| 6364-6368 | other fixes are ordinary PRs; fixer never merges | §28.14 bullet 2 / OPEN_ITEMS |
| 6369-6372 | refused scopes go to a person | §28.14 bullet 2 |
| 6373-6375 | every action logged append-only | §28.14 bullet 2 |
| 6376-6378 | escalation P1 after max attempts | §28.14 bullet 2 |
| 6382-6387 | §28.15 status | AGENTS_HISTORY |
| 6389-6392 | class MAJOR; governs where §17/§24.7/§24.8 differ | AGENTS_HISTORY / retired |
| 6394-6396 | causes 2026-10-25 | LESSONS |
| 6398-6413 | push budget 5 with coordinator override | §28.15 item 1 / OPEN_ITEMS / moved:docs/ops/HANDS_OFF_DELIVERY.md |
| 6414-6435 | shared infra merges alone through digest; conditions | §28.15 item 2 / OPEN_ITEMS |
| 6436-6447 | guard/CI/merge tooling: two reviews and operator merge | §28.15 item 3 / OPEN_ITEMS |
| 6449-6461 | live lanes declared in repo; host list override | §28.15 item 4 / OPEN_ITEMS |
| 6462-6464 | no TTY ACK for routine setup | §28.15 items 5–6 |
| 6465-6477 | configuration keys changeable by single-key tool | §28.15 items 5–6 / OPEN_ITEMS |
| 6478-6479 | item 7 retired solo class | AGENTS_HISTORY |
| 6481-6497 | routine pushes and toolchains need no guard grant | §28.15 item 8 / OPEN_ITEMS |
| 6498-6512 | complete list of what reaches the operator | §28.15 item 9 / §17 (operator_only) |
| 6513-6519 | no self-review | §28.15 item 10 |
| 6523-6526 | §28.16 PROPOSED status | AGENTS_HISTORY |
| 6528-6531 | one incident ledger | §28.16 item 1 |
| 6532-6534 | agent never ends task with incident open | §28.16 item 2 |
| 6535-6536 | host watchers open incidents | §28.16 items 3–5 |
| 6537-6541 | capped incident supervisor | §28.16 items 3–5 / moved:docs/ops/INCIDENT_LEDGER.md |
| 6542-6543 | coordinator reviews the ledger | §28.16 items 3–5 |
| 6549-6549 | §29 PROPOSED status | AGENTS_HISTORY |
| 6551-6556 | preflight every limit before paid jobs | §29 |
| 6557-6559 | data-quality gate before model calls | §29 |
| 6560-6564 | news rewrite only after relevance/collision checks | §29 |
| 5715-5722 | §25 preamble: train retired, §25.1–§25.9 not reused | §25 intro / AGENTS_HISTORY |

**Retired**

| 25.0.1 lines | reason |
|---|---|
| 5245-5254 | superseded: the §23.23 note is merged into §24.1 bullet 2; bookkeeping is history |
| 5275-5281 | stale: PR #1676 merged (99713d9ce); the engine flag state moved to OPEN_ITEMS |
| 5287-5291 | stale: the breaker was raised to 300/day, 3,600/month (config/data_source_authority.json providers.brave.budget._amended) |
| 5297-5303 | stale: PR #1675 merged (e5ecc6b06); earnings_calendar and news_sentiment are granted domains |
| 5319-5324 | stale: LANE_DIRECT_READ_ROSE exists in scripts/check_data_source_authority.py:39,592; "until it lands" removed |
| 5325-5328 | history: the approved-domain catalogue; latest_quote gap in OPEN_ITEMS |
| 5359-5362 | duplicate of §25.10 (kept as one sentence in §24.5) |
| 5388-5395 | superseded by §25.10: agents no longer request release-write for releases; the binding is kept for the emergency path in §24.8 |
| 5433-5441 | superseded: Telegram /approve grants retired by 23.0.0 (brief fact 6); keyboard bin/guard or Ops → Controls only |
| 5525-5532 | superseded: Telegram /approve grants retired by 23.0.0 (brief fact 6) |
| 5666-5670 | stale: the top-level `auto_apply` key does not exist in config/disk_hygiene_rules.json; replaced by standing_apply.enabled and tmp.auto_apply.enabled |
| 5676-5683 | stale: scripts/disk_hygiene.py and config/disk_hygiene_rules.json are on main and the lane is in the allowlist (live_arg --plan); enforcer gap moved to OPEN_ITEMS |
| 5684-5687 | duplicate of §20 (amendments) and the §24.12 kill switch |
| 5734-5737 | superseded: "never a draft" reconciled with §0 rule 11 (brief fact 5) |
| 5755-5758 | stale: "until that file and test are on main" — both are on main; remaining paths are PR #2251 |
| 5768-5771 | stale: deploy_delegation_binding.py is on main; the poller promotes without a per-SHA grant |
| 5865-5869 | stale: CARVEOUT_STATUS is ACTIVE in scripts/lib/n8n_broker_read_carveout.py:54 |
| 5921-5928 | duplicate of §28.5 |
| 6013-6018 | stale: the claim gate is wired in .githooks/pre-commit:7; the pre-tool warning phase is over |
| 6063-6068 | history: the retroactive registration list (Gates 1–4, Ask the CIO 8–11, CIO integrator, §26 domains) |
| 6136-6138 | folded: §28.8 binds agents only; it changes no service or setting |
| 6147-6151 | stale part: "coordinator holds such a PR out of every batch" — batches were the release train |
| 6229-6232 | partly superseded: in-flight 2026-10-24 branches; the board approvals survive as §28.13's back-filled 2026-10-24 approvals |
| 6389-6393 | folded: where §17/§24.7/§24.8 differ, each §28.15 item states its own effect |
| 6499-6503 | duplicate of §20 (ratification path) and §25.10 (held-class operator merge) |
| 6511-6512 | stale and contradicted: "Everything else ships with no operator input" — every merge needs the operator's digest approval (§25.10); now "ships through §25.10" |
| 6535-6536 | stale: the watchers shipped in #2238 (scripts/incident_watchers.py); "bind as each part ships" removed |

**Moved to the document that owns the subject**

| 25.0.1 lines | to |
|---|---|
| 5442-5505 | `docs/ops/EXECUTION_OPS_GRANT.md` |
| 5515-5585 | `docs/ops/BROKER_READ_SYNC.md` |
| 5873-5896 | `docs/ops/BROKER_READ_SYNC.md` |
| 5614-5687 | `docs/ops/DISK_HYGIENE.md` |
| 5282-5291 | `docs/implementation/n8n-maturity/SEARCH_SOURCE_ROUTING.md` |
| 5403-5409 | `docs/implementation/n8n-maturity/N8N_CONFIGURATION.md` |
| 5730-5782 | `docs/ops/MERGIFY_DEPLOY_FOUNDATION.md` |
| 5797-5813 | `docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md` |
| 5817-5828 | `docs/architecture/DATA_DICTIONARY.md` |
| 5900-5933 | `docs/ops/OPS_CONTROLS.md` |
| 5958-5976 | `docs/ops/PIPELINE_TIME_SETTINGS.md` |
| 5989-6051 | `docs/ops/AGENT_CLAIM_BOARD.md` |
| 6055-6068 | `docs/designs/README.md` |
| 6120-6138 | `docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md` |
| 6147-6176 | `docs/ops/DELIVERY_LIFECYCLE.md` |
| 6243-6287 | `docs/ops/DELIVERY_LIFECYCLE.md` |
| 6185-6203 | `docs/ops/CONFLICT_ENGINE.md` |
| 6296-6341 | `design/README.md` |
| 6353-6378 | `docs/ops/self_heal_claude_fixer.md` |
| 6398-6519 | `docs/ops/HANDS_OFF_DELIVERY.md` |
| 6528-6543 | `docs/ops/INCIDENT_LEDGER.md` |

**Provenance moved here**

| 25.0.1 lines | what |
|---|---|
| 5218-5228 | §24 header version tags and status banner: 4.6.0 ratified APPROVE_AGENTS_POLICY_4_6_0 1682 9dd9e7d6b (PR #1687), 5.0.0 ratified 1686 d51b6c50e (PR #1688); status corrected in 5.1.0; verification workspace refs. |
| 5245-5254 | §24.1 supersession bookkeeping: §23.23 (10.0.0) superseded "fires host lanes and decides nothing"; ACTIVE since APPROVE_AGENTS_POLICY_10_0_0 1736 7f275d279 (2026-10-14). |
| 5359-5362 | §24.5 25.0.0 note: the train service pushed train/*; train retired 2026-10-27. |
| 5414-5419 | §24.10 status: 5.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_5_0_0 1686 d51b6c50e, PR #1686 merged 0ec320486; requested as 4.7.0. |
| 5495-5497 | §24.10 install mechanics: operator installed the scope with ~/n8n-maturity-verification/packets/agents-4-7-0/install_execution_ops_scope.py (bin/guard ALL_TIERS, guard-lib.sh, broker.execution_ops rule). |
| 5507-5513 | §24.11 status: 14.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_14_0_0 1838 0d4940cda, PR #1838 merged 0c5998042. |
| 5586-5603 | §24.11 ratifying edit (2026-10-16): §0 rule 2 sentence and adapter copies; pin updates. |
| 5605-5612 | §24.12 status: 15.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_15_0_0 1852 fc56728962fd51c94b3dc8cfd67e2df334eda88f (PR #1852 comment 6324859562). |
| 5622-5633 | §24.12 named addition (20.0.0): the /tmp hygiene lanes, operator 2026-10-22, PR #1954; standing approval id operator-20261022-tmp-hygiene-delete. |
| 5688-5711 | §24.12 ratifying edit (2026-10-21): §0 rule 6 sentence and §17 entry; pin updates. |
| 5715-5722 | §25 preamble: 17.0.0 release train (train merges, train/* pushes, D1 delegation, D2 App, windows, Run now) retired by the operator 2026-10-27; §25.1–§25.9 not reused. |
| 5726-5728 | §25.10 "Status: PROPOSED in 25.0.0" — a missed ratifying edit (25.0.0 ACTIVE); replaced the 24.0.0 text and #2208's unratified rewrite. |
| 5786-5793 | §26 status: 18.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_18_0_0 1931 894bbd954ca174453e7339d30157e082d4403c84. |
| 5855-5857 | §26.6: ratifying 18.0.0 granted none of the proposed rows, created no table and moved no reader. |
| 5863-5869 | §27 status: 19.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_19_0_0 1962 bb54a14a…; CARVEOUT_STATUS flipped to ACTIVE at ratification. |
| 5915-5920 | §27.3: supersedes decision D3 (resume/scope only at host CLI or Telegram button) and the kill switch's terminal-only clear. |
| 5948-5954 | §28 status: 20.0.0 ACTIVE (MAJOR), ratified APPROVE_AGENTS_POLICY_20_0_0 2013 c766b497…; nine clause edits recorded in the appendix. |
| 5966-5971 | §28.1: the ratifying edit added the §7 standing trap "Timeouts, reaper caps and kill windows — measured, never guessed", absorbing withdrawn 18.1.0. |
| 6110-6113 | §28.7 ratifying-edit pointer (record in the Version history appendix). |
| 6115-6118 | §28.8 status: 20.1.0 ACTIVE (MINOR), ratified APPROVE_AGENTS_POLICY_20_1_0 2019 d24a2905…. |
| 6141-6145 | §28.9 status: 20.2.0 ACTIVE (MINOR), ratified APPROVE_AGENTS_POLICY_20_2_0 2073 c1795184…; operator request quote. |
| 6179-6183 | §28.10 status: part of 20.2.0; narrows §26.5. |
| 6206-6211 | §28.11 status: part of 20.2.0; operator quote; weekly Rulebook enforcement audit lists open exceptions. |
| 6235-6241 | §28.12 status: 20.3.0 ACTIVE (MINOR), ratified APPROVE_AGENTS_POLICY_20_3_0 2107 72bd48f4…. |
| 6289-6294 | §28.13 status: 21.0.0 ACTIVE, ratified APPROVE_AGENTS_POLICY_21_0_0 2128 f8a89dc6…; operator approved the Design Workflow 2026-10-25. |
| 6343-6351 | §28.14 status: 21.0.0 ACTIVE; arming = ACTIVE status, no separate grant; shadow before 2026-10-25; replaces never-ratified 13.0.0 fixer proposal. |
| 6380-6396 | §28.15 status: 21.0.0 ACTIVE (MAJOR); class rationale; 25.0.0 rewrote items 2, 3, 5, 7, 8, 9 and added item 10. |
| 6478-6479 | §28.15 item 7: the solo release-delegation class retired with the release train (25.0.0). |
| 6492-6494 | §28.15 item 8(c): hands_off_policy.py gate in PRs #2115, #2118, #2125 must key on the 21.0.0 version row. |
| 6521-6526 | §28.16 "Status: PROPOSED in 25.0.0" — missed ratifying edit; watchers, supervisor and page shipped in #2238. |
| 6547-6549 | §29 "Status: PROPOSED in 25.0.0 (adds obligations only)" — missed ratifying edit. |
