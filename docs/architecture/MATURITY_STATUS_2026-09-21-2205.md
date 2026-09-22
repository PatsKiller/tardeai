# Where we are: 4.75 / 10 — and what moves it to 8.5

**2026-09-21, 22:05 ET.** Every number queried in the last ten minutes.

---

## 1. The level right now: **4.75 / 10. Unchanged since 19:05.**

Nothing has reached production tonight. Three root causes were found and fixed
**in branches**; the score moves when they deploy, not when I commit them.

| # | dimension | score | measured tonight |
|---|---|---:|---|
| 1 | Capital-protection correctness | **7** | trailing-stop fix live; starred gate fed (12 symbols) |
| 2 | Alert delivery | **5** | 62 of 8,003 carry a message id (0.77%); **79 of 53,248 SETTLED** |
| 3 | Alert signal | **2** | storm **1,686 today** and still climbing |
| 4 | Identity / GUIDs | **5** | outbound 8,702/52,996 (16.4%); **inbound 1 of 252** |
| 5 | Memory / joinability | **3** | `causation_id` **0 of 53,248** |
| 6 | Self-observability | **3** | **no SLO exists anywhere** |
| 7 | Test / gate honesty | **5** | alarm coverage 36/188 (19.1%); CI runs 971 of 1,446 |
| 8 | Deploy discipline | **8** | prepare/promote strict; served 1 merge behind |

**38 / 80 = 4.75.** Target 69/80 = 8.6. Gap: **+31 points.**

---

## 2. What actually happened tonight

**The single finding that matters.** `claude_escalation_handler.py:295` imported
`datetime` a second time *inside* `_verify_remediation`. Python binds a name
assigned anywhere in a function as local for the whole function, so every earlier
reference raised `UnboundLocalError` — including one in an `except` handler,
which propagated out and killed the process.

- **122 of 124 runs crashed today (98%)**
- Added **2026-08-08** in a commit titled *"Health Agent … remediation"* — a
  remediation commit disabled the remediation verifier
- Stayed **latent** until 09-14, when the `rc=127` fix made retries succeed and
  finally reached the broken code
- The retries were fine (**2,370 succeeded** since 09-15). It was the
  *verification of those retries* that could not run, so nothing ever cleared

Proven RED on pristine, GREEN patched, in separate processes.

**11 of the 13 storm components are firing on a false premise.** All seven
`missing_*` tables exist with rows and fresh timestamps. A live collector run
returns exactly **one** real finding: `stale_setup_advisory` (4.9d vs 3d).

---

## 3. The stages to 8.5

| phase | moves | from → to | state |
|---|---|---|---|
| **0** Collect what's paid for | — | — | #1176 **merged**; timers **installed and firing** |
| **1** Kill the storm | signal | 2 → 7 | **#1177 open**, root cause fixed, CI amber |
| **2** Provable delivery | delivery | 5 → 9 | **#1179 open**, additive, CI amber |
| **3** Identity at the chokepoint | identity | 5 → 9 | not started |
| **4** Close the memory join | memory | 3 → 8 | not started |
| **5** SLOs + self-observability | observability | 3 → 8 | not started |
| **6** Gate honesty | gates | 5 → 8 | continuous |

Plus capital-protection 7→9 and deploy 8→9. **Sum at target: 69/80 = 8.6.**

Every phase is gated on a **production query**, never on a merge. Phase 1's gate:
escalation notifications/day **< 20**, against a frozen baseline of **1,673**,
measured with the identical command before and after:

```bash
grep -c '^<DATE>.*exhausted after' logs/claude_escalation.log
```

---

## 4. What is genuinely done

- **#1176 merged** — disk guard, agent-worktree retention, alarm firing test,
  and the deploy fix that stopped cloning 12 GB of agent data into every release
- **Both §17 timers installed**, `Linger=yes`, and the disk guard has **already
  fired**: receipt written 22:03:38, `used_pct 88.24`, `telegram: accepted`
- **Two new CI gates registered**: `import_shadowing`, `alert_delivery_id`
- **Alarm firing coverage 35 → 36 of 188** — the ratchet moved up, not sideways
- Both documents synced to Drive, verified by listing the parent folder

---

## 5. Where I was wrong tonight — the pattern, not the tally

**Six checks reported success while exercising nothing:**

1. A dry run that "proved" the fix — it skipped the crashing path entirely
   (`--dry-run` short-circuits before the call site); pristine main produced the
   identical result
2. A test that passed against the **unpatched** file, because the component
   string lacked the `health:` prefix the parser requires
3. The same test passing alone and failing batched — a sibling test seeded
   `sys.modules`, so the assertion targeted whichever copy loaded first
4. A negative control that `skip`ped every meaningful assertion because `ROOT`
   resolved to a scratch directory
5. A gate wrapper rewritten **four times**, each version wrong in a new way,
   before I abandoned it for the one-line `grep` that had worked all evening
6. Nearly reporting **"166 latent bugs"** from a repo-wide scan; triage showed
   162 benign, 4 candidates, **1 real**

And a seventh, authored tonight and caught by its own timer: the disk guard
returned exit 1 for "still over threshold", so systemd marked a **successful**
run as `failed` — making a real crash indistinguishable from normal operation.
The same three-way collapse as `_age_days_table`. Fixed.

> **A check that passes on the wrong dimension is worse than no check.**

Every one of these was caught by *running* the thing rather than reading it.

---

## 6. Open, and needing you

| item | status |
|---|---|
| `market_quotes` retention | **leave at 90 days.** The 7-day cut I first recommended was wrong — `rotation_ladders` reads 21/63/126-day lookbacks. Correct fix is downsampling (117.4 intraday rows per daily close): reclaims ~5.67 GB *and* extends history |
| `stale_setup_advisory` | the one genuinely real finding — 4.9 days against a 3-day threshold |
| `hermes_health_inspector` | queues items with `fixable=False` and no `retry_cmd`, so they can never be retried yet still page forever. Separate defect |
| Deploy | served is one merge behind; nothing takes effect until the dev tree advances (327 cron lines run from it) |
