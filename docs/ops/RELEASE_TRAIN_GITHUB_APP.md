# Release train GitHub App: operator setup (decision D2)

```
Status:      DRAFT (operator procedure; nothing is created on GitHub by this document or its PR)
as_of:       2026-10-21T21:30:00Z
Measured at: origin/main 7faa8cddf; GitHub facts checked against docs.github.com on 2026-10-21 (links below);
             repository and protection read with `gh api` on 2026-10-21 (outputs quoted in §1)
```

Owner: platform. Operator decision D2, 2026-10-21: the release train writes to GitHub through a **GitHub App**. The
release service mints a 1-hour installation token per use, and the operator creates the App. This document covers
creating the App, installing it, storing its key on the host, minting tokens, and what the App's permissions can and
cannot restrict. It arms nothing. Creating the App, installing it, placing the key and changing rulesets or branch
protection are all operator acts (AGENTS §17; proposed 17.0.0 adds "GitHub App custody").

Related code (libraries only, not wired): `scripts/lib/release_capability.py` (per-train, per-phase capabilities),
`scripts/lib/release_control.py` (STOP/pause/resume/revoke), `scripts/lib/release_delegation.py`
(`ReleaseDelegation@v1`). The App token is the **transport**. Authority comes from the host capability: the release
service asks for a token only while it holds a reservation from `CapabilityAuthority.reserve()`, and it down-scopes the
token to that phase.

---

## 1. Facts this setup rests on

| Fact | Evidence |
|---|---|
| The repository is `PatsKiller/tardeai`. It is **public** and **owned by a user account**, not an organization. | `[VERIFIED]` `gh api repos/PatsKiller/tardeai` on 2026-10-21 returned `{"private":false,"visibility":"public","owner_type":"User"}`. |
| Branch protection on `main` requires three contexts: `cio-hardening`, `agent-governance` and `release-readiness`. It also has `strict:false`, `enforce_admins:true` and `restrictions:null`. | `[VERIFIED]` `gh api repos/PatsKiller/tardeai/branches/main/protection` on 2026-10-21. |
| No repository rulesets exist. | `[VERIFIED]` `gh api repos/PatsKiller/tardeai/rulesets` on 2026-10-21 returned `[]`. |
| An installation access token expires after **1 hour**. | `[DOC-CLAIM]` GitHub docs, [Generating an installation access token](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app): "The installation access token will expire after 1 hour." |
| A token is minted with `POST /app/installations/{installation_id}/access_tokens`, authenticated with the App's JWT. The body may narrow the token with `repositories` / `repository_ids` and `permissions`. A token can never gain a permission the App was not granted. | `[DOC-CLAIM]` same page. |
| The JWT is signed **RS256** and carries `iat`, `exp` and `iss`. `exp` may be at most 10 minutes ahead. GitHub recommends setting `iat` 60 s in the past for clock drift. `iss` is the App's client ID (recommended) or its app ID. | `[DOC-CLAIM]` [Generating a JWT for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app). |
| Merging a PR (`PUT /repos/{o}/{r}/pulls/{n}/merge`) needs **Contents: write**. Creating or updating a ref (`POST/PATCH …/git/refs`) needs **Contents: write**; changing a ref that touches `.github/workflows/` also needs **Workflows: write**. Creating a PR needs **Pull requests: write**. Reading check runs and check suites needs **Checks: read**. | `[DOC-CLAIM]` [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps). |
| **An App permission cannot be limited to a path or a branch.** Contents: write applies to every ref in every repository the installation can reach. | `[DOC-CLAIM]` The permissions reference scopes by resource and access level only, and no path or branch scope exists. **This corrects the brief**, which asked for "contents: write limited to the train path". That limit has to come from repository rulesets plus the host capability (§4). |
| Rulesets can target branches by `fnmatch` pattern (for example `train/**`). They offer *Restrict creations*, *Restrict updates* and *Restrict deletions*, each applying to everyone except the ruleset's bypass list, and a **GitHub App can be on that list**. | `[DOC-CLAIM]` [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [Available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets). Rulesets on a public user-owned repository have **not** been tried here: the first step of §4 is to check that the Settings → Rules page offers them. |

