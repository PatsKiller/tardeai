# Advice digests — 10:00 / 15:00 / 17:00 ET (2026-10-08)

Your request: new CIO decisions, re-entry, upgrades and downgrades, and any advice that isn't urgent go into
comprehensive HTML digests. Each one shows the ticker, catalyst, rating, entry, target and latest news, with links to
the ticker in the Command Center and to the item in the Communication Center. Digests go out at 10 a.m., 3 p.m. and
5 p.m.; the 5 p.m. one also shows what moved up or down.

**Decisions (2026-10-08):**
- Scalp alerts and approval requests stay immediate.
- **All** CIO entry alerts go to the digest. This reverses the 2026-09-15 "page immediately" decision.
- The 5 PM "moved up/down" section covers price moves, rating changes, conviction-rank changes and new catalysts.
- The old scheduled digests fold into the new schedule.

## What changed

| Piece | File |
|---|---|
| Rules: slots, holds, sections, movers thresholds | `config/advice_digest.yaml` |
| Builder (collect, enrich, render HTML) | `scripts/lib/advice_digest.py` |
| Sender (window, watermark, mark, receipt) | `scripts/send_advice_digest.py` (lane `advice-digest`, `0 10,15,17 * * 1-5`, market-day gate) |
| Latest news per symbol | `lib/data_broker/catalyst_record.get_latest_news` (the `news_articles` projection) |
| Communication Center links | `/v3/communications?event=<id>` opens a message; `?q=<ticker>` filters the feed |

### What stops paging and feeds the digest

Each item can be rolled back by setting its hold to false in `config/advice_digest.yaml`. The file is read on every
send, so no deploy is needed.

| Hold | Where | Effect |
|---|---|---|
| `cio_entry_state` | `operator_alert_policy_v2` | Entry alerts from the entry runner and entry planner route to DIGEST (bucket ADVICE) instead of IMMEDIATE. They are still written to the Communications ledger. |
| `cio_entry_bot_copy` | `cio_entry_state_runner.send_alerts` | The direct CIO-bot copy of each entry alert is not sent (`cio_desk_reason=held_for_advice_digest`). |
| `cio_advisory_outbox` | `cio_notification_delivery.poll_and_deliver` | CIO-bot `advisory` notes (CIO advisory actions, RE_ENTER_IF and re-entry notes) stay PENDING. The digest includes them and marks them DELIVERED with the digest's message id. |
| `thesis_update` | `operator_alert_policy_v2` | Thesis updates route to DIGEST. |
| `material_change_buy_ready` | `notify_material_change.classify` | A watchlist BUY_READY material change goes to the digest. Held names that hit a stop or target, or make a big move, **still page**, because that is capital at risk. |

**Still immediate:** scalp alerts (their producers bypass the router), approval requests, stop health,
orphaned/unprotected positions, broker auth, protection failures, and platform/data-integrity alarms.

### What each digest contains

- **Header:** slot, time, item count, and a link to the Communication Center.
- **Entry setups** (CIO entry alerts and other reward advice; scalps excluded), **Re-entry**, and **CIO decisions &
  research** (CIO advisory notes, research and watch candidates). Each section shows at most 8 items, one block per
  ticker, newest first. Each block holds:
  - `$TICKER` (links to its opportunity view) · company · kind;
  - what the alert said;
  - 💲 live price with today's change · **rating** (analyst consensus and count) · **Street target** with upside
    (above +150% is flagged "⚠ check");
  - 🎯 **entry** zone · stop · **target** · R:R · CIO conviction and rank;
  - ⚡ latest **catalyst**;
  - 📰 latest **news** headline, linked, with source and age;
  - 🔗 **Ticker in Command Center** · **Communication Center** (the exact message where one exists, otherwise the
    ticker's feed).

  A ticker with only a price collapses to one line.
- **17:00 only — MOVED TODAY:**
  - **Price:** held, watchlist and top-150 names moving ±4% or more, plus today's material changes as "N× its
    normal daily move".
  - **Ratings:** analyst key changes, or a mean-target move of 5% or more, against the previous snapshot.
  - **CIO conviction:** moves of ±5 points, with rank, from today's CIO opportunity versions.
  - **New catalysts:** catalysts first seen today.
- **Other updates:** the archived P1 items (stop warnings, system health…) grouped by kind, so nothing the old P1
  digest carried is lost.
- Messages split at block boundaries, never mid-tag, at about 3,800 characters each.

### Folded

| Old schedule | Now |
|---|---|
| P1 digest (every 4 h) | the OTHER UPDATES section; its watermark advances after a confirmed digest send |
| Alert digest 08:00 / 16:00 | idle since `digest_queue` has had no rows in 7 days; the cron line is removed |
| Closed-trade digest 16:30 | removed. It reported Alpaca **paper** trades, and those never alert (operator rule 2026-09-22) |
| Material-change digest 16:15 | the 17:00 MOVED TODAY section |

The crontab change (remove five lines, add one) is made after deploy under a cron grant. The crontab is archived
first.

## Verify

1. Dry run: `scripts/send_advice_digest.py --slot 17` prints the messages and sends nothing.
2. Run `tests/test_advice_digests_20261008.py` (gate `advice_digests_20261008`).
3. After the first live run, `data/runtime/advice_digest_latest.json` holds message ids and counts. Held CIO notes
   show DELIVERED with `digest:<message id>`.
