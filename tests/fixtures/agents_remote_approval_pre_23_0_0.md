## Remote approval by Telegram — when the operator is not at the keyboard

The workflow above needs someone at a terminal. When the operator is away, work that is finished,
verified and green otherwise waits. This moves the *typing* to Telegram. It moves the *deciding*
nowhere.

**The rule above is unchanged and unweakened: the agent must never type, pipe, simulate, automate,
or infer the confirmation word.** What follows is how the operator gives it from their phone.

```bash
# Agent side. Grants nothing. Sends the operator a message and exits.
"$GUARD_PATH" request git-push --for 30m --uses 8 --reason "merge PR #NNN, CI green on <sha>"
```

The operator receives the scope, the window, the uses, the reason and the host, and replies in
Telegram with `/approve <CODE>` or `/deny <CODE>`. The live callback poller — which already owns
the single `getUpdates` consumer, so nothing new polls and nothing collides on HTTP 409 — verifies
and issues the grant.

Properties that make this safe, each pinned by a test in
`tests/test_guard_remote_approval.py`:

- **The requesting process is not the answering process.** `guard_request_approval.py` mints a
  PENDING record; only `run_telegram_callback_poller.py` can settle it.
- **The one-time code is never printed to stdout and never written to disk** — only its SHA-256 is
  stored. The agent runs the requesting process, so a code in that process's output would be a code
  the agent could read.
- **The grant is bound to what was requested.** Scope, window and uses are fixed in the record the
  operator saw before replying; they cannot be widened afterwards.
- **A reply from an unlisted chat burns the code** rather than leaving it live for a second try.
- **Codes work once, and the answer deadline is 4 hours by default (12h ceiling).** Silence is not
  approval, and an expired request is not approval. *It was 15 minutes, which is the right number
  for someone at their desk and the wrong one everywhere else: on 2026-09-06 a request for work the
  operator had explicitly asked for expired unanswered overnight. The grant window was never the
  constraint — the answer deadline was. Set it with `--ttl`.*
- **`sudo`, `destructive`, `file-delete`, `guard-config` and `frozen-v2` can never be requested
  remotely**, and no remote window may exceed **12 hours** or **500 uses**. `guard-config` is on
  that list specifically so a phone cannot widen what a phone may do — **raising the 12-hour ceiling
  itself required a keyboard, and that is the property that makes every other limit here real.**

### The 12-hour window — raised 2026-09-06, and what still bounds it

Remote approval was capped at one hour, on the reasoning that it is for finishing a piece of work
rather than handing over the machine. The operator raised it to **12 hours** so an overnight or
full-day autonomous run can be authorised from a phone instead of requiring a keyboard they are not
at. `bin/guard grant ... --for 12h --uses 40` is now requestable remotely.

**This is a real widening and it is recorded as one.** A stolen or misdelivered code buys twelve
hours instead of one. Four things bound it, and none of them may be relaxed to make a change pass:

| bound | value | why it holds |
|---|---|---|
| `REMOTE_FORBIDDEN_SCOPES` | unchanged | `sudo`, `destructive`, `file-delete`, `frozen-v2`, `guard-config` |
| `MAX_GRANT_SECONDS` | 12h | raised at the keyboard, because `guard-config` is remote-forbidden |
| `MAX_GRANT_USES` | 500 | **was unbounded** — `int(uses)` with no check. Harmless against one hour, not against twelve |
| settlement | chat allowlist | a reply from an unlisted chat burns the code; SHA-256 only on disk; single use |

The one that carries the weight is `guard-config`. **A phone cannot widen what a phone may do** — so
this ceiling could only ever be raised by someone at the machine, which is exactly what happened.

**Two reply paths, one settlement.** The operator may type `/approve <CODE>`, or tap **Approve** on
the inline keyboard the request carries. The button sends a `callback_query`, which originates at
Telegram's servers — a bot token cannot fabricate one — so it is not a weaker door than the code.
Both paths land in `settle_by_request_id`. Proven end to end 2026-09-06: `28e47322a7` and
`7f112670b7`, both `APPROVED` / `telegram_button`, from two different allowlisted chats.

**Know which identifier is enforced.** The gate is `chat_id` against `TELEGRAM_CHAT_ID`
(`approved_by_chat`); `from_id` is recorded as metadata and gated on nothing. In a 1:1 chat
Telegram makes the two equal, which is why every settlement so far shows them matching and why it
is easy to believe the *sender* is authenticated. **They diverge in a group.** If a group chat is
ever added to the allowlist, `chat_id` is the group and every member of it can approve — the
control would still pass its own test while meaning something entirely different. Keep the
allowlist to 1:1 chats, or gate `from_id` too before adding one.

**Any link in that message is read-only, and must stay so.** A URL button carries no sender
identity — anyone holding the link is anonymous to the receiver — so a link can never be the
approval path. The tailnet FQDN in the message shows status; it grants nothing.

**The request must not be routed.** The first version printed `telegram=sent` while the router
classified the prompt `P1_DIGEST` and suppressed it into an archive nothing delivers — an approval
request the operator was never shown, reported as sent. Requests now go with `bypass_router=True`
and report *accepted for interrupt delivery*, never *sent*. See `accepted` is not `delivered`,
above: this is that rule applied to the one message class where silence blocks the work. Under 5.1.0 that
bypass is an allowlisted legacy site (§9.1); migrated, the request is a P1 intent with dedupe off, which gives the
same guarantee and adds a route receipt.

**This is auditable, not impregnable, and must not be described as more than that.** The agent runs
as the same OS user. What the mechanism guarantees is that every legitimately obtained grant carries
provenance — chat id, message id, update id and the operator's own words — so a grant explained by
neither an interactive terminal nor an allowlisted Telegram reply is a detectable anomaly.
`guard_remote_approval.unprovenanced_grants()` finds them.
