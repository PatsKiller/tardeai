Status:      BLOCKED
as_of:       2026-09-01T21:31:24-04:00
run_id:      mp-20260901-210554
Canonical repo path: docs/implementation/maturity-program/mp-20260901-210554/STAGE_01_DRIVE_MIRROR_VERIFICATION.md
Verdict:     **NOT MIRRORED — no permitted mechanism can guarantee byte-exactness**

# Stage 1.6 · Drive mirror

## Done

Searched before creating, as required.

```
Trade_AI_Docs_v2        1Zxc20B5Xo24RGZ1Pow1-uW6ldASQJHiR   pre-existing
  governance            15ozcQNMP1zc0inDxpmgwsI2lXH8cgY0h   CREATED 2026-09-02T01:29:15Z
    agent-policy        1spBGi8OgIpDE1p2tlIXzk8fJLqxqMCCU   CREATED 2026-09-02T01:29:21Z
```

**No `AGENTS.md` exists anywhere on Drive** (title search, 30 results) — so there is no
multiple-candidate ambiguity and no stop condition on that count. The folder tree did not exist,
and the program authorizes creating it.

**Not touched:** `agents_bible.md` (`19rgu_foRGYd3Z6NxEobOnNxLuBUtj7S30SKDa6or-Rg`, Google Doc,
2026-05-21). §1.1 names it non-canonical. It is a stale competing artifact on Drive and is left
exactly where it is.

## Blocked: no permitted mechanism transfers bytes

| mechanism | verdict |
|---|---|
| `scripts/sync-docs-to-drive.py` (repo's own uploader, gog-based) | **FORBIDDEN.** Line 19 reads `/home/johnclaw/.openclaw/credentials/gog_keyring_password`. That is a credential read, which this program's authority envelope prohibits outright. |
| `scripts/sync-docs-to-drive.sh` (production hourly cron, :05) | Same credential path. Also syncs only `docs/` and `config/strategies` — `governance/` is outside its `SYNC_ROOTS`, so it will never carry this file. |
| connected Drive MCP `create_file` | **Available, but inline-content only.** It cannot read from a path. |

The MCP route requires reproducing **93,379 bytes / 1,596 lines** as generated text.
**Transcription cannot guarantee byte-exactness**, and byte-exactness is the whole requirement:

> *"download/read it back, compute SHA-256 again, and require exact equality"* · `verification: BYTE_EXACT`

Attempting it would produce either a verified pass or a silent-until-checked mismatch. The
read-back check would catch a mismatch, so nothing unsafe ships either way — but the mechanism is
wrong for the guarantee, and choosing it is the operator's call, not mine.

## What is ready the moment a mechanism is authorized

```
content commit   85373d2acd6e9e51291374175f4c42faede8fe9d
AGENTS.md sha256 eebf799f34a17d3439a8f56475c7a7d7c97bfed4c3354a367404a02a4d9cfa8c
target folder id 1spBGi8OgIpDE1p2tlIXzk8fJLqxqMCCU
manifest path    docs/ops/AGENTS_DRIVE_MIRROR_MANIFEST.json   (not written — no file id yet)
```

The manifest is deliberately **not** written. It records `drive_file_id`, `uploaded_at`,
`verified_at` and `verification: BYTE_EXACT`. Writing it now would assert a mirror that does not
exist — the "absent field renders as affirmative" defect §9.1 forbids.

## Options for the operator

1. **You run the repo sync.** It already has the credential and targets the canonical root; you
   would point it at `governance/agent-policy`. Cleanest — real byte transfer, no secret read
   by an agent.
2. **Authorize the inline MCP upload**, accepting that verification is by read-back and may need
   a retry. I do not recommend it as the standing mechanism.
3. **Defer the mirror** to a follow-up once a path-based uploader exists that does not read a
   credential. Stage 1's repository half is complete and approvable without it.

## Finding

**CORRECTED 2026-09-01.** This section originally read *"There is no credential-free
path-based Drive uploader in this repository."* **That was wrong.** `scripts/gog_broker.sh`
already existed and brokers the keyring secret from Bitwarden without reading the credential
path. It was missed because the search was `scripts/*drive*` — **by filename, not by
capability** — which is the detector-shape mistake §7 describes, made while writing a report
about detector shape.

`scripts/mirror_agents_md_to_drive.sh` (PR #842, merged `c02cfc92c`) now performs the
byte-exact mirror through that broker. It still requires the operator to unlock the vault once
(`export BW_SESSION=$(bw unlock --raw)`); it will not prompt and will not fall back to a weaker
source.

Any future agent asked to mirror
a governed document byte-exactly hits this same wall. That is a gap worth closing deliberately
rather than rediscovering.