---

## 2. Create the App (operator, in the browser)

GitHub → your account **Settings → Developer settings → GitHub Apps → New GitHub App**.

| Field | Value |
|---|---|
| Name | `tradeai-release-train` (GitHub names are global, so add a suffix if this one is taken) |
| Homepage URL | the repository URL |
| Webhook | **Active: off.** The release service polls. No inbound endpoint is exposed. |
| Where can this App be installed? | **Only on this account** |
| Repository permissions | **Contents: Read and write**; **Pull requests: Read and write**; **Checks: Read-only**; **Metadata: Read-only** (mandatory, and selected automatically). Leave everything else **No access**. That includes Workflows, Administration, Actions, Secrets, Environments, Deployments and Commit statuses. |
| Organization / account permissions | none |
| Subscribe to events | none |

**Workflows: write is deliberately not granted.** A train whose batch changes `.github/workflows/**` cannot be pushed or
merged by the App, and GitHub refuses the ref update. Such PRs stay on the manual operator path. This is the
safer setting, and the classifier (Phase 1) should hold them.

After creating the App, record its **App ID** and **Client ID**. Then **Generate a private key**: the browser downloads one `.pem` file.

## 3. Install it on `PatsKiller/tardeai` only

App page → **Install App** → your account → **Only select repositories** → `tardeai` → Install. Record the
**installation id**, the number at the end of the installation's settings URL.

Check that the installation reaches only this repository, by minting a token (§5) and calling
`GET /installation/repositories`. `total_count` must be 1, with `full_name` `PatsKiller/tardeai`.

## 4. Where the "train path only" restriction actually lives

App permissions cannot restrict the App to `train/**`, so the restriction has three layers. The operator applies the first two
in GitHub settings, and each one is a §17 branch-protection decision. The plan lists this under D4, and arming is not done here.

1. **Ruleset `release-train-refs`**, targeting `refs/heads/train/**`. Rules: *Restrict creations*, *Restrict updates*
   and *Restrict deletions*. Bypass list: the `tradeai-release-train` App only. Result: no agent token and no
   person (unless the operator adds Repository admin as an emergency bypass) can create or move `train/*`, and the
   App can.
2. **`main` stays behind its required checks.** Do **not** put the App on a bypass list of anything that carries the
   required status checks, because a bypass actor skips every rule in that ruleset. Two options for enforcing
   "agents never merge" technically:
   - **(a)** A separate ruleset `main-merge-actor`, targeting `main`, with only *Restrict updates* and the App (plus,
     optionally, Repository admin) on its bypass list. Classic branch protection keeps the three required contexts
     and `enforce_admins:true`, so the App still needs green checks to merge. **Test this on a scratch repository first.**
     The interaction between a ruleset bypass and classic protection on a user-owned public repository has not been
     tried here.
   - **(b)** Leave `main` as it is and rely on policy (17.0.0: agents never merge) plus the guard hooks (D6, log mode
     today). The guard hooks are log-only, so this option is not enforced.
