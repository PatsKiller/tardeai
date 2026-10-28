# Guard hook fixes — OI-132 and OI-133 (PROPOSAL packet)

```
Status:      PROPOSED — do not apply yet; held for operator merge (AGENTS.md §28.15 item 3)
as_of:       2026-10-28
Measured at: /home/johnclaw/tradeai-wt-resync-20261028 branch wt/resync-20261028, .cursor/hooks/guard-lib.sh (169 lines)
Owner:       platform
See also:    docs/governance/OPEN_ITEMS.md OI-132, OI-133
             AGENTS.md 26.1.0 §0 rule 4, §28.15 item 8, §28.15 item 3
             .cursor/hooks/guard-shell.sh  (the consumer of classify_cmd)
             .cursor/hooks/guard-write.sh  (classify_path only — not touched)
             scripts/lib/guard_push_auth.py, .githooks/pre-push  (the pre-push layer OI-133 leans on)
```

## What this packet is

This is a **proposal**, not an edit. The two files in this directory are:

- `guard-lib.sh.patch` — a unified diff against `.cursor/hooks/guard-lib.sh` (a held `guard-config` path).
- This `README.md` — the defect analysis, the proposed fix per defect, and the safety analysis.

Neither file has been `git add`ed, committed or pushed. The actual change to
`.cursor/hooks/guard-lib.sh` (and the companion edit to `.cursor/hooks/guard-shell.sh` in §"Companion
edit") is a **held** change: it needs two independent `Adversarial-review: MERGE` receipts **and** the
operator's own merge (§28.15 item 3 — "guard, hook, CI-enforcement, merge and deploy tooling").

---

## Defect OI-132 — `approvals` false-positive and an ungrantable tier

### The two defects

1. **The classifier scans quoted argument prose, not the actual command.**
   `classify_cmd()` line 44 is:

   ```bash
   [[ "$cmd" =~ (^|[[:space:];&|/])guard[[:space:]]+(grant|plan)([[:space:]]|$) ]] && { echo approvals; return; }
   ```

   The boundary class `(^|[[:space:];&|/])` matches a plain space, so the words
   `guard grant` / `guard plan` match **anywhere**, including inside a quoted argument of an
   unrelated command. The reported trigger:

   ```text
   agent_claim.py note --next "... git-push guard grant ..."
   ```

   classifies the whole command as `approvals`, even though no guard is being invoked.

2. **`approvals` is an internal hard-deny sentinel surfaced as a grantable tier.**
   `guard-shell.sh` treats every tier except `secret`/`gate`/`none` as a grant-gated scope, and its
   deny message prints `tier_scope "$tier"` plus `bin/guard grant $tier`. But `tier_scope()` has no
   `approvals` case — line 33 is the fallthrough `*) echo "Unknown tier: $1" ;;` — and
   `bin/guard`'s `ALL_TIERS` list excludes `approvals`, so `bin/guard grant approvals` is refused as
   "not grantable". Result: **a block no grant can satisfy** — "Unknown tier: approvals", with an
   allow-path that does not exist.

Line 45 emits `approvals` too, but only for shell writes/redirects that touch `.cursor/approvals`
(`>`, `tee`, `sed -i`, `mv`, `cp`, `rm`, `truncate`, `install`, `dd`), i.e. ledger tampering. That is
a real hard-deny and is **unchanged**.

### Proposed fix (OI-132)

Make the self-grant guard **quote-aware** and make `approvals` a proper hard-deny:

1. **Strip quoted spans before matching**, so quoted prose cannot classify the command (double quotes
   via `\"[^\"]*\"`, single quotes via a `_sq` variable so the literal `'` survives the glob).

2. **Re-scan the raw command when a code-executing builtin is present** — `bash`/`sh`/`zsh`/`dash`/
   `ksh`/`python`/`python3` `-c`, `node`/`perl` `-e`, or `eval`/`exec`. In those the quoted string
   **is** code, so stripping it would open a self-grant hole; the raw re-scan closes it.

3. **Add an `approvals` case to `tier_scope()`** so it never reads "Unknown tier: approvals".

Net effect (verified against the patched file):

| command | old tier | new tier |
|---|---|---|
| `bin/guard grant git-push` | approvals | approvals (blocked) |
| `guard grant git-push` | approvals | approvals (blocked) |
| `true && guard grant git-push` | approvals | approvals (blocked) |
| `bash -c "guard grant git-push"` | approvals | approvals (blocked) |
| `eval "guard grant git-push"` | approvals | approvals (blocked) |
| `python3 -c "guard grant git-push"` | approvals | approvals (blocked) |
| `agent_claim.py note --next "... guard grant ..."` | **approvals (false positive)** | **none** |
| `agent_claim.py note --next '... guard plan ...'` | **approvals (false positive)** | **none** |

No real self-grant vector is lost; only the quoted-prose false positive is removed.

### Companion edit (held, same path — `guard-shell.sh`)

The patch fixes `tier_scope`, but to stop `approvals` surfacing as a "grant this tier" prompt, the
consumer must hard-deny it. In `.cursor/hooks/guard-shell.sh`, the verdict `case` currently handles
only `secret`, `gate`, `none` (everything else falls through to the grant path). Add:

```bash
case "$tier" in
  secret) emit deny "…" "…" ;;
  gate)   emit deny "…" "…" ;;
  none)   allow ;;
+ approvals) emit deny "BLOCKED — self-grant or ledger tamper. An agent may never run 'guard grant'/'guard plan' or write .cursor/approvals. Operator only." \
+                       "You may not grant yourself authority or modify the approvals ledger. Ask the operator to run bin/guard grant at their terminal." ;;
esac
```

This makes `approvals` a hard deny like `secret`/`gate`, so it can never be satisfied by any grant.

---

## Defect OI-133 — redundant `git-push` grant for approved-scope pushes

### The defect

`classify_cmd()` line 57 bundles plain `git push` with history rewrite and refuses all of them:

```bash
[[ "$cmd" =~ git[[:space:]]+(push|reset[[:space:]]+--hard|rebase|filter-branch) ]] && { echo git-push; return; }
```

AGENTS.md 26.1.0 §0 rule 4 (lines 69–77) and §28.15 item 8 (lines 2452–2458) now make an
operator-approved scope the push authorization:

> An operator-approved plan or scope is that intent for fast-forward pushes of the agent's own
> non-`main` branches, within the per-branch budget the pre-push hook enforces … A guard hook must
> not require a separate `git-push` grant for an approved-scope fast-forward push of the agent's own
> non-`main` branch (it logs the push); the per-branch budget and the never-`main`/`release/*` ban
> still bind. Never push `main` or `release/*`, force-push, rewrite pushed history or delete a
> remote branch.

The shell guard still demands a `git-push` grant on every `git push`, so an approved-scope push is
blocked twice (once by the shell guard, once by the pre-push hook).

### Proposed fix (OI-133)

Split the one line into: (a) history rewrite stays `git-push`; (b) `git push` that is force-push,
a branch deletion, or names `main`/`master`/`release/*` stays `git-push` (hard-gated); (c) the
remaining plain non-`main` fast-forward `git push` passes through only when the push wrapper attests
an approved scope, and otherwise stays `git-push` (current behaviour).

Verified:

| command | no approved scope | `TRADEAI_APPROVED_SCOPE_REF` set |
|---|---|---|
| `git push origin mybranch` | git-push | **none** (log-only) |
| `git push origin main` | git-push | git-push |
| `git push origin release/1.0` | git-push | git-push |
| `git push --force origin mybranch` | git-push | git-push |
| `git push origin --delete mybranch` | git-push | git-push |
| `git push origin +mybranch` | git-push | git-push |
| `git reset --hard HEAD~1` / `git rebase` / `git filter-branch` | git-push | git-push |

### Not yet wired — be explicit

The hook cannot reliably see the claim-board (the shell guard runs in a sandboxed environment without
a dependable path to `scripts/lib/agent_claim_board.py` or `data/coordination/handoffs/`). So the
patch uses the **smallest safe signal**: an environment variable `TRADEAI_APPROVED_SCOPE_REF` that the
push wrapper is expected to set to the `Operator-approval:` reference.

**This is not wired end-to-end.** To make it real, three pieces still need their own reviewed work
(out of scope for this packet):

1. The push wrapper (e.g. `bin/agent-push`, or the coordinator's push path) must set
   `TRADEAI_APPROVED_SCOPE_REF=<Operator-approval: reference>` for a push that carries an approved
   scope, and must **not** set it otherwise (a forgeable env var is the same forgeable-approval
   problem OI-005 names — an approval relayed between agents never counts, §28.4).
2. The pre-push hook (`.githooks/pre-push` / `scripts/lib/guard_push_auth.py`) must treat the same
   approved-scope evidence as authorization, exactly as it today treats
   `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` and a scoped `git-push` grant. Until that lands, the shell
   guard passing the command through does **not** authorise the push by itself — the pre-push hook
   still refuses without `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` or a scoped grant.
3. The claim-board evidence must resolve to an operator-written approval (OI-004's coordinator-only
   rule: `source=coordinator` only when the reference resolves to an operator comment and the push
   touches no held path).

Until 1–3 land, this patch changes **nothing** for live pushes: with `TRADEAI_APPROVED_SCOPE_REF`
unset (the default), every `git push` still requires a `git-push` grant, exactly as today. The patch
only (a) stops the OI-132 false positive and (b) makes the shell guard *able* to honor an approved
scope without weakening anything.

---

## Safety analysis — what this patch does NOT weaken

- **§0 rules 1–3, 5–7 unchanged.** No broker/secret/delete path is touched.
- **Self-grant is still blocked in every real form** — direct, compound (`&&`/`;`/`|`), and
  code-executing wrappers (`bash -c`, `sh -c`, `eval`, `exec`, `python* -c`, `node`/`perl` `-e`).
- **Never-push-`main`/`release/*`, force-push, branch deletion, and history rewrite remain
  `git-push`** (hard-gated) under every condition, including when `TRADEAI_APPROVED_SCOPE_REF` is set.
- **No new tier is grantable.** `approvals` is added to `tier_scope()` for a correct deny message and
  is hard-denied by the companion `guard-shell.sh` edit; it is **not** added to `bin/guard`'s
  `ALL_TIERS`, so it can never be granted.
- **The pre-push hook remains the authority** for remote sync (`TRADEAI_REMOTE_PUSH_AUTHORIZED=1`
  plus a scoped grant, the per-branch budget, the policy-freshness gate and the secrets scan). The
  shell guard is a *front* gate; passing it through never authorises a push by itself.

## Residual gaps (stated, not hidden)

- The `approvals)` hard-deny requires the companion `guard-shell.sh` edit; the patch file here covers
  `guard-lib.sh` only.
- `TRADEAI_APPROVED_SCOPE_REF` is a forgeable env var until the wrapper + pre-push-hook work (items
  1–3 above) land. It must be treated as a *hint to stop double-gating*, never as push authorization.
- The de-quote strips simple `"..."` and `'...'` spans; escaped/nested quotes are not fully handled.
  A residual quoted false positive still *over-blocks* (fails safe) and never *under-blocks*.
- A bare `git push` (no refspec) passes the shell guard when `TRADEAI_APPROVED_SCOPE_REF` is set; if
  `HEAD` were `main` the pre-push hook and the §0 rule 4 "never push `main`" still bind. Agents work
  in worktrees off `origin/main` (§28.15 item 3), so this is the designed posture, not a new hole.

## What is held vs. what needs operator merge + two reviews

- **Held (`guard-config`) and needs §28.15 item 3 (two `Adversarial-review: MERGE` receipts + the
  operator's own merge):** the `.cursor/hooks/guard-lib.sh` change (this patch) **and** the companion
  `.cursor/hooks/guard-shell.sh` `approvals)` edit. Reviews alone never merge them.
- **Not held (ordinary work, its own PRs):** the three "not yet wired" pieces in §"Not yet wired"
  (the push-wrapper env plumbing, the pre-push-hook approved-scope authorization, and the
  claim-board `Operator-approval:` resolution) — but the pre-push-hook piece is itself
  `[shared-infra]`/guard-adjacent and should be reviewed with the same care.
- **This proposal packet** (`docs/ops/packets/guard-fix-20261028/`) is documentation only and does
  not touch any held path.
