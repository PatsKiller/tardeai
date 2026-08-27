# SCREENER-ARCH-3D — Falloff Apply Policy

## Candidate States

| State | Meaning | Automatic | Requires Flag |
|-------|---------|-----------|---------------|
| active | Present in at least one screener | Yes | No |
| source_missing | Dropped from all screeners, within TTL | Yes | No |
| retained_by_ttl | Dropped but kept by strategy TTL | Yes | No |
| reentered | Was dropped/expired, now present again | Yes | No |
| needs_refresh | Stale quotes/data, needs refresh before promotion | Yes | No |
| needs_strategy_fit_recheck | Strategy fit uncertain after source change | Yes | No |
| expired_pending_operator_review | TTL expired, awaiting operator decision | Yes | --operator-approved-expire |
| archived_human_review_only | Expired + no open position/proposal/watchpool | No | --operator-approved-archive |

## Rules

1. **Active**: Present in >= 1 screener -> keep active, clear source_missing flags
2. **Reentered**: Was dropped/stale/expired, now present -> mark reentered, clear flags
3. **Source missing**: Dropped from all screeners, within TTL -> mark source_missing + retained_by_ttl
4. **Expired**: TTL exceeded, no protection -> mark expired_pending_operator_review (requires `--operator-approved-expire`)
5. **Archived**: Expired + no open trade + no pending proposal + no watchpool + no recent catalyst -> requires `--operator-approved-archive`
6. **Never delete** catalog rows, membership history, trade history, or journal entries

## Protection Rules

A candidate is protected from expire/archive if ANY of:
- Has open paper trade
- Has pending proposal
- Is in active watchpool
- Has recent catalyst (within strategy TTL)
- Data confidence is not GOOD
- Latest full ingestion is stale (>48h)

## TTL by Strategy Family

| Family | TTL Days |
|--------|----------|
| momentum_scalp | 2-10 |
| swing_breakout / swing_trade | 10-30 |
| earnings_catalyst | Through earnings window |
| recovery_watch / speculative_growth | 30-60 |
| dividend / income / ETF | 45-180 |
| Unknown | 30 (conservative) |

## Mass Protection

- If data confidence != GOOD, produce review list only
- If latest ingestion > 48h stale, dry-run only
- If >50% of active candidates would expire, require review
