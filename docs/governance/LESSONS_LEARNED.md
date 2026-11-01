# Lessons learned — why the rules in AGENTS.md exist

```
Status:      ACTIVE
as_of:       2026-10-27
Owner:       coordinator
```

Every rule in AGENTS.md was written after a failure in this repository. AGENTS.md 26.0.0 keeps each rule and a one-line
cause (`*Cause: <date> — <what> (LESSONS <id>).*`); the story behind it lives here. The ids are permanent. The complete
25.0.1 text these were taken from is preserved byte-exact at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`; the line
ranges below refer to it.

Add a lesson in the same PR as the rule it explains. A lesson is history, not instruction: if it implies something an
agent must do, that belongs in AGENTS.md as a rule.

## §0–§6, §10–§11, §14–§17, §19–§22 and the version policy

### L0-01 · A policy rewrite merged with no version bump (2026-10-27)

PR #2208 rewrote §25.10 and §28.12 without changing Policy-Version or adding a history row, and nothing failed. 25.0.0 made CI check the bump on every AGENTS.md diff.

*Rule:* Document version policy — every change bumps the version. AGENTS.md 25.0.1 lines 123-129.

### L0-02 · A ratifying edit missed three status lines (2026-10-27)

After 25.0.0 was ratified, §25.10, §28.16 and §29 still read 'Status: PROPOSED in 25.0.0', so an agent could not tell whether they bound. 26.0.0 requires a ratifying edit to flip every in-body status line.

*Rule:* Document version policy — a ratifying edit changes every status line. AGENTS.md 25.0.1 lines 5726, 6523, 6549.

### L0-03 · The standard outgrew its readers (2026-10-27)

AGENTS.md grew from 1,662 lines (2026-09-02) to 7,401 (660 KB) in eight weeks; a line-by-line review measured about 31% current rules, 34% history, 15% reference, 14% gaps and stale text. Agents that read fifteen lines and stop were the reason §0 exists.

*Rule:* Document version policy — what never goes in this file. AGENTS.md 25.0.1 lines whole file.

### L0-04 · Peer promotes found by accident (2026-08-31)

Six promotes from a peer session inside one hour were discovered only during a census; that discovery is the only reason its measurements were stamped correctly.

*Rule:* §1 Session protocol; §11. AGENTS.md 25.0.1 lines 189-205, 2679-2680.

### L0-05 · The behaviour rail is code, not a variable (2026-08-30)

MBI_BEHAVIOR was reasoned about as an env var; nothing reads it. The enforcement is the unconditional BehaviorWriteRefused raise in apply_cognition(), which no setting can switch off.

*Rule:* §2 The rail is code, not a setting. AGENTS.md 25.0.1 lines 217-230.

### L0-06 · Personal data in a public repository (2026-10-27)

On 2026-10-27 the repository was briefly made private and then public again. An audit of tree and full history found no live credential, but found a full account number, personal, benefit and family details, real holdings, the operator's email and Telegram chat id in files present since the first commit (2026-04-18).

*Rule:* §2A The repository is public. AGENTS.md 25.0.1 lines new.

### L0-07 · Egress was enforced by convention (2026-08-31)

Every outbound model call applied the egress rule by hand at its own call site. A single sanitiser (scripts/lib/cio_egress_sanitiser.py sanitise_for_external) was later built and the bridge calls it; the file still said 'not built' until 26.0.0.

*Rule:* §2A A single egress point. AGENTS.md 25.0.1 lines 276-285.

### L0-08 · Green from the wrong artifact (2026-08 to 2026-10)

A gate affirmed a declaration read out of a SyntaxError; a test asserted literals from the file it validated; a liveness monitor was never scheduled; a repricer wrote a tree nobody served; an event fired 1,100 times and routed to nobody.

*Rule:* §3 The governing principle. AGENTS.md 25.0.1 lines 343-356.

### L0-09 · Measurements that only looked like conflicts (2026-08)

Four measurements of lineage completion looked like a four-way disagreement and were all correct at their own as-of; a 'structural' 35,928-event skip was a 149-name registry gap under 58,682 rows of extraction noise.

*Rule:* §5 Metric rules. AGENTS.md 25.0.1 lines 398-414.

### L0-10 · A dry run that consumed the work it previewed (2026-09-20)

drain_llm_deferred.py --dry-run called claim_due() before testing the flag, stranding the previewed row in 'claimed' forever (PR #1143). The fix made the preview a separate read-only query that returns before claim_due is reachable.

*Rule:* §6 A dry run must not be able to reach the mutation. AGENTS.md 25.0.1 lines 445-460.

### L0-11 · A tool's dry-run flag that does the thing (2026-09-14)

gog drive upload --dry-run (gog v0.12.0) uploads anyway. The trap had drifted into the version-history appendix, where nothing binds.

*Rule:* §6 A dry-run flag that performs the action is not a dry run. AGENTS.md 25.0.1 lines 6627.

### L0-12 · A long-lived process kept the old release (2026-09-18)

The governed bridge's cwd stayed on release 0162d0f19 while portfolio-server served 71535687d, because WorkingDirectory=…/CURRENT does not re-resolve after the symlink moves.

*Rule:* §10 A promote restarts only the bound units. AGENTS.md 25.0.1 lines 2630-2637.

### L0-13 · A merged timer that never ran (2026-09-13)

tradeai-operator-answer-quality.timer was merged and promoted and ran only once it was installed separately; a deploy does not install user units.

*Rule:* §10 A deploy does not install new user units. AGENTS.md 25.0.1 lines 2638-2643.

### L0-14 · A flood bounded by watching it (2026-09)

A 1,100-event flood was bounded at 48h by observing it during the incident; three days of undelivered briefs and a ten-hour broken census also happened with no written rollback answer.

*Rule:* §10 Bound the blast radius before enabling. AGENTS.md 25.0.1 lines 2645-2663.

### L0-15 · A rewrite that claimed to preserve (2026-09)

A rewrite of AGENTS.md asserted the previous content was preserved inside it, and ten operational items were gone; only a diff found it.

*Rule:* §14 A rewrite that claims to preserve is a claim — diff it. AGENTS.md 25.0.1 lines 3409-3413.

### L0-16 · A ratified policy that never merged (2026-10-26)

The operator ratified AGENTS.md 23.0.0 (Telegram remote grants retired, PR #2185) and CI went green, but the PR never merged after the release train was retired; main kept the retired rule for a day. 26.0.0 folds the policy in.

*Rule:* §8 Grants (Telegram retired); §17 decision channels. AGENTS.md 25.0.1 lines 2107-2197.

### L0-17 · Private visibility meters free CI (2026-10-27)

October's gross Actions usage was $637.14, all covered by the public-repo discount; private on GitHub Pro includes 3,000 minutes a month, about one day of this CI.

*Rule:* §18 Repository visibility is a CI invariant. AGENTS.md 25.0.1 lines 3781-3787.

## §7 Standing traps

### L7-01 · ast.parse passed files Python refuses to import (2026-08-30)

A parse sweep using ast.parse passed files with misplaced __future__ imports or a BOM that Python refuses to import. compile() enforces what import enforces.

*Rule:* §7 Use compile(), never ast.parse. AGENTS.md 25.0.1 lines 476-477.

### L7-02 · A parent-class except laundered an import failure (2026-08-30)

`try: from lib.X / except ImportError: from scripts.lib.X` could never work: ModuleNotFoundError subclasses ImportError, both arms loaded the same file, and the real failure was inside it.

*Rule:* §7 Never catch the parent class of the error you handle. AGENTS.md 25.0.1 lines 481-483.

### L7-03 · One edit churned 2,298 lines of the bridge (2026-09-14)

Conditional line-ending conversion has produced \r\r\n across whole files that still parse and pass tests; Path.read_text/write_text silently normalise CRLF. On 2026-09-14 one edit to scripts/lib/cio_governed_model_bridge.py produced 2,298 lines of churn.

*Rule:* §7 Route every text edit through safe_text_edit. AGENTS.md 25.0.1 lines 484-491.

### L7-04 · A JSON re-dump rewrote every escaped line (2026-09-14)

config/llm_process_registry.json stores \u escapes (ensure_ascii=True, indent=2); re-dumping it with a literal arrow rewrote every line carrying one.

*Rule:* §7 Re-dump a JSON registry exactly as it was dumped. AGENTS.md 25.0.1 lines 492-494.

### L7-05 · An earlier test's sys.modules stub broke later tests (2026-09-14)

tests/test_oco_dd_gaps.py leaves an empty telegram_alert in sys.modules via setdefault, and other tests cache producers; a path-loaded module not registered in sys.modules fails dataclasses with 'NoneType' object has no attribute '__dict__'.

*Rule:* §7 A test of new producer or transport code loads the module by file path. AGENTS.md 25.0.1 lines 495-499.

### L7-06 · A test that needs runtime data fails in every worktree (2026-09-14)

test_advisory_desk_phase2::test_build_evidence_stats builds the desk from runtime data; it fails in every worktree and passes in the dev tree.

*Rule:* §7 A worktree has no live data. AGENTS.md 25.0.1 lines 500-502.

### L7-07 · The SOP control-surface digest moved to the runtime attestation (2026-09-25)

Since 2026-09-25 the four formerly bound SOP evidence files say AT_HEAD and the digest is computed at HEAD and recorded in the runtime attestation; a committed digest fails EVIDENCE_EMBEDS_VOLATILE_DIGEST.

*Rule:* §7 Never write a control_surface_digest into the SOP evidence files. AGENTS.md 25.0.1 lines 506-510.

### L7-08 · A convenient reproduction masked a cron-only import failure (2026-08-30)

Cron runs scripts by path, so sys.path[0] is <root>/scripts and the implicit `scripts` namespace package does not resolve; `python -c` prepends cwd and hides the failure entirely.

*Rule:* §7 Reproduce the cron form, not a convenient one. AGENTS.md 25.0.1 lines 511-515.

### L7-09 · Process-local caps and dedupes did not exist (2026-08-31)

_dedupe_cache, _hourly_counts and _last_health lived in module-level dicts of one-shot processes; mark_sent() wrote to a dict that died microseconds later, and a 'max 2 per day' cap passed on every cold start.

*Rule:* §7 A guarantee that spans invocations needs durable state at one path. AGENTS.md 25.0.1 lines 517-523.

### L7-10 · Mode flags set OFF silently disabled controls (2026-08-31)

TELEGRAM_NORMALIZATION_MODE=OFF left two tables at 0 rows; the router at runtime_mode OFF made correct routing unreachable; the digest queue held one row from May while code reported messages queued.

*Rule:* §7 A mode flag that disables a control is a finding. AGENTS.md 25.0.1 lines 524-528.

### L7-11 · Fixing an exception silenced a live outage alarm (2026-08-31)

Fixing an UnboundLocalError dropped the orchestrator's stage-error count from two to one, so it exited 0 — ten silent successes while a Finviz outage aged from 64h to 97h.

*Rule:* §7 Never fix an alarm without fixing what it alarmed on. AGENTS.md 25.0.1 lines 529-533.

### L7-12 · Bounds keyed on the wrong quantity drifted (2026-08-31)

splitlines()[-500:] against a time-based TTL produced 71 sends by losing its own history, and a weekend gate asked whether today is Saturday rather than whether the lookback window contained hours the writer runs.

*Rule:* §7 Bound by the thing you are bounding. AGENTS.md 25.0.1 lines 534-539.

### L7-13 · Unmeasured caps killed two pipeline_critical pipelines every run (2026-10-22)

trade_ai_orchestrator at the 20 m reaper cap was SIGTERMed at 1216–1377 s on every market-hours run 2026-10-21/22 (20 + 22 failed); symbol_enrichment under orphan_wait_s 30 went 224 failed / 1 success in 36 h.

*Rule:* §7 Never lower a timeout, reaper cap, orphan wait or tick deadline without measured evidence. AGENTS.md 25.0.1 lines 566-572.

### L7-14 · A runtime measured under a kill was survivor bias (2026-10-22)

'Enrichment takes 25–50 s' was the survivors of a 30 s kill; the uncensored distribution 2026-09-20..10-07 (n=3,178) is p50 136 s / p95 241 s / max 419 s, and the orchestrator's 1377 s is a floor.

*Rule:* §7 A runtime measured under a kill is censored. AGENTS.md 25.0.1 lines 573-577.

### L7-15 · Fail-open analyst caches destroyed three weeks of analyses (2026-09-01)

All seven ai_*.json analyst caches were overwritten 07:32–07:33 with 'Analysis unavailable — all LLMs failed', destroying analyses from 2026-08-11; each file kept its name, shape and a fresh mtime, so every staleness check read it as current.

*Rule:* §7 A producer that cannot produce keeps the prior value. AGENTS.md 25.0.1 lines 593-603.

### L7-16 · 'Newest copy wins' would have destroyed the last copies (2026-09-01)

The same seven files were newer on one root and 20–30× smaller; a newest-wins merge would have destroyed the last surviving copies, which existed only because a second diverging tree was not written by the failing job.

*Rule:* §7 Never conclude 'the newest copy wins'. AGENTS.md 25.0.1 lines 604-610.

### L7-17 · A tree-relative budget counter split traffic eight ways (2026-09-05)

brave_search._BUDGET_FILE resolved relative to the importing tree, so server and cron kept separate counters (one frozen at 2026-08-10), eight copies on the host; a dashboard reading the secondary counter reported monthly_pct 17.6 'ok' while the provider sat at its ceiling.

*Rule:* §7 Durable state at one path; search spend read from search_budget.json. AGENTS.md 25.0.1 lines 611-627.

### L7-18 · A provider limit invented in a comment was reported as fact (2026-09-05)

brave_search.py asserted '1,000/month free tier' for months; Brave's headers, read 2026-09-05, reported 50 req/s and no metered monthly window, and a reported limit of 0 means unmetered, not zero.

*Rule:* §12 Search providers — 'Provider ceilings come from response headers' (duplicate §7 rule retired). AGENTS.md 25.0.1 lines 628-634.

### L7-19 · A silent fallback made a dead engine look healthy (2026-09-05)

google was reported working twice: every result came from bing after a silent fallback, and isolated it returned zero with empty unresponsive_engines; engines that raised were fixed while the one returning zero successfully outlived them all.

*Rule:* §7 Ask which component produced the result. AGENTS.md 25.0.1 lines 644-653.

### L7-20 · Two SearXNG engines were configured and never registered (2026-09-06)

SearXNG's inactive: is a gate separate from disabled:; two engines installed cleanly, passed YAML validation and were absent from /config with no error. The installer now diffs its intended set against the running config.

*Rule:* §7 Configured is not registered. AGENTS.md 25.0.1 lines 654-658.

### L7-21 · A just-rotated log nearly proved a cron never ran (2026-09-06)

A cron was nearly reported as never firing four minutes after logrotate ran; syslog.1 held 308 invocations of it.

*Rule:* §7 A rotated log is not an empty log. AGENTS.md 25.0.1 lines 659-661.

### L7-22 · Five findings from assumed scope (2026-08-30)

python -c prepends cwd; a synthetic probe used a different import spelling; git add -A swept 14 unrelated files into a docs branch; event-bus cursors replayed 1,100 events at 12/cycle; git checkout origin/main -- . staged main over a branch's corrections.

*Rule:* §7 Before relying on a mechanism's scope, run the command that establishes it. AGENTS.md 25.0.1 lines 663-674.

### L7-23 · Working detectors answered an adjacent question (2026-08-30)

ast.parse sweeps, a skip aggregate, a presence-only board check, an invariance-keyed origination scan, a symlinked root control, a one-spelling bootstrap probe, OS-only scheduler search, import_module guards, a ** pathspec that under-reported 50 files as 3, and fixed-string greps each reported cleanly while structurally blind.

*Rule:* §7 Before trusting a zero, state what the detector keys on. AGENTS.md 25.0.1 lines 550-559,676-691.

### L7-24 · attempts_24h=0 for nine days hid a lane dying at subprocess.run (2026-09-06)

The deepseek lane's scheduler ran every weekday and died at subprocess.run (FileNotFoundError) before the child wrote the row attempts_24h counts, so every reader concluded nothing called it.

*Rule:* §7 A counter of completed work cannot tell never-started from failed. AGENTS.md 25.0.1 lines 693-700.

### L7-25 · Controls whose names asserted restrictions nothing enforced (2026-08-30)

CIO_TELEGRAM_INTERDICT, the situation detector's shadow flag and BLOCKED_ACTIONS_WHEN_NOT_READY asserted restrictions no conditional read; MBI_BEHAVIOR was reasoned about as a setting by two documents and an audit programme though it names no variable.

*Rule:* §7 A control's name is not evidence of its restriction. AGENTS.md 25.0.1 lines 702-729.

### L7-26 · An always-on P0 and a checker exception posed as findings (2026-09-06)

expected_release_pin.txt was written once on 2026-08-07 and never by promote, so the health inspector reported the same P0 for thirty days; it also called PortfolioValidator(live_dir=...) on an __init__ taking no arguments, so a TypeError replaced every portfolio check.

*Rule:* §7 A control's name is not evidence…(always-on shape); a checker exception is not a system finding. AGENTS.md 25.0.1 lines 731-744.

### L7-27 · Two operator litmus replies failed and named no sources (2026-09-13)

A question about SCHG got the whole re-entry book, and a sector question was answered from model knowledge while the reply called cash and holdings empty; no reply said where its facts came from (PRs #992, #998–#1001).

*Rule:* §7 Every operator reply leaves through finalize_operator_reply. AGENTS.md 25.0.1 lines 746-756.

### L7-28 · Data gaps were marked resolved when a job was only queued (2026-09-13)

Gaps were marked resolved on queue while most Maria, Steph and risk jobs failed on a 4,000-token input cap before reaching the model.

*Rule:* §7 resolved means proven. AGENTS.md 25.0.1 lines 774-779.

### L7-29 · A duplicate def silently replaced the cash formatter (2026-09-13)

A new _fmt_usd in the 3,700-line desk module replaced the whole-dollar cash formatter; Python raises nothing. The price helper is now _fmt_price.

*Rule:* §7 Grep ^def <name>( before adding a helper. AGENTS.md 25.0.1 lines 792-795.

### L7-30 · Agent numbers must come from the prompt; replays overstate (2026-09-13)

Rule G0 (GROUNDING_RULE, agent_number_grounding) demotes answers with unsupported numbers; a calibration replayed over stored rows checks against an input snapshot, not the sent prompt, so its flag rate is an upper bound.

*Rule:* §7 Numbers come from the prompt (rule G0). AGENTS.md 25.0.1 lines 765-768,780-784,796-798.

### L7-31 · The tagger cron sat commented out for two months (2026-09-06)

taxonomy_tagger's cron was commented out on 2026-07-02 after a lock timeout; the code was fixed the same day but only the code came back, and sector tagging sat at 5% for two months with nothing reporting it.

*Rule:* §7 A part of the spine found disabled is an incident. AGENTS.md 25.0.1 lines 800-809.

### L7-32 · A ticker-to-name map was nearly hand-rolled (2026-09-06)

An agent nearly hand-rolled a ticker-to-name table; the operator stopped it, and 4,997 Schwab instruments with descriptions and CUSIPs were already on disk.

*Rule:* §7 Never build a ticker or name map. AGENTS.md 25.0.1 lines 834-861.

### L7-33 · A no_match sentinel without a TTL would have foreclosed a corpus (2026-09-06)

taxonomy_tagger selected WHERE category_content IS NULL, so no_match was permanent; a bounded 20-row run gave 17 sentinels, 1 tag, 0 sectors, and the hourly cron at --limit 500 would have foreclosed ~85% of a 32,060-row backlog in ~64 hours.

*Rule:* §7 Every 'unclassifiable' sentinel has a shelf life. AGENTS.md 25.0.1 lines 1154-1160,1275-1286.

### L7-34 · 58% of tagged news mentioned other tickers (2026-09-06)

Tagging by the row's symbol column never read the body; 58% of tagged news articles mention other tickers, and a source quoted as the estimate's origin is not the subject.

*Rule:* §7 A mention's role is decided deterministically or left undecided. AGENTS.md 25.0.1 lines 948-980.

### L7-35 · A hand-written UPDATE split the cap registry from the database (2026-09-06)

A hand UPDATE left config/llm_process_registry.json at 200 / $0.30 while the database said 100000 / $1.25, and sync_cio_process_caps.py was scheduled nowhere to catch it.

*Rule:* §7 A process cap changes only through /caps. AGENTS.md 25.0.1 lines 1038-1061.

### L7-36 · A request-count cap read as a broken provider (2026-09-06)

The usefulness backfill died after exactly 200 calls having spent $0.0742 of $0.30 — 100% of daily_soft_cap; every caller saw HTTP 500, the bridge log carried no reason, and the cause was only in the JSON body.

*Rule:* §7 Diagnose a paid-lane outage at the bridge. AGENTS.md 25.0.1 lines 1063-1093.

### L7-37 · Escalation must stop and ask, once, past the router (2026-09-06)

Operator policy 2026-09-06 set free OAuth → DeepSeek Flash → notify and stop; on 2026-09-05 guard approvals classified P1_DIGEST were archived unseen, so the notification bypasses the router.

*Rule:* §7 Escalation is free, then one paid lane, then ask. AGENTS.md 25.0.1 lines 1095-1121.

### L7-38 · Recurring DDL collided with live readers (2026-09-06)

ADD COLUMN IF NOT EXISTS still takes ACCESS EXCLUSIVE; nine LockNotAvailable failures against live readers were recorded.

*Rule:* §7 Schema changes here are additive; DDL once, off-peak. AGENTS.md 25.0.1 lines 1163-1164.

### L7-39 · Fixing a lane's gates exposed a release-relative .env (2026-09-06)

Once the schedule/gate overlap and effective-model bugs were fixed, hermes-deep-research-local reached a database and died on DB_PASSWORD not found: hermes_staging_ingest resolved .env relative to its source tree, and a release has no .env.

*Rule:* §7 Credentials come from lib/env_bootstrap. AGENTS.md 25.0.1 lines 1266-1273.

### L7-40 · The integrity sweep rediscovered a session's defects unprompted (2026-09-06)

Run cold, scripts/run_integrity_checks.py found every defect a session had found by hand; its first run emitted 314 alarms, 309 of them a population debt, and its obvious fix for one finding (re-enabling taxonomy_tagger) would have destroyed a corpus.

*Rule:* §7 The integrity sweep reports and never repairs. AGENTS.md 25.0.1 lines 1288-1305.

### L7-41 · output_tables was a declaration nothing validated (2026-09-06)

Only api_v2.py read pipeline_stage_owner_map output_tables; ~20 of 31 pipelines declared tables that did not exist, symbol_enrichment wrote other tables, and social_ingest succeeded 34 times in 7 days without writing social_mentions.

*Rule:* §7 A pipeline's output_tables names a table that exists and that it writes. AGENTS.md 25.0.1 lines 1307-1334.

### L7-42 · Two integrity-check false positives nearly shipped (2026-09-06)

A check assumed created_at and reported the healthy trade_ai_scans (scanned_at) unreadable, and collapsing 'table missing' into 'no timestamp' understated eight P1s as cosmetics.

*Rule:* §7 A check discovers its column and keeps distinct states distinct. AGENTS.md 25.0.1 lines 1336-1344.

### L7-43 · rows_produced defaulted to 0 and broke the zero-rows alarm (2026-09-06)

PipelineRun defaulted _rows = 0; 16 of 20 callers never called .rows(), so pipeline_zero_rows fired on five pipelines that never recorded a non-zero. Unknown is now None.

*Rule:* §7 Unknown is not zero. AGENTS.md 25.0.1 lines 1362-1372.

### L7-44 · Four layers of success sat on an empty producer (2026-09-06)

strategy_rule_engine.py --all was scheduled nowhere, so strategy_rule_evaluations held 0 rows and cio_decision_engine, inner-joining it, made 0 decisions on 3,010 'successful' runs a week; cio_decisions was last written 2026-08-07.

*Rule:* §7 When a consumer inner-joins a table, check the producer's schedule. AGENTS.md 25.0.1 lines 1374-1390.

### L7-45 · Every concurrent PR conflicted on generated files (2026-09-06)

Six of six consecutive merges touched the same generated files (SOP digests, docs/INDEX.md, AGENTS.md, run_cio_hardening_ci.py); four conflict resolutions were all this, none a real disagreement.

*Rule:* §7 Resolve a generated file by recomputing it. AGENTS.md 25.0.1 lines 1346-1360.

### L7-46 · Normalising input hid an emitter's bug (2026-08-30)

Coercing 'ALEX' to 'alex' accepted a value the emitter never sent and hid the emitter's bug.

*Rule:* §7 Validate against a known set; never normalise input. AGENTS.md 25.0.1 lines 1406-1407.

### L7-47 · A pre-build check without the vocabulary produced duplicates (2026-08-31)

§13.5 required a pre-build search while the type vocabulary lived only in two diagram documents §19 did not list; a specification then proposed four new types where three were already registered.

*Rule:* §7 A standard that omits the vocabulary cannot enforce the pre-build check. AGENTS.md 25.0.1 lines 1408-1413.

### L7-48 · Operator binding: shared security research, no silos (2026-09-29)

The operator bound security research to be transparent across options, holdings, watchlists, re-entry, Hermes, Aegis and cross-asset routing, owned by the CIO; private per-desk thesis caches were declared a defect.

*Rule:* §7 Shared security research — NO SILOS. AGENTS.md 25.0.1 lines 1174-1180.

### L7-49 · Invocations and idle alarms misread lane health (2026-09-06)

'tagged 3 this run' measured content +1, sector +0; a sub-second drain 'Finished' meant an empty queue; the deepseek lane alarmed zero_non_error_24h while reporting 'No queued jobs'.

*Rule:* §7 Count durable rows, not invocations. AGENTS.md 25.0.1 lines 1392-1400.

## §7A, §8, §8A, §9

### L7A-01 · Three source-of-truth incidents in one week (2026-09-13)

Positional Finviz parsers put `Performance (10 Years)` into a 1–5 analyst column for five months (97.9% of rows); `CURRENT/data/*` was linked to persistent state while the dev tree was not (297 files diverged over 18 days, 79 ledgers grew on both sides, 40 of 192 API-read files stale); four of six catalyst-news chain slots were dead (Finnhub 401 since 07-27, NewsAPI never ran, Polygon and FMP paid-only). Nothing a program could read declared the source, the served copy or a retired provider.

*Rule:* §7A intro (registry is the only place). AGENTS.md 25.0.1 lines 1424-1436.

### L7A-02 · Data sources must be granted by the operator (2026-09-13)

Operator, verbatim: "audit to make sure that all of this is documented ... if any agent needs to write a new source they need to get a grant from the operator for approval and it needs to meet the methodology that you just developed." The dead slots, positional parsers and unlinked dev tree were all sources or writers that appeared without anyone deciding they should exist.

*Rule:* §7A Ownership and the grant. AGENTS.md 25.0.1 lines 1469-1473,1499-1501.

### L7A-03 · Served-copy split reconciled under an operator-approved merge rule (2026-09-13)

Phase 1 of the One Source of Truth plan ran only after a quoted dry run and the operator's merge rule (snapshots newer-wins with loser archived; append-only ledgers line-level union, both archived; nothing deleted). Receipt `persistent-state/data/runtime/served_copy_reconcile_receipt.json`; archive `~/trade-ai-releases/archive/served_copy_split_20260913/`, tripwired by the split monitor.

*Rule:* §7A Ownership — never reconcile divergent copies alone. AGENTS.md 25.0.1 lines 1595-1601.

### L7A-04 · Command Center checked against a live Schwab read (2026-10-06)

Account values and cash matched to the cent, but one position showed a wrong share count and cost basis, another kept a stale basis, a third waited four days for a reinvestment click, and moomoo was frozen at 2026-09-28. Causes: the repricer wrote an older copy over every moomoo write for eight days (no lock), and a basis check keyed by symbol compared the same ticker across two accounts and reverted PL's correct basis. Operator: "fix all of it, document fixes, edit agents.md with correct source of truth".

*Rule:* §7A Positions rules 2–3. AGENTS.md 25.0.1 lines 1605-1611,1636-1640.

### L7A-05 · Schwab ingest dropped transfer direction (2026-10-06)

Until 2026-10-06 the Schwab ingest lost the direction of `Security Transfer Out` / `Journaled Shares Out`; reinvestments were grouped by a missing orderId. After the fix, ledger lots reproduce the broker for every Schwab position.

*Rule:* §7A Positions rule 7. AGENTS.md 25.0.1 lines 1664-1667.

### L8-01 · CURRENT rotated and PROMOTE OK re-pinned a stale release (2026-08-30)

`CURRENT` rotated three times in fifteen minutes, and a `PROMOTE OK` line was printed while the live directory pointed at a stale release; a `gh pr merge` that printed nothing had not merged.

*Rule:* §8 traps — resolve CURRENT. AGENTS.md 25.0.1 lines 1760-1763.

### L8-02 · GitHub Actions quota block read as test failures (2026-08-27)

Red runs with 0 steps, empty runner_name, 2–5 s and empty logs were a billing quota block; debugging the diff wasted time. `docs/ops/GITHUB_ACTIONS_QUOTA_INCIDENT_2026-08-27.md`.

*Rule:* §8 traps — quota block. AGENTS.md 25.0.1 lines 1764-1765.

### L8-03 · A signal writer failed for 24 days; three detectors told nobody (2026-08-31)

An alarm fired 171 times into a bare `except` on an import that never existed, a durable audit went CRITICAL surfaced by nothing, and that audit then read OK because zero input made its condition false. Same shape as STOP_HIT_CLOSE: 98 days importing `telegram_bot`, a module in no tree.

*Rule:* §8 traps — guard verified by presence. AGENTS.md 25.0.1 lines 1768-1774.

### L8-04 · Repaired alarm still reached nobody (2026-08-31)

`send_alert` → `send_telegram` made the import resolve, but the router classified the CRITICAL `P1_DIGEST` into `report_capture`'s `reports_archive`, which nothing delivers. The repair was verified by presence; a firing test one wave later caught it.

*Rule:* §8 traps — repairing the reason. AGENTS.md 25.0.1 lines 1775-1780.

### L8-05 · signal_flow_audit read OK through a 24-day outage (2026-08-31)

Zero GO scans made `go>0 and after==0` false, so the audit read healthy. The state already had a name, `NO_GO_TODAY`, emitted by another writer into the same table.

*Rule:* §8 traps — two states cannot express no input. AGENTS.md 25.0.1 lines 1781-1785.

### L8-06 · Invalid mutations twice in one session (2026-08-31)

A 'fix a swallowed alarm' mutation landed on a handler whose try had no alarm call; a dotenv-absent simulation patched `builtins.__import__`, defeating the sys.modules stub under test.

*Rule:* §8 traps — invalid mutation. AGENTS.md 25.0.1 lines 1786-1790.

### L8-07 · A timer that never once executed (2026-09-06)

`hermes-deep-research-local.timer` ran 22:00–05:35 ET behind a peak guard allowing 10:00–21:00 ET; every fire logged `SKIPPED_DEEPSEEK_PEAK` and exited 0, so health read success with `attempts_24h=0`.

*Rule:* §8 traps — schedule and gate disjoint. AGENTS.md 25.0.1 lines 1797-1803.

### L8-08 · Spend guard keyed on a stale variable (2026-09-06)

`flash = primary_provider() == "bridge_flash"` was computed at entry; the overnight branch then switched to a free OAuth lane and the guard refused a run that cost nothing. It now keys on the effective model.

*Rule:* §8 traps — gate re-reads effective value. AGENTS.md 25.0.1 lines 1804-1810.

### L8-09 · Proof deferred to a natural fire; the grant expired (2026-10-11)

C1 stage-runner manifest flips (2026-10-10/11): flip 1's proof was deferred to its 10:50 ET natural fire, flip 2 waited on it, and the grant expired before either was proven. Operator 2026-10-11 ~09:22 ET, verbatim: "When a agent is developing and building something out, it should do dry test and unit test and validate before it's deemed as working, and then the natural schedules can run, but we do not wait for natural schedules."

*Rule:* §8.1 Working means validated now. AGENTS.md 25.0.1 lines 1752-1756.

### L8-10 · Research queue failures hidden behind a healthy store (2026-09-14)

`hermes_external_research` was healthy (56/57) while 62% of `data/cio/hermes_research_requests.jsonl` requests failed in the week with no alarm; an unlocked load-modify-replace of the 30 MB projection lost 32 enqueued requests; 129 CALLER_DAILY_CAP denials were refused then asked of nobody until the free fallback (PR #1045).

*Rule:* §8 Subsystem traps — Research. AGENTS.md 25.0.1 lines 1828-1867.

### L8-11 · Self-healing loop whose retries all exited 127 (2026-09-14)

`claude_escalation_handler` rewrote `.venv/bin/python` inside absolute paths; every retry exited 127 (36,365 times, 08-07 to 09-14) while logs said fixes were tried.

*Rule:* §8 traps — self-healing loop. AGENTS.md 25.0.1 lines 1877-1881.

### L8-12 · Data litmus failures (2026-09-14)

Finviz Market Cap/Shares Float are millions and Average Volume thousands, stored as `market_cap_b`/`avg_vol_m` (1,000× mislabel); 16% of 09-11 `market_quotes` closes from IEX were >1% off the consolidated tape; `rvol` before 09-14 had universe median 3.4–4.8; a sub-one-share Schwab price is value because the transport divides by max(qty,1).

*Rule:* §8 Subsystem traps — Finviz, Prices. AGENTS.md 25.0.1 lines 1885-1903.

### L8-13 · Spend measured three ways (2026-09-14)

Real (`estimated_cost_usd`), counted (`llm_cost_reservations`, conservative on failures) and projected (32k-token worst case) differed; a $0.50 worst-case cap refused research on phantom money; `caprace_` synthetic rows counted as production spend; the $2.00 host cap was shadowed by a Bitwarden-rendered 0.50.

*Rule:* §8 Subsystem traps — Spend. AGENTS.md 25.0.1 lines 1905-1916.

### L8-14 · Cron environment and calendar windows (2026-09-14)

`data_source_report` never recorded alpha_vantage for four months because cron does not load `.env`; `CURRENT_DATE - 2` emptied social-scalp discovery every Monday; retention aborted a whole policy on a few FK-referenced rows (now `db_retention.fk_guard`).

*Rule:* §8 Subsystem traps — Cron environment. AGENTS.md 25.0.1 lines 1919-1930.

### L8-15 · Postgres ENOSPC; Command Center false-green (2026-09-18)

Root volume filled (release trees, Postgres logs); main Postgres hit ENOSPC, WAL PANIC and stayed down (~04:10 ET) while `/api/health` stayed ok; reclaiming ~41 GB did not restart it; orchestrator slots wrote `ticker_count > 0` with zero primary rows, so PARTIAL was the contract telling the truth. Lasting controls PR #1068. Runbook moved to `docs/ops/POSTGRES_MAIN_ENOSPC_2026-09-18.md`.

*Rule:* §8 traps — green /api/health is not a database. AGENTS.md 25.0.1 lines 1955-2023.

### L8-16 · Agent controls audit — Pilot Ready (17/30) (2026-09-18)

Measured on CURRENT `2d4b6c0f0`: the router write-gate classified `buy 100 shares of AAPL at market` as read_only (since fixed: `WRITE_WORDS`/`_TRADE_WRITE_RE` include trade verbs); prompt-injection defence PARTIAL (structural typing only; `agent_collab.get_agent_context` injects raw peer summaries); Hermes/Iris/`tradeai-cio-reactive` oneshots stayed failed with timers re-firing every ~2 min; alert policy `runtime_mode: SHADOW`; RAG empty for unknown symbols; 0% grounding flag rate while listing unsupported numbers. Evidence: `~/trade-ai-audits/AGENT_CONTROLS_AUDIT_2026-09-18.md`.

*Rule:* §8 traps — failed oneshot; Subsystem traps — Router. AGENTS.md 25.0.1 lines 2025-2105.

### L8-17 · Telegram remote guard grants retired (2026-10-26)

Remote approval by Telegram (`bin/guard request` → `/approve <CODE>` or inline button, settled by the callback poller) ran from 2026-09-06; the answer deadline went 15 min → 4 h after a request expired overnight, and the window was raised from 1 h to 12 h with `MAX_GRANT_USES` 500. Lessons kept: an approval request must never be routed into a digest; `chat_id` is the enforced identifier and `from_id` only metadata, so a group chat lets any member approve. The operator ratified 23.0.0 on 2026-10-26 (PR #2185): grants come only from the keyboard or Ops → Controls.

*Rule:* §8 Guard grants. AGENTS.md 25.0.1 lines 2107-2197.

### L8-18 · Green CI reported on a sliver of the suite (2026-08-30)

2026-08-30: the hardening runner named 49 of 1,009 test files (4.9%); a later count gave 59 of 1,027 (5.74%) behind the only required context. Measured 2026-10-27 with `check_test_coverage.py`: 1,500 of 2,425 (61.9%) registered, 919 inherited unlisted; PRs run a selection.

*Rule:* §8 Know what CI green means. AGENTS.md 25.0.1 lines 2199-2203.

### L8-19 · Testing standards — the failures behind them (2026-08-31)

A coverage gate caught the §0 drift guard unregistered (#734); a PR shipped past a test that only read source text; `assert status == "DONE"` went red on an honest downgrade; a dark-contract gate exited 0 on an uncompilable file; an origination scan returned zero because prose never lands in an invariance bucket; a 'no fake alpha' test was green precisely when there was no alpha; a helper test stayed green after the caller reverted to `rglob`; two runtime-path tests passed locally and failed in CI where tree and state root coincide (2026-09-06).

*Rule:* §8A Testing standards. AGENTS.md 25.0.1 lines 1791-1793,1816-1822,2308-2335.

### L8-20 · Comms idempotency key restarted alerts as first events (2026-09-14)

Without `observation_version` (body hash plus minute), every later alert with the same opening became the first event again; check `status_transition_illegal` counts before trusting the Communications page.

*Rule:* §9.1 dedupe key. AGENTS.md 25.0.1 lines 1883.

### L9-01 · Three identical briefs shipped (2026-08-30)

The dedupe key's only distinguishing part was a fresh run id, so three identical briefs went out.

*Rule:* §9.1 dedupe key. AGENTS.md 25.0.1 lines 2349-2351.

### L9-02 · Communications page showed undelivered alerts as delivered (2026-09-05)

`_best_effort_comms_publish` hardcoded `LEGACY_DELIVERED`; the first guard read only `send_telegram` and passed while `send_telegram_document` settled every row, failed sends included, as delivered.

*Rule:* §9.1 accepted is not delivered. AGENTS.md 25.0.1 lines 1811-1815,2370-2380.

### L9-03 · Bypass senders moved to notification intents (2026-10-10)

The first guard approval request printed `telegram=sent` while the router suppressed it; `bypass_router=True` fixed that by skipping dedupe and receipts too. PR #1685 (operator 2026-10-10) moved the 30 measured bypass senders; scheduled reports had bypassed the router and reached the phone at night.

*Rule:* §9.1 P1, bypass, P2. AGENTS.md 25.0.1 lines 2381-2407.

### L9-04 · Alarm coverage measured (2026-08-31)

11 of 141 `send_telegram` sites had firing tests; 556 alarm-path imports checked, 0 unresolved; 65 pure swallows and 46 log-only handlers at baseline.

*Rule:* §9.1 alarm firing test. AGENTS.md 25.0.1 lines 2416-2425.

### L9-05 · Store-cadence monitor first run (2026-08-31)

It reported `strategy_signals` SILENT at 581 h and `paper_trade_proposals[momentum_scalp]` SILENT at 1496 h; the unscoped table read LIVE at 0.6 h because other strategies kept writing it.

*Rule:* §9.1 store cadence. AGENTS.md 25.0.1 lines 2427-2432.

### L9-06 · Operator comms audit (2026-08-31)

155 producers, ~50 direct API paths and 34 router bypasses in 30 files; `sent_telegram` 0 of 864 and `telegram_sent_at` 0 of 932 rows; 40 stop-warning interrupts in four days (83% of its table); `Data quality: OK` asserted under an ATTENTION verdict; a Markdown 400 triggered an unlogged plaintext resend.

*Rule:* §9.1 chokepoint, receipts, transitions. AGENTS.md 25.0.1 lines 2436-2470.

### L9-07 · settle_delivery omitted ownership coordinates (2026-09-09)

Without `delivery_owner`/`gateway_mode` in `provider_coordinates`, `gateway_canary_delivery` gave false negatives on delivered messages (fixed PR #926; operator-approved inclusion 2026-09-09).

*Rule:* §9.1 receipts. AGENTS.md 25.0.1 lines 2445-2454.

### L9-08 · Phone replies refused and garbled (2026-09-14)

The 13:47 AXTI answer (4,571 characters) was refused twice with HTTP 400 while the poller logged 'replied'; a resent answer's raw provenance tail read as 'Gibberish'; the editor once tagged AP, TROW and F in an ARMP alert. Operator: "If it needs to be broken up across three or four messages, then do so."

*Rule:* §9.1 phone replies. AGENTS.md 25.0.1 lines 2474-2492.

### L9-09 · Lane availability defaulted to True (2026-08-02)

`available()` returned True for any unrecognised lane until 2026-08-02, routing every DeepSeek call to local Gemma; a brief rendering complete with a section silently absent hid a 97-day outage.

*Rule:* §9.2 lane per §12, no bare except. AGENTS.md 25.0.1 lines 2498-2505.

### L9-10 · Shared process id and a single-threaded bridge (2026-09-14)

88% of the week's spend sat under `advisory_desk_opinion` carrying six callers; DeepSeek held calls ~906 s with keep-alive bytes so a 90 s read timeout never fired and the single-threaded bridge queued everyone (15:15–17:17 ET); logged $5.45 recomputed to $5.42.

*Rule:* §9.2 bridge caller names itself. AGENTS.md 25.0.1 lines 2516-2531.

### L9-11 · Per-lane grants moved 4 lanes in two days (2026-10-09)

One import and one grant per lane moved 4 lanes in two days against 438 cron lines, so a reviewed dispatcher registry-row merge became the lane decision.

*Rule:* §9.3 scheduler entry operator-only. AGENTS.md 25.0.1 lines 2539-2544.

### L9-12 · Re-enabled crontab line left undeclared (2026-09-13)

Re-enabling the read-only Moomoo sync under `timeout --kill-after=30s 10m` left an undeclared job; lane `moomoo-live-read-sync` was declared in PR #1001.

*Rule:* §9.3 crontab line edit. AGENTS.md 25.0.1 lines 2560-2565,1926-1929.

### L9-13 · Paid lane died unnoticed; backfill ran outside the window (2026-09-17)

DeepSeek 402'd for three days (09-17..09-19) and nothing noticed; a usefulness backfill (~31,000 rows, temporary $7 cap) ran around the clock under a shared id, putting 60% of the week's spend outside the window (2026-09-06–09).

*Rule:* §9.3 paid work window, backfill. AGENTS.md 25.0.1 lines 2566-2582.

### L9-14 · Checkout-only writer froze the served copy (2026-09-08)

`portfolio_dividend_calendar.py` refreshed `dividend_calendar.json` in the dev tree daily while the served copy sat at 2026-09-04 (~100 h stale); the Schwab journal cron's `>> logs/schwab_ingest.log` ran 281 h stale in the served view.

*Rule:* §9.4 writes land on the served path. AGENTS.md 25.0.1 lines 2595-2605.

### L9-15 · Cash block age taken from its freshest part (2026-08-30)

A 27-day-old small balance made the cash block 27 days old; the composition timestamp hid it.

*Rule:* §9.5 as_of per block. AGENTS.md 25.0.1 lines 2356-2358.

## §12, §13, §17A, §18

### L12-01 · A paid lane died for three days and nothing said so (2026-09-19)

The DeepSeek account ran to -$0.09 and returned HTTP 402 on every call 2026-09-17..19 (660+ failures; hermes_external_research ate 172); no health check read llm_consumption_log.error_message, and failed calls still settled cap reservations, draining request pools. Fixed by the llm-provider-health monitor (now a health-tick step) and an OAuth fallback for risk/steph/tax.

*Rule:* §12 Cap consumption is not evidence of work. AGENTS.md 25.0.1 lines 2733-2773.

### L12-02 · Caps compared against worst-case projections, not real spend (2026-09-14)

One week showed $214.61 projected against $4.73 real; the live bridge carried a forgotten $7.00 backfill override and the portfolio server $1.50. The operator ratified a durable $2.00/day of actual spend and retired the override.

*Rule:* §12 The ruling cap is LLM_GLOBAL_DAILY_USD_CAP = 2.00. AGENTS.md 25.0.1 lines 2784-2797.

### L12-03 · Free search rescue first proven live (2026-09-16)

At 12:45:01Z on a91d7b3ba, Brave at 25/25 produced two CALLER_DAILY_CAP refusals that the self-hosted searxng provider answered (free_answered: 2), the first non-zero searxng counters in the ledger. Free usage is metered in the same ledger as paid.

*Rule:* §12 One ledger: lib/search_budget. AGENTS.md 25.0.1 lines 2696-2703.

### L12-04 · Out-of-window paid work was silently dropped (2026-09-20)

Before PR #1134 (live at 498ecd0f6) work reaching gate_and_generate out of window logged PEAK_SKIP, exited 0 and vanished: no row, no retry, no way to tell ran from skipped. It now queues in llm_deferred_requests and a drainer re-issues it; the process-boundary wrapper still drops.

*Rule:* §12 Two gates, and only one queues. AGENTS.md 25.0.1 lines 2868-2890.

### L12-05 · Scheduled paid work ran outside the operator's window (2026-09-14)

Measured 09-10..09-14: $0.58 of $2.46 ran outside the window (holdings research 08:00 $0.19, hourly usefulness scorer $0.08, due-diligence $0.03, $0.22 under a shared id); the prior week's $5.45 was 60% outside, mostly a one-time backfill. The operator set the 09:00-21:00 ET weekday/weekend window, never inside DeepSeek peak.

*Rule:* §12 Scheduled paid work runs weekdays 09:00-21:00 ET. AGENTS.md 25.0.1 lines 2859-2867, 2916-2918.

### L12-06 · An in-memory budget and a frozen second ledger hid real search spend (2026-09-05)

An in-memory cache did not survive cron invocations, so a 1,000-call monthly budget vanished in three weeks; a frozen brave_search_budget.json read like a live ledger and made Brave look unused while the real ledger showed September traffic. The second counter was retired rather than reconciled.

*Rule:* §12 One ledger: lib/search_budget. AGENTS.md 25.0.1 lines 2922-2924, 2960-2966.

### L12-07 · The SearXNG engine pool had one working engine of six (2026-09-05)

brave (scraper) was rate-limited, duckduckgo/startpage CAPTCHA'd, google returned 0 results with no error (consent page), yahoo_finance did not exist; bing answered 'federal reserve policy' with an ammunition retailer; engines left inactive: true never registered and logged nothing. A hand chown left the config mode 600 and took SearXNG down.

*Rule:* §12 change the pool only through scripts/install_searxng_config.sh. AGENTS.md 25.0.1 lines 2927-2956.

### L12-08 · SearXNG braveapi made 2,357 uncounted paid-API calls (2026-10-10)

In SearXNG's general category braveapi made 2,357 calls 10-01..10-10 that lib/search_budget never counted, every one HTTP 422 (billing unknown), because it calls the provider directly. The operator approved disabling it ~18:40 ET.

*Rule:* §12 braveapi is the paid Brave API and bypasses lib/search_budget. AGENTS.md 25.0.1 lines 2939, 2957-2958.

### L12-09 · A readiness flag routed DeepSeek calls to local Gemma (2026-08-02)

available() returned True by default for any unrecognised lane, silently routing every DeepSeek call to local Gemma. Lanes are probed live.

*Rule:* §12 Never route on a readiness flag alone. Probe live.. AGENTS.md 25.0.1 lines 2817.

### L12-10 · Request caps sized from measured demand (2026-09-19)

risk/steph request caps were raised (60->220, 40->180) from 7-day peak demand (171 and 155 symbols/day) at $0.0015/call; the $1.00 cost cap stays the binding guard (binds near 660 calls). The operator accepted that a heavy day may reach the $2.00 ceiling rather than raise it.

*Rule:* §12 Every paid process has both per-process caps. AGENTS.md 25.0.1 lines 2717-2731.

### L12-11 · Arming off-peak deferral globally queues a fifth of paid calls (2026-09-20)

Measured before arming: 965 of 4,590 successful paid DeepSeek calls over 7 days (21%) would queue (maria 293, advisory_desk_opinion 262, cio_plan_enrichment 129, ...); cio_plan_enrichment and watchlist_cio_synthesis_cron feed operator surfaces, so their output lands at the next drain. The operator armed it for cron the same day.

*Rule:* §12 Arming ... is operator-only. AGENTS.md 25.0.1 lines 2898-2913.

### L13-01 · The most expensive pattern is rebuilding what exists and is merely unwired (2026-08-30)

load-by-subject was built, correct, tested and called by nothing; store_consistency.py the same; the librarian grading law shipped with no index file; two re-entry books, two identity-minting schemes, three place_order definitions, ~37 identity/memory/lineage modules with duplicates. Each cost the build and the later discovery.

*Rule:* §13.5 An unwired thing is not an absent thing. AGENTS.md 25.0.1 lines 3248-3257.

### L13-02 · Fifteen narrative surfaces, one carrying identity (2026-09-10)

Only subject_state_narratives carried identity; 515 defense theses, 109 rotation theses, 269 sizing rationales and 462,902 agent_recommendation_registry rows carried none. material_changes fired sector_move under a member symbol, so 13 of 14 sector events carried a SECURITY guid.

*Rule:* §13.4 Narrative subject identity. AGENTS.md 25.0.1 lines 3011-3021.

### L13-03 · Cookie-only Finviz screeners died and a heal masked it (2026-09-01)

Screener paths required FINVIZ_COOKIE only; when it expired runs returned zero rows, social_scalp's Finviz gate failed with them, and heal_trade_ai_session_cache.py re-dated the session cache with 0 tickers so the Trade AI page looked fresh and empty. Token auth (&auth=) was verified as a working backstop.

*Rule:* §13.6 Screener path ... retry with &auth=FINVIZ_API_TOKEN. AGENTS.md 25.0.1 lines 3297-3348.

### L13-04 · Audits kept re-opening settled entities as gaps (2026-09-24)

The 2026-09-24 agentic-memory audit (D1/D2) re-opened industries, themes, sectors and options as missing entities; the operator settled INDUSTRY/THEME as tags only and SECTOR as mintable-but-unproduced, so agents stop building producers for tags.

*Rule:* §13.4 Never build a producer for a tag. AGENTS.md 25.0.1 lines 3104-3111.

### L17A-01 · Three watchlist names rose 15-40% and nothing said so (2026-09-05)

Every research job was schedule-triggered, so a sweep could not notice one name behaving unlike itself. Material-change detection closed the loop; the first research row with trigger_source='material_change' was written 2026-09-06 (before that, zero).

*Rule:* §17A Material-change intelligence. AGENTS.md 25.0.1 lines 3574-3593.

### L17A-02 · The model narrated corrupt prices the detector had rejected (2026-09-06)

The first curation run picked JEPI and BND, both corrupt prices suppressed as UNCORROBORATED, and wrote 'JEPI showed a large price excursion'. The loop now inherits the detector's rejections.

*Rule:* §17A The loop inherits the detector's rejections. AGENTS.md 25.0.1 lines 3666-3669.

### L17A-03 · ACCEPTED is not DELIVERED (2026-09-06)

send_telegram returned True while the router suppressed the message into the 8pm digest; three changes were marked notified and the operator received nothing. A first fix read the most recent delivery row after sending and mis-attributed a stale SUPPRESSED row.

*Rule:* §17A ACCEPTED is not DELIVERED. AGENTS.md 25.0.1 lines 3656-3660.

### L17A-04 · A NaN fired as a real change (2026-09-06)

ticker_prices carries literal NaN; NaN < K is False, so the early-continue never triggered and the first run reported BHVN at magnitude NaN. Postgres NUMERIC NaN equals itself, so close_price = close_price does not filter it.

*Rule:* §17A A NaN fires. AGENTS.md 25.0.1 lines 3652-3655.

### L17A-05 · Curation bake-off and a dead default research lane (2026-09-06)

On one 30-item dossier, deepseek-flash (6.4s) and pro were 3-5x faster and more complete than chatgpt-oauth (19.1s) and grok-oauth (28.3s, 2 questions, 8 citations), so curation runs flash-first with chatgpt before grok. Research ranks on measured delivery (over 11,116 scored answers chatgpt 0.616, grok 0.470); the first routed question went to the old default claude and returned [CREDITS_REQUIRED] - stored correctly, answering nothing.

*Rule:* §17A Two lane policies point opposite ways. AGENTS.md 25.0.1 lines 3595-3633.

### L17A-06 · The DeepSeek cap check runs in the caller's process (2026-09-06)

The same governed call in the same second was refused without LLM_GLOBAL_DAILY_USD_CAP and OK with it: the check reads the caller's environment, not the bridge's. A cron line without it refuses every call with a message that reads like a budget problem.

*Rule:* §17A The DeepSeek cap is read in the caller's process. AGENTS.md 25.0.1 lines 3686-3691.

### L17A-07 · Identity coverage decays without the sweep (2026-09-06)

38 rows arrived untagged in the eleven minutes after the first backfill; nothing stamps subject_guid at write time, so a one-shot backfill is a snapshot, not a state.

*Rule:* §17A Coverage decays. AGENTS.md 25.0.1 lines 3637-3639.

### L17A-08 · An optional DB probe without a SAVEPOINT broke an unrelated query (2026-09-06)

A missing column on an optional source aborted the Postgres transaction and took down the price query twenty lines away; CREATE TABLE IF NOT EXISTS added no columns on installs that already worked.

*Rule:* §17A Wrap optional DB probes in a SAVEPOINT. AGENTS.md 25.0.1 lines 3692-3698.

### L17A-09 · Several trees, four checkout-relative splits (2026-08-31)

The pipeline wrote to the hub, the server read a release, cron jobs resolved against their cd tree and the old deploy script read a deploy worktree's HEAD; CURRENT rotated three times in fifteen minutes. That confusion produced four checkout-relative splits.

*Rule:* §17A The trees / Never quote CURRENT as an identifier. AGENTS.md 25.0.1 lines 3565-3566, 3711-3727.

### L18-01 · GitHub Actions quota exhaustion failed every job (2026-08-27)

Private repositories get a monthly Actions allowance that this CI exhausts in about a day; every job then fails with a quota signature (failure, 0 steps, empty runner). Standing operator policy since 2026-07-18: the repository stays public.

*Rule:* §18 Repository visibility is a CI invariant. AGENTS.md 25.0.1 lines 3781-3787.

### L18-02 · .env is rendered onto tmpfs; hand edits vanish (2026-08-31)

.env is a symlink to /run/user/1000/tradeai/env on tmpfs, regenerated from Bitwarden Secrets Manager by render_env.py; it does not survive a reboot and a hand edit is lost at the next render.

*Rule:* §18 .env is a tmpfs symlink. AGENTS.md 25.0.1 lines 3818-3822.

### L18-03 · Backups did not cover the durable stores (2026-08-31)

persistent-state appeared in zero crontab entries while holding 885 MB across 81 CIO JSONL stores (lineage, identity registry, learning history); the offsite job that once covered data/ was retired, and ~/backups sits on the same physical disk (/dev/nvme0n1p2).

*Rule:* §18 Never assume persistent-state can be restored. AGENTS.md 25.0.1 lines 3823-3828.

### L18-04 · Unlinked release directories served stale or empty data (2026-09-01)

reports/ was not linked into releases, so the scalp scanner read a stale run (run_label 1730 from the day before); logs/ started empty in each release and a 2026-08-27 deploy abandoned an 18-entry escalation queue. Durable directories are now linked into persistent state at deploy.

*Rule:* §18 The pipeline writes to the hub and persistent state; the server reads the release. AGENTS.md 25.0.1 lines 3789-3800.

## §23 n8n

### L23-01 · n8n was about to schedule lanes under no rule (2026-10-08)

AGENTS.md 1.6.1 contained zero occurrences of n8n (measured 2026-10-08) while a process was about to schedule 71 lanes; the lab bench already said it did not replace AGENTS.md, so a carve-out without a scope line would read as precedent for every process.

*Rule:* §23.1 Applies only to the n8n Community instance. AGENTS.md 25.0.1 lines 4032-4036,4056-4057.

### L23-02 · Most n8n activations had no matching grant (2026-10-09)

Due-diligence audit E C2/D5: of 13 activations since 2026-10-08, 9 were ungranted and 3 had a name-only grant; §17, §23.2 and the checker disagreed on the tier, and the only granted activation used a `service` grant. Audit C G5: 17 shadow activations had no grant and n8n history records only `import`.

*Rule:* §23.2 Install, activate, edit, deactivate or retire a workflow only under a cron grant. AGENTS.md 25.0.1 lines 4090-4092,4424-4425,4509-4512.

### L23-03 · The tranche-B cutover rollback restored the whole crontab (2026-10-08)

The tranche-B `_cutover.py` rollback was a wholesale crontab restore, which would have reverted every other lane's state along with the one that failed.

*Rule:* §23.2 Cutover comments the cron line, never deletes it. AGENTS.md 25.0.1 lines 4107-4108.

### L23-04 · A doubled schedule raised no finding (2026-10-08)

A lane left `kind: cron` with its line removed is reported ORPHANED by the lane monitor (measured 2026-10-08); the mirror image, a live line beside a new scheduler, had no finding at all. On 2026-10-10 a `kind: n8n` row with a live line also failed the inactive-row check, which is why shadow and canary stay cron rows.

*Rule:* §23.2 One scheduler per lane. AGENTS.md 25.0.1 lines 4112-4114.

### L23-05 · The n8n container could reach any provider directly (2026-10-09)

Audit C G3: from the container 1.1.1.1:443 and 172.19.0.1:22 were open, so a workflow or Agent could bypass §2A, the bridge and the $2.00/day cap. Decision 3 blocked egress with a DOCKER-USER rule; host 22/7777/7776/9090 then timed out.

*Rule:* §23.3 The container's internet egress is blocked, not proxied. AGENTS.md 25.0.1 lines 4148-4155.

### L23-06 · The bridge returned model tool_calls unvalidated (2026-10-09)

Audit B H4: the bridge passed client `tools` / `tool_choice` to the provider and returned `tool_calls` unvalidated, so n8n would execute whatever tool a model named. Audit C G12: no policy text addressed n8n Agent nodes; audit A: the allowlist never-list was prose enforced only at merge time.

*Rule:* §23.3 An Agent may not invoke unrestricted execution. AGENTS.md 25.0.1 lines 4133-4147.

### L23-07 · Self-labelled bridge callers hid 88% of a week's spend (2026-09-14)

88% of a week's spend sat under one shared id because callers could relabel themselves; audit B H2 found the bridge's `X-TradeAI-Agent` header self-asserted. Audit C G4: an Agent holding its own provider key would bypass the bridge, the cap, the registry, deferral and caller identity.

*Rule:* §23.4 A workflow or Agent requests AI only through the governed bridge. AGENTS.md 25.0.1 lines 4219-4227.

### L23-08 · Three days of HTTP 402 looked like a system doing no work (2026-09-17)

2026-09-17..19 a provider answered every call with HTTP 402 for three days, and every monitor read it as idleness; hence caps refuse typed and refused calls are deferred, not dropped.

*Rule:* §23.4 Every call is capped twice and refuses typed. AGENTS.md 25.0.1 lines 4246-4247.

### L23-09 · Only one n8n process validated model output (2026-10-09)

Audit B M3: only `n8n_model_job` validated output; the bridge returned whatever the provider produced. Output schema plus a behaviour-field scan at the bridge closed it.

*Rule:* §23.4 Outputs are advisory drafts. AGENTS.md 25.0.1 lines 4252-4253.

### L23-10 · One n8n API key would have been an unbounded credential (2026-10-09)

Audit C G7: the n8n public API was enabled, so one API key would have been a third, unbounded credential; audit C G18: the rotation daemon was unscheduled.

*Rule:* §23.5 n8n holds one credential, the relay bearer. AGENTS.md 25.0.1 lines 4266-4268.

### L23-11 · The relay credential was created while the n8n DB role was a superuser (2026-10-08)

The relay credential `tradeai-run-relay` was created 2026-10-08T16:45:48Z, after 2.0.0, while owner MFA was off and the `n8n` DB role was a superuser (`rolsuper = t`, still so on 2026-10-09, audit E C1/D7). MFA was waived on 2026-10-09; the role half stays open (P13).

*Rule:* §23.5 No new n8n credential while the n8n database role is a superuser. AGENTS.md 25.0.1 lines 4272-4274,4281-4288.

### L23-12 · n8n stores execution input, so a bearer in a workflow is a bearer in its database (2026-10-07)

ADR_COORDINATION_SECRETS.md: n8n stores execution input; the lab measured `EXECUTIONS_DATA_SAVE_ON_SUCCESS=all` on 2026-10-07. Retention was cut to no success data and 168 h of errors before any credential existed.

*Rule:* §23.5 The instance saves no successful executions. AGENTS.md 25.0.1 lines 4288-4290.

### L23-13 · n8n was adopted for throughput, not authority (2026-10-08)

The bakeoff measured incumbent 97 vs n8n 73; the operator moved scheduling to n8n for throughput, and the lab doc already said n8n is not the owner of Trade AI or NYC DOF jobs.

*Rule:* §23.6 Deleting the compose project must leave production unchanged. AGENTS.md 25.0.1 lines 4300-4302.

### L23-14 · The heartbeat watcher runs inside the thing it watches (2026-10-14)

WS1-15 and WS3-18: the heartbeat watcher runs inside n8n (WS9 C6); W0 on 2026-10-10 showed all six generic workflows can fail within four minutes, so P0/P1 must not depend on n8n.

*Rule:* §23.6 P0/P1 never depend on n8n. AGENTS.md 25.0.1 lines 5066-5068.

### L23-15 · The bridge's streaming path made a second, unreserved provider call (2026-10-09)

Audit B H1: the streaming path called the provider again after the governed call, outside the reservation; streaming is refused until the bridge streams the governed result.

*Rule:* §23.8 An Agent node runs only in a workflow with a registry row. AGENTS.md 25.0.1 lines 4433-4435.

### L23-16 · A direct Agent would skip most guardrails the run path keeps (2026-10-09)

Audit B: 44 of 59 code guardrails are enforced on the run path, while a direct Agent would leave 35 of 59 unenforced; audit C: 26 of 70 policy rules not enforced. n8n is the orchestration layer, never the source of governance truth.

*Rule:* §23.9 Before a lane or capability moves into n8n, list its guardrails. AGENTS.md 25.0.1 lines 4455-4458.

### L23-17 · A kind: n8n row with a live cron line fails its own registry gate (2026-10-10)

Agent A, 2026-10-10: a `kind: n8n` row whose cron line is live fails `CRON_PRESENT_WHILE_SCHEDULER_N8N` and the inactive-n8n-row check, so the 22-lane shadow wave was built as cron rows; design 02 §12.2 had written the workflow id as the row expression.

*Rule:* §23.11 Shadow and canary rows stay cron rows. AGENTS.md 25.0.1 lines 4531-4536.

### L23-18 · Overlapping registry PRs shipped corrupted cadences (2026-10-09)

Audit E C5: the registry lock broke twice and one conflict was resolved by hand in #1554; audit E C4: #1542 merged in 10 minutes with no review, carrying three cadences corrupted by shell-glob expansion.

*Rule:* §23.11 One registry PR at a time. AGENTS.md 25.0.1 lines 4566-4568.

### L23-19 · A lane was cut over on a skipped-lock fire (2026-10-09)

Audit E C8: `n8n-incident-fanin` was cut over when its only live fire was `RUN_SKIPPED_LOCK`, which proves no double run but not that the n8n-initiated run works.

*Rule:* §23.12 A lane that fails any fire leaves the wave. AGENTS.md 25.0.1 lines 4583-4585.

### L23-20 · The dispatch matcher let a secret renderer through and over-blocked ordinary words (2026-10-10)

Measured 2026-10-10: `lane_dispatch.dispatch_eligible` passed `scripts/render_env.py --write`; the substring matcher also refused any word containing stop, position, paper or guard. The matcher is now word-based (`EXTRA_FORBIDDEN_WORDS`) with `render_env`, `rotation_daemon`, `bitwarden` added.

*Rule:* §23.14 The test is code, not judgement. AGENTS.md 25.0.1 lines 4660-4666,4764-4772.

### L23-21 · Token-clean F09 lanes reach broker code (2026-10-27)

Measured 2026-10-27 at 274e531f5: `dispatch_eligible` returns eligible for 15 of 57 F09-family lanes; `advisory_lane_guard.scan_entry` finds broker modules, trade contexts and account reads in options_intent_matcher.py and options_iv_snapshot.py and a broker module in watchlist_proposal_bridge.py. None is allowlisted today.

*Rule:* §23.14 F09 broker, order, stop, protection and secret lanes stay host-side. AGENTS.md 25.0.1 lines 5208-5214.

### L23-22 · The cron-run scalp scan stalled unseen for 90 minutes (2026-10-09)

2026-10-09 13:30–15:00 the cron-run `trade-ai-scalp-live` scan stalled for 90 minutes (cold catalyst cache, every run killed at 295 s); the operator admitted this one lane to n8n live on the 4.0.0 terms.

*Rule:* §23.14 trade-ai-scalp-live runs live only on its exact cron argv. AGENTS.md 25.0.1 lines 4178-4180,4675-4676.

### L23-23 · Guard requests and grants expired unseen (2026-10-07)

On 2026-09-06 a pending guard request expired unseen and on 2026-10-07 two approved grants expired unused; the allowlist's blanket guard entry blocked the read that would have escalated them.

*Rule:* §23.14 The approval router's lane reads guard state only. AGENTS.md 25.0.1 lines 4687-4689.

### L23-24 · A log-file mtime proves only that cron opened a file (2026-10-10)

Refactor wave 1 (#1641) had to add `--dry-run`, honest exits and lane receipts to 36 cron rows (31 scripts) before any could be fired; the 2026-10-09 inventory classed 247 active rows as needing refactoring first.

*Rule:* §23.18 An ingest, llm or learn row enters only through r1_class_admission. AGENTS.md 25.0.1 lines 4706-4709,4729-4731.

### L23-25 · Six imported workflows failed within four minutes (2026-10-10)

W0, 2026-10-10 15:53–15:58 ET (RC8/RC9): the procedure lived in packets and PR bodies, the import dry run checked JSON shape only, and six workflows failed within four minutes; operator ~16:35 ET asked that new n8n work follow one procedure.

*Rule:* §23.19 The procedure is N8N_ONBOARDING_STANDARD.md, and it is mandatory. AGENTS.md 25.0.1 lines 4786-4789.

### L23-26 · Every n8n failure reached the SIEM as WARN (2026-10-10)

617 of 619 registry rows carried no `severity`, so every n8n RUN_* failure reached the SIEM as WARN; operator ~16:45 ET asked what each lane is supposed to do and what healthy and degraded mean.

*Rule:* §23.19 No lane enters shadow, canary or cutover without a workflow health contract. AGENTS.md 25.0.1 lines 4796-4798.

### L23-27 · Soft-deleted successful executions read as hangs (2026-10-10)

RC8/RC9: 403 `bad_lane_filter` and 404 `POST /event` were invisible to the import dry run, and successful executions soft-deleted under `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` kept `status = 'running'` and read as hangs.

*Rule:* §23.19 Before any n8n import, check_n8n_relay_contract.py passes. AGENTS.md 25.0.1 lines 4801-4803.

### L23-28 · A sending lane passed the forbidden-token gate (2026-10-14)

The token gate passed `momentum-scalp-advisory-alerts` (no forbidden word in its argv) although it sends Telegram advisories; only the prose sender rule kept it off. The operator admitted the advisory market-data class on 2026-10-14 ('just looking at level 2 on moomoo no trading').

*Rule:* §23.20 Only a lane in ADVISORY_MARKET_DATA_LANES qualifies. AGENTS.md 25.0.1 lines 4861-4863,4186-4188.

### L23-29 · Waits, not defects, held cutovers back (2026-10-14)

On 2026-10-14 the migration matrix held 6 lanes cut over, 61 canary-ready and 18 in shadow, six days after n8n scheduling opened; the operator ruled the multi-day waits the road block ('to many road blocks to testing').

*Rule:* §23.21 Cut over only when all four hold. AGENTS.md 25.0.1 lines 4886-4888,4920-4921.

### L23-30 · Forced live fires were refused for keyed lanes (2026-10-15)

The 2026-10-15 cutover packets and the 2026-10-21 `hermes-watchlist-scorer` packet found a forced live fire refused for keyed lanes (`run_key_namespace_refused`); the checklist then gained `OPERATOR_FORCED_LIVE` evidence.

*Rule:* §23.21 The live run is the next dispatcher slot, or an operator-forced fire. AGENTS.md 25.0.1 lines 4896-4899.

### L23-31 · Retired cron lines are kept as the fallback (2026-10-21)

12 lanes were retired by commenting on 2026-10-16 (2026-10-21: 16 RETIRED n8n-cutover lines, 13 rows at stage cutover); operator 2026-10-21: 'comment out whats working now this can be a fallback'.

*Rule:* §23.21 Use scripts/n8n_cutover_wave.py. AGENTS.md 25.0.1 lines 4910-4912.

### L23-32 · Most cutovers were the platform watching itself (2026-10-14)

6 lanes were cut over in 8 days, 4 of them the platform watching itself, for 68% of merge throughput; 35–45% of planned items were for jobs that will not exist (DECISIONS_FOR_OPERATOR.md decision 2).

*Rule:* §23.21 Consolidate before migrating. AGENTS.md 25.0.1 lines 5077-5079.

### L23-33 · The scheduler-only rule made the automation fabric impossible (2026-10-14)

The 2026-10-14 architecture review found 'a scheduler and a requester' among the rules that made the fabric impossible (WS1b-01); retries, dead letters, breakers, 75 chained steps and approval reminders lived in host Python (WS1b-03/08/09).

*Rule:* §23.23 n8n owns flow; the host owns authority, execution and evidence. AGENTS.md 25.0.1 lines 4066-4068,5021-5023.

### L23-34 · A broker read token was a trading token (2026-10-14)

WS9-04 and WS4-10: a read token was a trading token and '2FA' was a database write; WS4-01/WS4-08/WS9-02/WS9-05: one effectively-root uid, forgeable grants, an unauthenticated Command Center and a world-writable unlock file.

*Rule:* §23.23 No workflow that can reach a broker account read, write, arm or unlock is activated. AGENTS.md 25.0.1 lines 5035-5036,5084-5085.

### L23-35 · Policy refusals were logged as n8n errors and most workflows had no error workflow (2026-10-14)

WS1b-05: 10 of 16 workflows had no error workflow; WS1b-07: 977 dispatcher errors in a day were policy refusals; WS1b-06: successes were not saved.

*Rule:* §23.23 Every workflow has an error workflow; policy refusals are data. AGENTS.md 25.0.1 lines 5056-5058.

### L23-36 · No active n8n workflow met the framework (2026-10-14)

The 2026-10-14 gap assessment found 16 active workflows, none compliant in any area; re-measured 2026-10-15: 18 active, none compliant.

*Rule:* §23.24 Every workflow meets the framework. AGENTS.md 25.0.1 lines 5112-5114,5182-5184.

### L23-37 · Operator N8N Cutover Decision (2026-10-15)

The operator directed every lane family except F07 and registry_systemd to n8n and rejected maturity, reliability or monitoring concerns as a blocker; scope measured that day: about 267 rows (149 MIGRATE_N8N + 118 reclassified), 54 deferred.

*Rule:* §23.25 Every family in lane_cutover_policy.json is a cutover target. AGENTS.md 25.0.1 lines 5188-5214.

## §24–§29

### L24-01 · Sixty-six direct senders; the gateway stays the only sender (2026-10-10)

The operator ruled (~18:40 ET) that n8n orchestrates and the custom communications gateway stays the only sender; ~66 jobs each formatted, deduped and sent on their own. Senders now hand the gateway an intent.

*Rule:* §24.1 The host communications gateway is the only sender. AGENTS.md 25.0.1 lines 5232-5264.

### L24-02 · All generic n8n workflows can fail at once (2026-10-10)

W0 (15:53–15:58 ET) showed all six generic workflows can fail within four minutes, so the P1 path (incident notifier, SIEM bridge) stays on host cron. A routing rule held inside a workflow would escape registry checks and PR review (10.0.0, 2026-10-14).

*Rule:* §24.1 n8n decides what and when; the host decides delivery. AGENTS.md 25.0.1 lines 5239-5258.

### L24-03 · A Brave-first caller and an uncounted SearXNG engine (2026-10-10)

All 250 October Brave requests to 10-10 came from one caller that asked Brave first; SearXNG's `braveapi` engine made 2,357 calls 10-01..10-10 that `lib/search_budget` never counted, every one HTTP 422. Operator: "I have $20 maximum a month on Brave already, trying not to use it all".

*Rule:* §24.2 Free lane first; paid Brave only on measured insufficiency. AGENTS.md 25.0.1 lines 5268-5296.

### L24-04 · The search budget counted requests, never dollars (2026-10-10)

The dollar lines ($20 account, $18 ceiling, $15 scalp target, $12 non-priority stop, pools scalp 50/operator 20/catalyst 20/other 10) were set by the operator; at the old 1,500/month request breaker the pools stopped near $6.50, so the breaker was raised to 300/day, 3,600/month (registry `_amended`, operator "Yes, from one to six").

*Rule:* §24.2 Dollars bound Brave. AGENTS.md 25.0.1 lines 5282-5291.

### L24-05 · Unbudgeted Alpha Vantage calls (2026-10-10)

`scalp_float_lookup` made up to two unbudgeted Alpha Vantage calls every 5 minutes, and ~4,650 refused calls a week were counted as spend (#1668). One owner module now spends at most 23 of the free 25 daily requests.

*Rule:* §24.2 Alpha Vantage has one owner. AGENTS.md 25.0.1 lines 5297-5303.

### L24-06 · Forty-five lanes fetching providers themselves (2026-10-10)

Measured ~45 lanes fetching providers, ~36 of them consumers; only 3 read through `data_broker`. The finviz cache shrank 4,501 → 38 in torn writes and the directive servicer made 8,490 Finviz requests per run where 426 sufficed; the checker counted hub files only, missing ~27 lane scripts.

*Rule:* §24.3 One owner lane writes each broker-backed domain. AGENTS.md 25.0.1 lines 5307-5328.

### L24-07 · DOF stages connected as trade_ai (2026-10-10)

All 22 `dof_*` tables were owned by `trade_ai` and every DOF stage connected as `trade_ai`; the DOF pipeline (L152) had failed all six stages since 2026-08-29 on a password failure while exiting 0. Operator: "it's its own application".

*Rule:* §24.4 Trade AI resources never serve another application. AGENTS.md 25.0.1 lines 5332-5347.

### L24-08 · Cron jobs pushed to GitHub (2026-10-10)

L556 `coder_dispatch` in PR mode would push and run `gh pr create` from cron, and L541 `backup_generated_docs.sh` pushed from cron; the backup branch's latest commit held 0 files while exiting 0. Fix #1672 gated pushes behind flags and `TRADEAI_REMOTE_PUSH_AUTHORIZED=1`.

*Rule:* §24.5 A scheduled job never pushes. AGENTS.md 25.0.1 lines 5351-5362.

### L24-09 · Tests wrote production state (2026-10-10)

RC7: a sub-agent's `@needs_db` test run without `TRADE_AI_CI=1` wrote `hdi2test` rows to five live tables; `tests/test_research_heartbeat_20260914.py` wrote the production `search_budget.json`, including 33 future-dated keys.

*Rule:* §24.6 Every test sets TRADE_AI_CI=1. AGENTS.md 25.0.1 lines 5366-5374.

### L24-10 · .env symlinked into a worktree (2026-10-10)

A quick-wins agent symlinked `.env` into its worktree; several lanes load the whole `.env`, and the C1 stage runner sources it into every step.

*Rule:* §24.7 No agent reads, copies, links or prints .env. AGENTS.md 25.0.1 lines 5378-5384.

### L24-11 · Promotes under another campaign's grant (2026-09-25)

#1229 and #1230 were promoted under another campaign's grant, so release grants bind to a SHA, PR or campaign; on 2026-10-10 a generic 6 h grant was refused by SHA binding. On 2026-10-27 (review M2) the poller still asked for a per-SHA grant §25.10 said it did not need.

*Rule:* §24.8 The deploy poller needs no grant; the emergency path does. AGENTS.md 25.0.1 lines 5388-5399.

### L24-12 · A later move to Supabase and hosted n8n (2026-10-10)

Operator, verbatim: "One day I may move this to Supabase and the hosted version of N8N, so we want to consolidate as much as we can." Measured 18:37 ET: `trade_ai` 24.95 GB against a 16 GB budget, growing ~0.18 GB/day.

*Rule:* §24.9 No design may block a move to managed Postgres. AGENTS.md 25.0.1 lines 5403-5412.

### L24-13 · A broker-execution unit no agent could fix (2026-10-10)

The operator archived the motion unit's stale exact-SHA drop-in and restarted it by hand; the start was skipped on a missing `/etc` flag and the unit sat on a dev-tree root until a `95-code-root-current.conf` drop-in. Operator: "I need a way to grant exceptions for rule number two in situations like this where you can fix it."

*Rule:* §24.10 the execution-ops grant. AGENTS.md 25.0.1 lines 5421-5463.

### L24-14 · Agents had to stop and ask for fresh positions (2026-10-16)

The operator ran `sync_all_readonly.sh` by hand from CURRENT, and every agent that needed fresh positions had to stop and ask: "make that bash so agents can run, make amendment, not trading just reading".

*Rule:* §24.11 One entrypoint. AGENTS.md 25.0.1 lines 5515-5532.

### L24-15 · The SPCX incident (2026-10-14)

The SPCX incident produced the trading lock and the Schwab access-mode switch; every broker read and carve-out lane now refuses unless locks are LOCKED and Schwab is `read_only`, and safety findings are never auto-resolved.

*Rule:* §24.11 It refuses unless…; §27.1; §28.10. AGENTS.md 25.0.1 lines 5533-5541.

### L24-16 · Automatic deletion needs an amendment (2026-10-18)

Operator: "i approve automatic deletion would need an AGENTS.md amendment"; on 2026-10-22, with `/tmp` at 99% inodes: "It needs to be able to delete it. Just looking at it won't do anything." The exception is one reviewed code path with a fast kill switch.

*Rule:* §24.12 Two scripts, no hand deletion. AGENTS.md 25.0.1 lines 5614-5633.

### L24-17 · Stale clones may be the only copy (2026-10-18)

Root disk at 89%, ~100 GB in stale clones and worktrees and 36 GB in old releases; a clone with uncommitted or unpushed work may be the only copy of that work (§0 rule 5), so every check fails closed.

*Rule:* §24.12 Reclaimable. AGENTS.md 25.0.1 lines 5634-5649.


### L24-19 · Broker market data and paid feeds (2026-10-31)

After the 2026-10-30 selloff the engine lacked held-name option chains, an extended-hours cross-check, institutional flow, earnings dates and sector groups. Operator: "Modify the agents.md. Those are allowed. No problems at all. In FinViz, remember you get different data from the cookies than you do the APIs. I'm paying for it, we need to utilize both. So if you need a ratification on any type of data fees that we need, it's okay to use the broker accounts."

*Rule:* §24.11 Broker market data and paid data feeds. AGENTS.md 29.2.0 (ratified as 28.2.0; renumbered).
### L25-01 · #2208 merged by gh with zero reviews (2026-10-26)

PR #2208 was merged by `gh` under the `PR_MERGE_BOOTSTRAP_GH_MERGE` flag with zero reviews, rewriting §25.10 with no version bump (review H2).

*Rule:* §25.10 Agents queue; they never merge or promote. AGENTS.md 25.0.1 lines 5730-5733.

### L25-02 · One tap for the day's merges (2026-10-27)

The operator is not a GitHub expert and asked for one tap as the go-signal; the digest's "Approve all" binds each PR to the head SHA shown. Draft PRs (rule 11) never merge.

*Rule:* §25.10 "Approve all" in the digest is the operator's merge approval. AGENTS.md 25.0.1 lines 5734-5744.

### L25-03 · Five held paths (2026-10-27)

Review H1: `.mergify.yml` held five paths, so `AGENTS.md`, the guard and broker adapters outside them could merge on one tap. PR #2251 adds the remaining named paths.

*Rule:* §25.10 Held classes are never in "Approve all". AGENTS.md 25.0.1 lines 5745-5758.

### L25-04 · Merges stay out of market hours (2026-10-26)

24.0.0 put Mergify merges in America/New_York windows with a market-hours freeze (no merge Mon–Fri 09:30–16:15 ET).

*Rule:* §25.10 Mergify merges in ET windows. AGENTS.md 25.0.1 lines 5759-5762.

### L25-05 · Merged work waited on a per-SHA grant (2026-10-27)

Review M2: the poller refused every poll from 2026-10-27 13:34Z for want of a per-SHA grant, and the SOFT flag let a missing delegation look armed. The armed delegation, the poller ticket and exact-main CI are now the binding.

*Rule:* §25.10 The host promotes under the standing deploy delegation. AGENTS.md 25.0.1 lines 5763-5777.

### L25-06 · Emergency authority stays human (2026-10-27)

Review L5: the emergency promote stays operator-only; a coordinator may run it only on the operator's own in-session instruction, never a relayed one.

*Rule:* §25.10 The emergency promote and rollback are the operator's. AGENTS.md 25.0.1 lines 5778-5782.

### L26-01 · Eight CIO stores disagreed silently (2026-10-22)

The prospect was split over eight CIO stores holding 120 to 3,889 symbols, none GUID-keyed in Postgres; NVDA showed `ADD` at 78.5 beside thesis stance `watch`, and a kind-prefixed key kept a held security in a `WATCH:` record.

*Rule:* §26.1 One row per security_guid. AGENTS.md 25.0.1 lines 5797-5813.

### L26-02 · Facts with no registry domain (2026-10-22)

Stops, scans, catalysts, fused signals, CIO decisions and theses, options and paper proposals and alerts had no registry domain; 51 files wrote `paper_trade_proposals` and nothing reported it. Operator: "a data dictionary that shows one source of data".

*Rule:* §26.2 The dictionary is the §7A registry. AGENTS.md 25.0.1 lines 5817-5828.

### L26-03 · Watch ranked from an unregistered store (2026-10-22)

Watch ranked with an unregistered `top_ideas.v2` and read no CIO store; five page or API files and two projections read `holdings.json` directly.

*Rule:* §26.3 Every surface reads through its projection. AGENTS.md 25.0.1 lines 5832-5836.

### L26-04 · Use the CIO agent and n8n (2026-10-22)

Operator: "One data store with everything; use the CIO agent and n8n to accomplish this." n8n gathers; authority stays on the host (§23.14, §23.23).

*Rule:* §26.4 n8n schedules gathering lanes and decides nothing. AGENTS.md 25.0.1 lines 5840-5843.

### L26-05 · Disagreement no surface showed (2026-10-22)

The opportunity file, the thesis and the instrument record disagreed for NVDA and SPCX, and no surface showed it.

*Rule:* §26.5 A disagreement is a recorded, visible conflict. AGENTS.md 25.0.1 lines 5847-5851.

### L26-06 · The positions plan (2026-10-06)

The positions plan of 2026-10-06 set row-by-row migration; on 2026-10-22 the operator decided `holdings.json` becomes a generated export of `positions_current`.

*Rule:* §26.6 Adding or retiring a store or writer is operator-only. AGENTS.md 25.0.1 lines 5855-5859.

### L27-01 · n8n may read the broker (2026-10-22)

Operator: "N8N can read the broker because right now we're only doing reading of the broker. We're not doing any trading. So I want to amendment." Both market-data reads passed the §24.11 audit on `2d8fc9574`.

*Rule:* §27.1 Only READ_LANES. AGENTS.md 25.0.1 lines 5873-5896.

### L27-02 · One operator surface, one applier (2026-10-22)

The operator decided settings live in Postgres with history and one governed host applier (backup, audit, undo) applies crontab, live list, settings and grants; agents never call it.

*Rule:* §27.2 One audited host applier changes state. AGENTS.md 25.0.1 lines 5900-5908.

### L27-03 · Passkey for the risky direction (2026-10-22)

Operator: "yes on passkey"; this superseded decision D3 (resume at the host CLI or by Telegram button, TOTP declined) and the kill switch's terminal-only clear. Stopping is one click; re-enabling needs a passkey and a typed phrase.

*Rule:* §27.3 Safe direction one click; risky direction two factors. AGENTS.md 25.0.1 lines 5912-5933.

### L28-01 · Guessed caps killed good runs (2026-10-22)

`symbol_enrichment` had 224 failed / 1 success in 36 h under a 30 s orphan wait, and every market-hours orchestrator run on 10-21/22 was SIGTERMed at the 20-minute reaper cap; "enrichment takes 25–50 s" was the survivors of a 30 s kill. A zombie clear wrote `errors: []`.

*Rule:* §28.1 Only four automations end or rewrite a run. AGENTS.md 25.0.1 lines 5958-5976.

### L28-02 · /tmp filled up (2026-10-22)

`/tmp` (tmpfs, 1,048,576 inodes) was at 97% on 2026-10-19 and 99–100% on 2026-10-22, when an agent's package build and the tool harness failed with ENOSPC; on 2026-10-25 04:07–04:18 ET agent test runs filled it again.

*Rule:* §28.2 No new temp data under /tmp. AGENTS.md 25.0.1 lines 5980-5985.

### L28-03 · Two vendors built the same fix (2026-10-22)

Two agents of different vendors built the same reaper and enrichment fix in parallel; the claim board was approved with "approve all".

*Rule:* §28.3 Look, then claim, then build. AGENTS.md 25.0.1 lines 5989-5998.

### L28-04 · Lose nothing between agents (2026-10-23)

Operator: "put their complete changes and what are they planning to do into a file, and then annotate when it is actually done … just in case I need another agent to pick up anything that you left off" and "We shouldn't lose anything just because different developers or agents working on it."

*Rule:* §28.3 Every claim has a lifecycle and a worklog; the pre-commit gate. AGENTS.md 25.0.1 lines 5999-6033.

### L28-05 · Any agent picks work from the board (2026-10-23)

Operator: "I should be able to just say, hey, look to see if there's any open design work out there. Take what tasks you're going to do register it, do it, and execute, and it should know how to do".

*Rule:* §28.3a The procedure. AGENTS.md 25.0.1 lines 6037-6051.

### L28-06 · Designs need tracked ids and phases (2026-10-23)

Operator: "each agent that designs something needs to have phases attached to it and systematic phases, and we should have unique IDs that are actually tracked."

*Rule:* §28.3b Every plan is DSN-<YYYYMMDD>-<slug>. AGENTS.md 25.0.1 lines 6055-6071.

### L28-07 · Relayed approvals and dead commands (2026-10-22)

A relayed approval was correctly refused twice on PR #1933; two `! cd … && …` lines and two `<placeholder>` arguments run in a plain terminal did nothing.

*Rule:* §28.4 An approval counts only in the agent's own session. AGENTS.md 25.0.1 lines 6075-6083.

### L28-08 · A time to live for passkey approvals (2026-10-22)

Operator: "we need a time to live for this. Maybe 1 hour or 2 hours. So it caches." and "approve sudo window".

*Rule:* §28.5 One passkey assertion may open a window. AGENTS.md 25.0.1 lines 6087-6093.

### L28-09 · A read-only Schwab baseline (2026-10-22)

Operator: "we still want to go from a baseline of only read-in child swap from now not placing orders"; `kill_switches.py --status` showed only `global` engaged since the SPCX incident.

*Rule:* §28.6 Schwab read_only, locks LOCKED, kill switches the operator's. AGENTS.md 25.0.1 lines 6097-6108.

### L28-10 · Agent crawls killed the live server (2026-10-23)

Five portfolio-server SIGKILLs between 09:14 and 10:24 ET were driven by agent crawls and previews against the live server (PR #2012, `docs/ops/SERVER_MEMORY_SPIKES_2026-10-23.md`).

*Rule:* §28.8 No agent traffic to the live server in market hours. AGENTS.md 25.0.1 lines 6120-6138.

### L28-11 · Operator surfaces removed without approval (2026-10-22)

Commits 20853e201 (2026-10-22), 8c14784ae (2026-09-15) and fdb99d7a8 (2026-09-29) removed operator surfaces; TradeInView hid Calendar P/L and Replay. Operator: "changed without any change control".

*Rule:* §28.9 No silent removal; §28.13. AGENTS.md 25.0.1 lines 6147-6151.

### L28-12 · A batched wrapper change stopped ~30 cron jobs (2026-10-23)

d5f51dbef rode in PR #1979 / batch 8 and stopped ~30 cron jobs (stop supervisor, incident notifier, repricer …) for ~2 days from 12:06 ET; no surface showed the outage because the error line kept every log fresh.

*Rule:* §28.9 Shared infrastructure ships alone; health is the last successful run. AGENTS.md 25.0.1 lines 6152-6168.

### L28-13 · Three portfolio totals (2026-10-24)

Site audit (`handoffs/site-audit-20261024/FINDINGS.md`): SPCX ADD on Watch vs TRIM on CIO Desk; three portfolio totals; position counts 32/12/25/9/14/20. Operator: "coming from the CIO … it should be the same".

*Rule:* §28.9 One source per fact, owned by the CIO record. AGENTS.md 25.0.1 lines 6159-6164.

### L28-14 · Reads that acted (2026-10-24)

An inventory burst OOM-killed the server at 15:50; GET `/holdings/live-stops` refreshed a live Schwab stop read; Active Trader polled 6 MB every 30 s.

*Rule:* §28.9 A read never acts. AGENTS.md 25.0.1 lines 6169-6172.

### L28-15 · Pages showing stale writers as live (2026-10-24)

`risk_management.json` was written once a day while the Risk page presented it as live; retired writers sat behind blank panels (advisory opinions, regime, dividends, attribution).

*Rule:* §28.9 Every writer is a monitored n8n lane. AGENTS.md 25.0.1 lines 6173-6176.

### L28-16 · Noisy conflict flags that never cleared (2026-10-24)

15 Watch flags of which 9 were noise and none could clear; WATCH vs AVOID on names not held and 52–79-day-old reviews shown as conflicts; FATN/ANET/SMCI gates flagged; the "Resolve conflict" button queued reviews that cleared nothing.

*Rule:* §28.10 One engine; the owner decides. AGENTS.md 25.0.1 lines 6185-6203.

### L28-17 · Do not cut off work in flight (2026-10-24)

Operator, ratifying 20.2.0: "We don't want it to cut off anything that's already in action." Each transition exception names its replacement and sunsets on 2026-12-31.

*Rule:* §28.11 Until replaced, at most to 2026-12-31. AGENTS.md 25.0.1 lines 6208-6233.

### L28-18 · Deployed and tested, failures emailed and texted (2026-10-25)

Operator: "multiple agents can read the agents.md, see how to design and deliver their stuff and queue … Any failures I need to be emailed, notified, and texted." On 2026-09-22 the desk ran three days on a stale release and a locally green PR failed CI.

*Rule:* §28.12 The path; verify and page. AGENTS.md 25.0.1 lines 6237-6287.

### L28-19 · Approvals that lived only in prose (2026-10-24)

The 10-24 approvals of the 22 desk boards, TradeInView and the Watch row existed only in handoff prose; Approvals showed 0 decisions, and Board 19's approved "Decided recently" panel was never built.

*Rule:* §28.13 Page designs live in design/pages. AGENTS.md 25.0.1 lines 6296-6317.

### L28-20 · Fixed phone chrome; a public repo (2026-10-25)

The phone metric strip and Ask bar stayed fixed and pages scrolled under them; no agent opened Rulebook or Approvals, so "Rulebook unavailable" went unseen. The repository is public, so real financial data never enters it.

*Rule:* §28.13 Phone first; no real data in the public repo. AGENTS.md 25.0.1 lines 6318-6341.

### L28-21 · Small errors waited on a person (2026-10-25)

Operator: "Arm the fixer and also a logger that tracks what was fixed … Somebody needs to monitor it, if there's little errors they need to correct it as long as they're adhering to our agents.md."

*Rule:* §28.14 Monitor and fixer. AGENTS.md 25.0.1 lines 6353-6378.

### L28-22 · The push budget blocked approved PRs (2026-10-25)

The per-branch budget of 2 blocked four operator-approved PRs, each waiting for an operator override; 21.0.0 ratified a budget of 5 and a coordinator override (PR #2115).

*Rule:* §28.15 item 1 Push budget. AGENTS.md 25.0.1 lines 6398-6413.

### L28-23 · Shared-infrastructure PRs waited per PR (2026-10-25)

Every shared-infrastructure PR waited for a per-PR operator release; merged lanes stayed dry until a hand edit; setup packets stopped on TTY ACKs; enabling SMS waited on a hand `.env` edit.

*Rule:* §28.15 item 2 Shared infrastructure merges alone after the digest. AGENTS.md 25.0.1 lines 6394-6396.

### L28-24 · Weak review let guard changes ship (2026-10-27)

Review M1/M3: two agent reviews and a veto window let guard and CI changes ship with no operator act; 116 of 167 health contracts were `REVIEWED` by a team label.

*Rule:* §28.15 items 3 and 10. AGENTS.md 25.0.1 lines 6436-6447.

### L28-25 · Lanes stayed dry; setup waited on hand edits (2026-10-25)

Merged and released lanes stayed dry until the host relay live list was edited by hand; setup packets stopped on interactive TTY ACKs; operator: "this should have just been a toggle on the control ops."

*Rule:* §28.15 items 4–6. AGENTS.md 25.0.1 lines 6449-6477.

### L28-26 · Telegram grant requests for routine work (2026-10-25)

At 16:14 ET Cursor, following 20.2.0, asked the operator on Telegram for a `git-push` grant to push routine branches and a `deps` grant to run `npm run build` and Playwright.

*Rule:* §28.15 item 8. AGENTS.md 25.0.1 lines 6481-6497.

### L28-27 · Fully automatic unless there is an issue (2026-10-25)

Operator: "I need you to take care of all six of those items now. They should be fully done, fully automatic, no input by me, … unless there's an issue."

*Rule:* §28.15 item 9. AGENTS.md 25.0.1 lines 6498-6512.

### L28-28 · Errors dropped with no record (2026-10-27)

Operator, relayed by the coordinator session: "agents … if they have an error, they can't just drop and leave it. They need to fix it and report it somewhere in a log that the coordinator can come back to". Shipped as #2238.

*Rule:* §28.16 Incidents. AGENTS.md 25.0.1 lines 6523-6543.

### L28-29 · A design that never became a task (2026-10-28)

The W8 conflict-engine workstream spec'd its `conflict-resolver` lane as a paragraph in `docs/ops/W8_WRITERS_20261024.md` — "the separate W8 Conflict Engine PR will declare `conflict-resolver`…" — but gave it no `-P<n>-T<m>` task id. Four days later the lane still had no registry row, allowlist entry, health contract or PR, and every Watch card rendered "conflict ledger not yet produced". A design expressed only as prose is invisible to `agent_claim.py status` / `next` and the Work board, so no other agent could see or take it. The same audit found six `PROPOSED` designs and four spec'd-but-unadmitted lanes sitting unwired.

*Rule:* §28.3b — "designed" means each buildable unit is a task id on the board. AGENTS.md 26.0.0 §28.3b.

### L28-30 · A redundant push grant blocked an approved push (2026-10-28)

The operator approved the work in-session, but the agent's `git push` was refused by the guard hook for a missing `git-push` grant — a second, per-push human re-confirm the operator said should not exist: "The GET push grant. Not needed. It should be automatically pushed by the agent as long as the operator approved the work to be done." 21.0.0 §28.15 item 8 had already ratified grant-free pushes under an approved scope, but §0 rule 4 (matched to the hook in 26.0.0) still said a guard hook "may also require a git-push grant", and the hook enforced it. 26.1.0 removes the grant requirement; the per-branch budget and the never-`main`/`release/*` ban remain the actual rails.

*Rule:* §0 rule 4; §28.15 item 8. AGENTS.md 26.0.0 §0 rule 4.

### L25-07 · An emergency needs merge and deploy without Mergify (2026-10-28)

The operator asked for an emergency path that bypasses Mergify: "in an emergency … merge and push live … commenced through Telegram … use a digest if necessary … bypass Mergify." Waiting on a Mergify window or the market-hours freeze is wrong for a genuine emergency fix, and the operator must be able to act from the phone, not only the host terminal. 26.1.0 adds an operator-initiated emergency merge / merge-and-deploy, SHA-bound, executed under STOP, the locks and a rollback target. The one line it cannot cross: "push live" never bypasses the broker rails (kill switch, trading locks, Schwab `read_only`, order/stop paths) — those stay §17 on Ops → Controls or the host terminal.

*Rule:* §25.10 "Emergency merge and deploy"; §17. AGENTS.md 26.0.0 §25.10.

### L25-08 · The operator's word in-session is a merge approval, not only the Telegram tap (2026-10-31)

Eight green PRs from the 2026-10-30 selloff RCA sat unmerged while the operator, in the coordinator's own session, had already approved everything; the only recognised merge approval was a Telegram digest tap, and the operator had not seen the digest. The operator directed, verbatim: "No merge digest went to Telegram and you are allowed to merge on my word and via the command center. Make sure that's in the agents.md. You're not able to merge on your own, but with operator approval you are able to merge." 28.0.0 adds §25.10.3: the agent records that in-session (or Command Center) approval as the same `PrMergeDigestApproval@v1` row the tap would have written, head-SHA bound, and applies `operator-merge` through the same host helper; Mergify still merges under the same checks and windows. What does not change: an agent never merges on its own, never runs `gh pr merge`, never covers a held-class PR with "everything", and §0 rules 1–2 / §24.7 are never overridable.

*Rule:* §25.10.3; §28.4; §17. AGENTS.md 28.0.0.

### L29-01 · Runs that hit a cap mid-way (2026-10-27)

A paid lane died for three days and nothing said so (§12); runs that hit a cap mid-way leave partial state.

*Rule:* §29 Preflight every limit. AGENTS.md 25.0.1 lines 6551-6556.

### L29-02 · Bad data reached the model (2026-10-26)

Prospectus defects — units, filing labels and price series — reached the model unchecked.

*Rule:* §29 A data-quality gate runs before any model call. AGENTS.md 25.0.1 lines 6557-6559.

### L29-03 · Passing mentions read as subject news (2026-10-27)

Passing mentions and ticker collisions have repeatedly been read as subject news (identity spine).

*Rule:* §29 News drives a rewrite only after checks. AGENTS.md 25.0.1 lines 6560-6564.


### L24-18 · Nothing closed what agents opened (2026-10-30)
The disk reached 99.75%. 646 git worktrees existed (332 abandoned, 59.6 GiB); `~/.cache/agent-tmp` held 43 GB;
release prepares copied `.env.*` backups into every release; older DB dumps were "archived" on the same disk, freeing
nothing. The reviewed hygiene rules were plan-only, failed every `--standing` plan on a non-claim file, and held any
folder with a nested repo or a fixture timestamp. The config `.env` was truncated to 0 bytes during the full-disk
window. Rule: agents close what they open (archive, then remove); a recurring, pressure-triggered sweep closes the
rest; backups keep one on host and N+1 verified on Drive; growth is audited twice a week (AGENTS.md §24.14–§24.15).

## Coordinator, 2026-10-27 (rules added during the consolidation)

### LC-01 · Approvals the operator could not read (2026-10-27)

The operator approves merges from a Telegram digest that shows only PR titles, and from GitHub; PR titles and bodies were written for engineers. He asked, verbatim: "make sure those approvals of PR are in plain English, the who, what, when, and why of what's changing or what's being implemented, and fallbacks, if anything ... not just tonight's, everything going forward. That should be the mandate in the agents md."

*Rule:* §28.12 — every PR explains itself in plain English.

### LC-02 · A public repository map of personal data (2026-10-27)

The 2026-10-27 audit found personal and financial data in tracked files. Listing those files by name in a public register would publish a map to them, so OPEN_ITEMS names the class of data and the remedy and the file list stays in the operator's private handoff.

*Rule:* §2A — treat every commit as public.

### L25-09 · A promote left long-running units on the old release (2026-10-31)
**What happened.** Units whose WorkingDirectory is `CURRENT` resolve the symlink once, at start. The deploy restarted
a fixed list, so tradeai-ops-applier ran 10-22 code until the operator restarted it by hand on 10-31 (it refused every
newer Ops Controls kind as `KIND_UNKNOWN`) and went stale again at the next promote; grok-/chatgpt-oauth-proxy and
heartbeat-receiver ran 10-11/10-13 code. Operator, verbatim: "Why does that keep happening and why do I need to keep
resetting it? We need to build in a system that the system can automatically do that if needed with my approval and
make an amendment." **Rule.** §25.10 (28.1.0): a fail-closed restart list (named units only, WorkingDirectory-bound,
installed, §23.14 tokens over name/argv/env, approval and guard daemons excluded or session-gated, cap), each cwd read
back and receipted, a P1 on failure, and the deploy continues.

### L11-01 · Every push ran two full suites and the CI queue saturated (2026-10-31)
**What happened.** 5,369 GitHub Actions runs started on 2026-10-31. Mergify's blanket "keep PRs up to date" rule pushed
catch-up commits to every open PR after each merge (2,913 runs, 54%); agents opened ready PRs and pushed several times
each (1,775, 33%); CodeQL default setup scanned every PR push (392, 7%). One PR push cost 9-10 workflows, about 36 jobs
and about 110 runner-minutes; two near-identical 12-job sharded suites were about 97 of those minutes, and 269 of 444
full-suite PR runs were cancelled by a newer push. Main's 12-second gating job then waited 48-104 minutes for a runner,
merges stalled, and the operator cancelled runs by hand. **Rule.** §11 (29.3.0): open every PR as a draft and mark it
ready only when the work is done and adversarial review has passed; only a stack's top is marked ready; approved PRs
merge in one weekday window (17:30-18:30 ET). Design and measurements: `DSN-20261031-ci-load-reduction`.