3. **The host capability.** The release service mints a token only inside `CapabilityAuthority.reserve()` for the
   current train and phase. It requests only that phase's permissions (§5) and pushes only `refs/heads/train/<train_id>`
   (the build capability's `output_ref`). A merge needs a merge capability whose bound base SHA, candidate SHA,
   ordered PR heads and CI evidence match what GitHub shows at that moment.

## 5. The private key on the host, and minting 1-hour tokens

**Key custody.**

```
install -d -m 700 ~/.config/tradeai/release_train
mv ~/Downloads/tradeai-release-train.*.private-key.pem ~/.config/tradeai/release_train/github-app.pem   # move: one copy
chmod 600 ~/.config/tradeai/release_train/github-app.pem
```

- The key is **outside the repository**, with mode 600 inside a mode-700 directory, and is owned by the release service's user.
- It never lives in `.env`, in n8n, in the Command Center, in Drive or in a backup that leaves the box (AGENTS §2A, §24.7).
- Agents never read, copy or symlink it (§24.7). Add the path to the guard's credential-path list when the guard
  patches are next applied.
- Non-secret identifiers go beside it in `~/.config/tradeai/release_train/github-app.json` (mode 600):
  `{"app_id": …, "client_id": "Iv…", "installation_id": …, "repository": "PatsKiller/tardeai"}`.
- **Rotation:** generate a second key on the App page, install it the same way, then delete the old key **on GitHub**.
  The old local file is archived (renamed with a date suffix), never deleted (§0 rule 6).
- **Revocation in an emergency:** suspend the installation (Install App → Configure → Suspend). Every token stops
  working within the hour at most, and new tokens cannot be minted. Pair it with `scripts/release_control_cli.py stop`.

**Minting.** The service does this; agents never do it. It is implemented by `GitHubAppTokenMinter` /
`GitHubAppWriter` in `scripts/lib/release_train_controller.py` (arming finding 3, branch
`fix/release-train-arming-blockers-20261021`; reservation binding, branch
`feat/release-train-app-token-reservation-20261022`): one token per capability reservation, minted on the first write
inside `writer.reservation(<intent id>, <action>)` (which the controller enters right after `reserve()`), never outside
one and never for another action, and dropped when the reservation ends. It is RS256 signed with `cryptography`. The
`git push` child receives it as `GH_TOKEN` and as an `http.extraheader` scoped to `https://github.com/` through its
`GIT_CONFIG_*` environment, with every inherited `GH_TOKEN`/`GITHUB_TOKEN` stripped; the parent process environment
never holds it. Only `refs/heads/train/<id>` is pushed. It stays inert while `GITHUB_WRITES_STATUS` is `PROPOSED`.

**The pinned App.** The operator's App is pinned in code: App ID `5419776`, installation `173961421`, repository
`PatsKiller/tardeai` (`APP_ID`, `APP_INSTALLATION_ID`, `APP_REPOSITORY`). `github-app.json` is optional; absent, the
pins are used with the App ID as the JWT `iss`; present, it must be mode 600 and agree with every pin, and a
`client_id` in it becomes the `iss`. A file naming another App, installation or repository is refused before anything
is signed.

1. Build a JWT: header `{"alg":"RS256","typ":"JWT"}`; claims `iat = now − 60`, `exp = now + 540` (under the 10-minute
   cap), `iss = <client_id>`. Sign it with `github-app.pem`.
2. `POST https://api.github.com/app/installations/<installation_id>/access_tokens` with
   `Authorization: Bearer <JWT>`. The body **always** narrows the token:
   - build/publish phase: `{"repositories":["tardeai"],"permissions":{"contents":"write","pull_requests":"write","checks":"read","metadata":"read"}}`;
   - merge phase: the same set (merge needs contents write; reading checks confirms the evidence);
   - promote phase: `{"repositories":["tardeai"],"permissions":{"contents":"read","checks":"read","metadata":"read"}}`.
     Promotion happens on the host and writes nothing to GitHub.
3. Hold the token in memory only, for the duration of the reservation. Never write it to disk, to a log, to a
   receipt or to the environment of a child process that outlives the reservation. Log only `expires_at` and the
   granted `permissions` from the response.
4. Mint a fresh token for each reservation, and do not cache one across reservations. A token outliving its capability
   is the failure the capability exists to prevent.

## 6. Operator checklist

- [ ] Create the App with exactly the permissions in §2, webhook off, installable only on this account.
- [ ] Install it on `tardeai` only, and record the app id, client id and installation id.
- [ ] Place the key per §5. Run `stat -c '%a %U' ~/.config/tradeai/release_train/github-app.pem`, which should print `600 <user>`.
- [ ] Mint a token by hand once and run `GET /installation/repositories` (total_count 1). Discard the token.
- [ ] Decide §4 (1) and (2), and apply the rulesets. These are §17 branch-protection decisions.
- [ ] Do not arm anything. Arming the delegation is `scripts/release_control_cli.py arm` at the host, a separate
      §17 act after 17.0.0 is ratified.
