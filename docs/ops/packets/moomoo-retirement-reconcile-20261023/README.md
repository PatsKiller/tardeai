# WP-30: moomoo retirement decision packet

Status: DRAFT — operator decision and authorized metadata writer pending; no live state changed
as_of: 2026-10-24T03:02:12Z
Measured at: main `8ed8a246486317950df01f2a1846825627f369eb`; worker `codex-wp30-20261023`

The registry `assets/portfolio_accounts.yaml` already has moomoo Taxable `active: true` in both main and CURRENT. The obsolete retirement flag is in `holdings.json.account_summaries.moomoo_taxable_live`: `retired: true`, retirement date 2026-09-01, alongside stored `state: LIVE` and two holdings rows. This is metadata drift. It is not a fresh broker verification or authority to trade.

The historical `RETIRED_moomoo_taxable_live.json` is an intact `RetiredAccountRow@v1` archive. Its “tripwire” is prose asking later readers to resolve premature retirement; no tracked executable reference to that exact filename was found. Archive its bytes after resolution; never restore its old financial rows into today's holdings.

## Operator decision

Choose either outcome; the worker has chosen neither:

| Decision | Action |
|---|---|
| `UNRETIRE_ACCOUNT_RECORD` | Keep the already-active registry unchanged; authorize a one-time retirement-metadata amendment through the protected writer/shared lock; verify readback; archive the old tripwire. |
| Keep retired | Leave this packet unapplied. A separately granted broker-sync change must make the read sync honor retirement; do not silently archive the unresolved evidence. |

This packet is read-only toward holdings and the account registry. `prepare` creates a private proposal, not approval or a production write. `archive` only moves the old archive after the authoritative summary proves the approved resolution. It cannot change holdings, grant itself authority, call a broker or import broker code.

## Exact preview and preparation commands

```bash
wp30_packet=/home/johnclaw/wt-codex-wp30-20261023/docs/ops/packets/moomoo-retirement-reconcile-20261023
wp30_py=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
cd "$wp30_packet"
sha256sum SHA256SUMS
sha256sum -c SHA256SUMS
"$wp30_py" "$wp30_packet/packet.py" preview
```

Preview reads the served/persistent holdings path, registry and tripwire; divergent paths refuse. It writes only a private receipt under the operator's own `~/.cache/rtc/`. Output includes the account **name**, safe flags/clocks, row count and hashes. It does not print account identifiers, balances, shares, reasons or archived financial rows.

Only if choosing the unretire proposal:

```bash
wp30_proposal=$("$wp30_py" "$wp30_packet/packet.py" prepare --decision UNRETIRE_ACCOUNT_RECORD)
cat "$wp30_proposal"
wp30_candidate_sha=$("$wp30_py" -c 'import json,sys; print(json.load(open(sys.argv[1]))["candidate_sha256"])' "$wp30_proposal")
```

The adjacent `candidate.PRIVATE.json` contains a full private holdings copy. Never attach it to a PR, email or progress log. The proposed change sets only the target summary's `retired` flag false and adds `retirement_resolution`; historical retirement fields, every financial field, stored classification and observation clocks remain unchanged. The proposal does not force `LIVE` or refresh market/account data.

## Required writer authorization

`AGENTS.md` §7A says “Do not add a writer of holdings.json … A new writer is an operator grant (§17), not a code change.” §9.4 says “Holdings route through protected_holdings_write(), always.” The common guard currently imports the Schwab implementation. This packet therefore provides **no holdings apply/new writer**. The `apply-holdings` action explicitly refuses. Direct `jq`, Python JSON replacement or an archive-first workaround would bypass those requirements.

After reviewing the exact candidate, the operator may authorize the necessary one-time writer in the implementing agent's own session. This is a request command, **not an issued grant**:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
bin/guard grant state-write --for 3600 --uses 1 --reason "WP-30 operator chooses UNRETIRE_ACCOUNT_RECORD for moomoo Taxable; authorize one-time retirement-metadata writer under AGENTS7A, candidate SHA=$wp30_candidate_sha; shared holdings lock plus protected_holdings_write required; no shares, cash, basis, prices, classifications or financial clocks changed"
```

The implementing agent/operator must receive the actual decision/grant directly, build or select the authorized protected-writer route, and verify exact readback under the same shared lock. No existing writer was repurposed by this worker. Updating the YAML's already-true `active` flag would not clear the preserved holdings flag.

## Archive after authorized correction

Only after the authorized writer/readback is complete, capture a **new** preview. Its `archive_ready` must be true and the operator must review its safe output:

```bash
wp30_preview=$("$wp30_py" "$wp30_packet/packet.py" preview | "$wp30_py" -c 'import json,sys; value=json.load(sys.stdin); print(value["receipt"])')
cat "$wp30_preview"
```

The operator may then issue the archive-scope grant and invoke the archive command:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
bin/guard grant release-write --for 3600 --uses 1 --reason "WP-30 archive resolved retirement tripwire only: /home/johnclaw/trade-ai-releases/holdings-moomoo-retire-20260901-131731/RETIRED_moomoo_taxable_live.json into its new resolved-unretirement directory; exact-byte archive, no delete, no release, no holdings or account registry write"
"$wp30_py" "$wp30_packet/packet.py" archive --approved-preview "$wp30_preview" --decision UNRETIRE_ACCOUNT_RECORD
```

Archive requires an operator TTY and `UNRETIRE_ACCOUNT_RECORD-ARCHIVE`, a private owned preview no more than fifteen minutes old, unchanged source hashes, an already-unretired authoritative summary and its matching resolution/tripwire digest. It takes the existing `/tmp/holdings_write.lock` nonblocking. Busy lock or any drift refuses; it never retries.

The archive is renamed into a unique `resolved-unretirement-*` directory beside the old archive, with private STARTED/COMPLETE receipts and unchanged bytes. No file is deleted, no financial snapshot restored and no account state toggled. An interrupted action preserves its STARTED receipt and any moved bytes for operator inspection; no automatic rollback rewrites current financial data.

## Audit scope

`static-references.csv` maps 145 references across 65 tracked source/test/legacy files at the frozen base. Roles distinguish summary reads, assignments/constructions, presentation/type references and the five direct retirement-metadata reads in `scripts/lib/data_broker/broker_access.py`. `guard-writer-sites.csv` identifies fifteen static guarded holdings write sites, including operator/legacy routes; these are potential metadata-preserving writers, not proof every route runs.

The source registry's seven-writer historical note is narrower than this static inventory. No tracked source directly writes this account's `retired` flag. Generic loaders/syncs can retain it while updating holdings or classification. External one-off scripts, dynamic indirect access and current process reachability remain unmeasured. The CSV is a scoped inventory, not a live execution census.

Reproduce the inventory with `"$wp30_py" "$wp30_packet/audit.py"` from this worktree. No live runtime calls are made. The report explains the registry/readers/writers and remaining acceptance.
