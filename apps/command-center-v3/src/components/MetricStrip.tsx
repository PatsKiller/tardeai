import { useApi } from '../hooks/useApi'
import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import { runLabel } from '../lib/homeLabels'
import { overviewSurfaceFreshness, tradeAiSurfaceFreshness } from '../lib/surfaceFreshness'
import { renderSetupCounts } from '../lib/setupRunSummary'
import { BB, T, TYPE } from '../lib/watchTokens'
import type { DrillContext } from './DetailDrawer'


interface Props {
  onDrill: (ctx: DrillContext) => void
}

export default function MetricStrip({ onDrill }: Props) {
  const navigate = useNavigate()

  const { data: overview } = useApi<any>('/api/v2/overview', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 120_000)
  const { data: gate } = useApi<any>('/api/v2/live-trading-gate', 120_000)
  const { data: health } = useApi<any>('/api/v2/health', 120_000)
  // The badge showed a bare number over a heart. "27" of what, out of what, and
  // does it reconcile with the page it links to? Each part of the population is
  // counted separately so the badge can name its own definition rather than
  // presenting a total whose basis lives only in this expression.
  const healthFindings = (health?.findings ?? []) as any[]
  const healthCritical = healthFindings.filter((f: any) => f.severity === 'critical').length
  const healthWarning = healthFindings.filter((f: any) => f.severity === 'warning').length
  const healthWarn = healthCritical + healthWarning
  const healthOther = healthFindings.length - healthWarn
  const healthPopulation =
    `${healthWarn} of ${healthFindings.length} findings from /api/v2/health` +
    ` · ${healthCritical} critical + ${healthWarning} warning` +
    (healthOther ? ` · ${healthOther} below threshold, not counted` : '')

  const portfolioVal = overview?.portfolio_value
  // Canonical aggregate contract (cc-header-truth-v2 Phase 2 A). The header total
  // is an ALL-ACCOUNTS aggregate; a named account is only ever the oldest/stale
  // contributor, never the source of the whole total.
  const portfolioAgg = overview?.portfolio_aggregate
  // Read scope from the contract — never hardcode. Live acceptance 2026-09-03
  // failed when UI said ALL ACCOUNTS while aggregate clocks contradicted rows.
  const portfolioScopeLabel = String(
    portfolioAgg?.portfolio_scope ?? portfolioAgg?.aggregate_scope ?? '',
  )
    .replace(/_/g, ' ')
    .trim()
  // TODAY sums today_by_account across every linked account, so its provenance is the
  // same all-accounts scope as PORTFOLIO. It previously fell back to `overviewAcct` --
  // a single account name -- and rendered "TODAY -$2,908 · data_as_of ... ·
  // alpaca_taxable_live" beside "PORTFOLIO ... ALL ACCOUNTS". The number was right and
  // the attribution named one account it did not come from, which is worse than an
  // obviously missing label: it reads as authoritative.
  // TodayPnl@v1. The P&L's own session, calculation time and account coverage
  // now travel with the number. Before this block existed the tile borrowed
  // `data_as_of` -- the position observation -- and stamped a 2026-09-04
  // intraday figure "2026-09-03".
  const todayPnl = overview?.today_pnl
  const todayAccountCount = Object.keys(overview?.today_by_account ?? {}).length
  const todayLinked = todayPnl?.linked_account_count ?? null
  // Funded, not linked: an account holding nothing cannot make the day
  // incomplete. TODAY warned "2 acct(s) missing" and flagged itself STALE over
  // the same two $0 accounts PORTFOLIO correctly called empty.
  const todayFunded = todayPnl?.funded_account_count ?? todayLinked
  const todayRepresented = todayPnl?.represented_account_count ?? todayAccountCount
  const todayMissing: string[] = todayPnl?.missing_accounts ?? []
  const todayEmpty: string[] = todayPnl?.empty_accounts ?? []
  // Account census for TODAY lives on hover, not the face (operator 2026-09-04).
  // True missing funded accounts still raise the face STALE chip via `todayMissing`.
  const todayHoverAccounts = (() => {
    const scope = todayPnl?.scope?.replace(/_/g, ' ') || portfolioScopeLabel || 'ALL ACCOUNTS'
    if (todayLinked == null) {
      return todayAccountCount > 0 ? `${scope} · ${todayAccountCount} contributing` : scope || null
    }
    const cover = `${todayRepresented}/${todayFunded} funded accts`
    const emptyPart = todayEmpty.length ? ` · ${todayEmpty.length} empty (${todayEmpty.join(', ')})` : ''
    const missingPart = todayMissing.length ? ` · MISSING ${todayMissing.join(', ')}` : ''
    return `${scope} · ${cover}${emptyPart}${missingPart}`
  })()

  // ── the six clocks, each named (live capture 2026-09-04, release a7c550d1d) ──
  //
  // The header showed "data_as_of 2026-09-03" beside a book panel saying
  // "session 2026-09-04" and a status line saying "observed 2026-09-04 13:30:02
  // ET · last refresh 2026-09-04T07:43:15". Four clocks, one of them named, and
  // the one that was named belonged to a $5,000 account standing in front of a
  // $1.28M total. PortfolioAggregate@v2 publishes each separately; nothing here
  // may collapse two of them back into one word.
  const cov = portfolioAgg?.coverage
  const posNewest = portfolioAgg?.position_observation_newest ?? null
  const posOldest = portfolioAgg?.position_observation_oldest ?? null
  const posOldestAcct = portfolioAgg?.position_observation_oldest_account ?? null
  const posOldestAgeH = portfolioAgg?.position_observation_oldest_age_hours ?? null
  const valuationTime = portfolioAgg?.valuation_time ?? null
  const quoteObsTime = portfolioAgg?.quote_observation_time ?? null

  const ageMark = (h: number | null) =>
    h == null ? '' : h >= 48 ? ` (${Math.round(h / 24)}d old)` : ` (${Math.round(h)}h old)`

  // How much of the aggregate VALUE the headline date actually speaks for. On
  // the captured book this was 0.4% -- the single number that makes a fresh date
  // over a stale book impossible to state honestly.
  const coverageMark =
    cov?.at_newest_pct != null ? ` · covers ${cov.at_newest_pct}% of value` : ''
  // Undated is now counted over CONTRIBUTORS. Listing three $0 accounts as
  // "undated" made a fully-observed book look half-unobserved.
  const undatedMark =
    cov?.accounts_undated
      ? ` · ${cov.accounts_undated}/${cov.accounts_contributing ?? cov.accounts_total} contributing undated`
      : ''
  // Accounts holding nothing are named, not counted against coverage.
  const emptyMark =
    cov?.accounts_non_contributing
      ? ` · ${cov.accounts_non_contributing} empty (${(cov.non_contributing_accounts ?? []).join(', ')})`
      : ''
  // Two copies of the position clock disagreeing is reported on the surface,
  // never silently resolved. account_summaries.as_of is not maintained; the
  // position rows are. Both are published and the divergence is stated.
  const clockDivergences = (portfolioAgg?.observation_divergences ?? []) as { account: string; detail: string }[]
  const divergenceMark = clockDivergences.length
    ? ` · ⚠ ${clockDivergences.length} clock divergence${clockDivergences.length > 1 ? 's' : ''}`
    : ''

  // Account + date detail on HOVER only (operator 2026-09-04). The face keeps the
  // position date and compact warnings; naming every account inline crowded the
  // strip and duplicated tip content. Provenance is not dropped — tip + drill
  // still carry oldest stamp/age, empties, coverage, and divergences.
  const oldestLine = posOldest
    ? `oldest ${posOldestAcct ?? '—'} ${posOldest}${ageMark(posOldestAgeH)}`
    : cov?.accounts_undated
      ? `no dated position observation (${cov.accounts_undated} account(s) undated)`
      : 'oldest —'

  const portfolioHoverAccounts = portfolioAgg && portfolioScopeLabel
    ? [
        `scope ${portfolioScopeLabel}`,
        `${cov?.accounts_contributing ?? portfolioAgg.included_account_count ?? '?'} funded accts${coverageMark}`,
        oldestLine,
        undatedMark.replace(/^ · /, '') || null,
        emptyMark.replace(/^ · /, '') || null,
        divergenceMark.replace(/^ · /, '') || null,
      ].filter(Boolean).join('\n · ')
    : null

  // Face may only carry compact non-account warnings so divergence is not silent.
  const portfolioFaceNote = clockDivergences.length
    ? `⚠ ${clockDivergences.length} clock divergence${clockDivergences.length > 1 ? 's' : ''}`
    : null

  const clockLines = [
    posNewest ? `positions observed ${posNewest} (newest, ${portfolioAgg?.position_observation_newest_account ?? '—'})${coverageMark}` : 'positions observed UNDATED',
    oldestLine,
    valuationTime ? `valued ${valuationTime}` : 'valued UNDATED',
    quoteObsTime ? `quotes observed ${quoteObsTime}${portfolioAgg?.quote_source ? ` (${portfolioAgg.quote_source})` : ''}` : 'quotes observed UNDATED',
  ]
  // No source-mixing null-coalesce (cc-header-truth-v2 Phase 2 E). The TRADING
  // tile must come from one internally-consistent projection — the live broker
  // journal — and never silently borrow the paper-trade-readiness win rate when
  // the journal is absent. Paper readiness stays visible in the drill rows only.
  const winRate = overview?.journal?.win_rate
  const winTrades = overview?.journal?.trade_count
  const regimeLabel = regime?.regime_label ?? '—'
  const regimeConf = regime?.confidence
  // Prefer API stale + cached_at over session-normalized run_date (heal can label "today"
  // while the cache stays empty for days — census/bisect 2026-08-28).
  const setupsFresh = tradeAiSurfaceFreshness(tradeAi)
  const overviewFresh = overviewSurfaceFreshness(overview)
  const scanStale = setupsFresh.stale
  const setupsRun = runLabel(tradeAi?.run_label ?? tradeAi?.latest_run_label, tradeAi?.run_date)
  const setupsAsOfMark = setupsFresh.asOf
    ? ` · as_of ${String(setupsFresh.asOf).slice(0, 19).replace('T', ' ')}`
    : ''
  // GAP 2. This said "as_of" while the value is the DATA clock, so the chip
  // named the one field it is specifically not reporting. It also went blank
  // when the money had no date -- and after the UNDATED fix that silence would
  // be the whole rendering. Silence must never be indistinguishable from a
  // healthy block (AGENTS.md 9.1), so UNDATED is stated.
  const overviewAcct = overviewFresh.dataAsOfAccount
  const overviewAcctMark = overviewAcct ? ` (${overviewAcct})` : ''
  const overviewAsOfMark = overviewFresh.dataAsOf
    ? ` · data_as_of ${String(overviewFresh.dataAsOf).slice(0, 19).replace('T', ' ')}${overviewAcctMark}`
    : ` · data_as_of UNDATED${overviewAcctMark}`
  const operatorLive = !!gate?.operator_live_via_2fa_allowed
  const autoLive = gate?.status === 'AUTHORIZED'
  const liveBadge = operatorLive ? '2FA LIVE' : autoLive ? 'AUTO LIVE' : 'AUTO BLOCKED'
  const liveBadgeBlocked = !operatorLive && !autoLive
  const todayChange = overview?.today_change
  const todayPct = overview?.today_pct
  const journalPnl = overview?.journal?.total_pnl
  const realizedPnl = overview?.journal?.realized_pnl
  const realizedCount = overview?.journal?.realized_count
  const longTermTrimPnl = overview?.journal?.long_term_trim_pnl
  const journalLastClose = overview?.journal?.last_close_date
  const journalLastIngested = overview?.journal?.last_ingested_at
  // Provenance (cc-header-truth-v2 Phase 2 E): TRADING and REALIZED must state
  // their basis, window, account scope and as-of so a mixed-source or
  // differently-windowed figure can never masquerade as the same number.
  const journalScope = overview?.journal?.account_scope ?? 'schwab'
  const journalWindow = overview?.journal?.time_window ?? 'all-time'
  const journalAsOf = overview?.journal?.as_of
  const journalIngestedHours = (() => {
    if (!journalLastIngested) return null
    const ms = Date.now() - new Date(String(journalLastIngested)).getTime()
    return isFinite(ms) && ms > 0 ? ms / 3_600_000 : null
  })()
  // STALE now means "journal pipeline hasn't rebuilt recently" (72h spans weekends), not
  // "haven't closed a trade recently" — a quiet market is not stale data.
  const journalStale = journalIngestedHours != null && journalIngestedHours > 72
  const journalAgeMark = journalStale ? ` · not refreshed ${Math.round(journalIngestedHours)}h` : ''
  const journalRefreshedMark = journalLastIngested ? ` · journal rebuilt ${new Date(String(journalLastIngested)).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''
  const vix = tradeAi?.vix
  const vixSource = tradeAi?.vix_source
  const vixObsTime = tradeAi?.vix_observation_time
  const approvals = overview?.pending_approvals ?? overview?.approvals_count
  const priceStamp = pricingStampLine(overview?.pricing ?? { last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source })
  // Canonical quote-selection projection (cc-header-truth-v2 Phase 2 B). The
  // header must distinguish the selected quote provider from an eligible
  // fallback and must surface DEGRADED/UNAVAILABLE rather than a healthy-looking
  // price when Finviz is down and a read-only alternate answered.
  const quoteSel = overview?.quote_selection
  // "quotes DEGRADED (price_cache_nav(1))" said something was wrong and nothing
  // about how much. A degraded aggregate must state its coverage: how many
  // symbols the selected provider actually answered for, and how many fell back.
  const quoteCovered = quoteSel?.covered_symbols ?? quoteSel?.selected_symbol_count ?? null
  const quoteTotal = quoteSel?.total_symbols ?? quoteSel?.symbol_count ?? null
  const quoteDegradedN = quoteSel?.degraded_symbol_count ?? null
  const quoteCoverMark =
    quoteCovered != null && quoteTotal != null ? ` ${quoteCovered}/${quoteTotal} symbols` : ''
  // Face: short status only. Coverage / fallback reason / observation time live
  // on hover — live capture 2026-09-04 showed the full line painting over PORTFOLIO
  // (brand cell whiteSpace:nowrap + maxWidth without ellipsis).
  const quoteStatusFace = (() => {
    if (!quoteSel) return null
    if (quoteSel.status === 'UNAVAILABLE') return ' · quotes UNAVAILABLE'
    if (quoteSel.fallback_used) return ' · quotes DEGRADED'
    return null
  })()
  const quoteStatusTip = (() => {
    if (!quoteSel) return null
    if (quoteSel.status === 'UNAVAILABLE') return ' · quotes UNAVAILABLE'
    if (quoteSel.fallback_used) {
      const n = quoteDegradedN != null ? `${quoteDegradedN} ` : ''
      return ` · quotes DEGRADED · ${n}on ${quoteSel.fallback_reason ?? 'fallback'}${quoteCoverMark}`
    }
    return ` · quotes ${quoteSel.selected_provider ?? '—'}${quoteCoverMark}`
  })()
  // Observation time of the SELECTED quote, distinct from the aggregate's
  // valuation time and from the browser's receipt clock.
  const quoteObservedMark = quoteSel?.selected_observation_time
    ? ` · observed ${quoteSel.selected_observation_time}`
    : ''
  const pricesFace = [priceStamp, quoteStatusFace].filter(Boolean).join('')
  const pricesTip =
    `Holdings repriced via ${quoteSel?.selected_provider ?? overview?.pricing?.reprice_source ?? overview?.reprice_source ?? 'finviz'}` +
    (quoteStatusTip ?? '') +
    quoteObservedMark +
    (quoteSel?.fallback_used ? ` · fallback ${quoteSel.fallback_reason}` : '') +
    (quoteSel?.status === 'UNAVAILABLE' ? ' · no eligible quote source' : '') +
    ' · /api/v2/overview'

  // Canonical run-scoped summary (cc-header-truth-v2 corrective pass). One
  // taxonomy, one reconciliation, identical to HomeHub and the Trading page.
  // setup_run_summary is the SOLE source of the GO/WAIT/NOGO counts: the legacy
  // go_count / wait_count / avoid_count fallback is gone, so a mixed-source or
  // differently-scoped count can never masquerade as the same number. The
  // GO+WAIT+NOGO == classified_count invariant is re-derived client-side and a
  // PARTIAL / COUNT_MISMATCH verdict is surfaced, never hidden.
  const setupRun = renderSetupCounts(tradeAi?.setup_run_summary, {
    stale: scanStale,
    staleLabel: setupsFresh.surfaceLabel || `STALE · ${setupsRun}`,
  })
  // Face = counts only. Population (classified/scanned/review) is a secondary
  // line — stuffing both into one lg monospace string wrapped mid-token and
  // painted over the run id (live capture 2026-09-04).
  const setupsValue = scanStale
    ? setupRun.counts
    : setupRun.degraded
      ? `${setupRun.counts} · ${setupRun.integrity}`
      : setupRun.counts
  const setupsSub = scanStale ? null : (setupRun.population || null)

  const tiles = [
    {
      label: 'PORTFOLIO', value: portfolioVal != null ? fmt$(portfolioVal, 0) : '—',
      valueSub: null as string | null,
      stale: overviewFresh.stale ? (overviewFresh.surfaceLabel?.replace(/^STALE · /, ' · ') || overviewAsOfMark) : null,
      // The tile shows the POSITION observation. Saying "data_as_of" named no
      // clock at all; saying "positions observed" names the one on screen and
      // leaves the other three visibly absent rather than silently merged.
      asOf: posNewest ?? overviewFresh.asOf,
      asOfLabel: 'positions observed',
      asOfNote: portfolioFaceNote,
      undated: !posNewest && !overviewFresh.dataAsOf,
      color: overviewFresh.stale ? BB.amber : 'var(--text0)',
      tip: `Total portfolio equity — an ALL-ACCOUNTS aggregate${portfolioAgg?.included_account_count != null ? ` of ${portfolioAgg.included_account_count} account(s)` : ''} (Schwab, Alpaca, Moomoo). No single account is the source of the total.\n\nACCOUNTS (hover):\n · ${portfolioHoverAccounts ?? '—'}\n\nFOUR SEPARATE CLOCKS:\n · ${clockLines.join('\n · ')}\n\nThe newest position observation dates ${cov?.at_newest_pct ?? '—'}% of the aggregate value; ${cov?.value_fresh_pct ?? '—'}% is within ${cov?.stale_after_hours ?? 48}h.${clockDivergences.length ? `\n\nCLOCK DIVERGENCE — two copies of the position clock disagree:\n · ${clockDivergences.map(d => `${d.account}: ${d.detail}`).join('\n · ')}\naccount_summaries.as_of is not maintained by the loader; the position rows are. Neither copy is edited.` : ''} Refreshes every 2 min via /api/v2/overview.${overviewFresh.stale ? ` · ${overviewFresh.reason}` : ''}`,
      drill: { title: 'Portfolio (ALL ACCOUNTS)', subtitle: overviewFresh.stale ? `STALE · ${oldestLine}` : `All-account aggregate · ${portfolioAgg?.included_account_count ?? '?'} account(s)${coverageMark}`, endpoint: '/api/v2/overview',
        rows: overview ? [{ portfolio_value: overview.portfolio_value, positions_observed_newest: posNewest, positions_observed_oldest: posOldest, positions_observed_oldest_account: posOldestAcct, positions_observed_oldest_age_hours: posOldestAgeH, valuation_time: valuationTime, quote_observation_time: quoteObsTime, quote_source: portfolioAgg?.quote_source, coverage: cov, observation_divergences: clockDivergences, portfolio_aggregate: overview.portfolio_aggregate, total_cash: overview.total_cash, position_count: overview.position_count, today_change: overview.today_change, today_pct: overview.today_pct, as_of: overview.as_of, surface_stale: overviewFresh.stale, surface_reason: overviewFresh.reason }] : [] },
    },
    {
      label: 'TODAY',
      value: todayChange != null ? `${todayChange >= 0 ? '+' : ''}${fmt$(todayChange, 0)}${todayPct != null ? ` ${todayPct >= 0 ? '+' : ''}${todayPct}%` : ''}` : '—',
      valueSub: null as string | null,
      // A P&L is stamped with its OWN session, never the position clock.
      stale: todayMissing.length ? ` · ${todayMissing.length} funded acct(s) did not report` : null,
      asOf: todayPnl?.session_date ?? null,
      asOfLabel: 'P&L session',
      asOfNote: null,
      undated: !todayPnl?.session_date,
      color: overviewFresh.stale ? BB.amber : todayChange == null ? 'var(--text3)' : todayChange >= 0 ? BB.green : BB.red,
      drill: { title: "Today's Move", subtitle: `${todayPnl?.session_date ? `session ${todayPnl.session_date}` : 'session UNDATED'} · ${todayHoverAccounts ?? todayPnl?.coverage_reason ?? 'coverage unknown'}`, endpoint: '/api/v2/overview',
        rows: overview ? [
          { today_change: overview.today_change, today_pct: overview.today_pct, pnl_session_date: todayPnl?.session_date, pnl_session_source: todayPnl?.session_source, pnl_calculated_at: todayPnl?.calculated_at, pnl_mark_source: todayPnl?.mark_source, scope: todayPnl?.scope, linked_accounts: todayLinked, funded_accounts: todayFunded, represented_accounts: todayRepresented, contributing_accounts: todayPnl?.contributing_accounts, zero_change_accounts: todayPnl?.zero_change_accounts, empty_accounts: todayEmpty, missing_accounts: todayMissing, portfolio_value: overview.portfolio_value, surface_stale: overviewFresh.stale },
          ...Object.entries(overview.today_by_account ?? {})
            .sort((a: any, b: any) => Math.abs(b[1].change) - Math.abs(a[1].change))
            .map(([acct, d]: any) => ({
              account: acct, today_change: d.change,
              today_pct: d.pct != null ? `${d.pct >= 0 ? '+' : ''}${d.pct}%` : null,
              account_value: d.value, top_movers: d.top_movers || null,
            })),
        ] : [] },
      tip: `Today's net change ($ and %).\n\nACCOUNTS (hover):\n · ${todayHoverAccounts ?? '—'}\n\n · P&L session: ${todayPnl?.session_date ?? 'UNDATED'}${todayPnl?.session_source ? ` (from ${todayPnl.session_source})` : ''}\n · calculated: ${todayPnl?.calculated_at ?? '—'}\n · marks: ${todayPnl?.mark_source ?? '—'}\n · coverage: ${todayPnl?.coverage_reason ?? '—'}\n\nThis is the P&L's OWN session — not the date the share counts were observed (${posNewest ?? 'UNDATED'}). Click for the per-account breakdown. Refreshes every 2 min.`,
    },
    {
      // Win rate + trade count on the face; P&L on the sub line so the tile
      // does not wrap mid-token under terminal density.
      label: 'TRADING',
      value: winRate != null ? `${winRate}% win${winTrades ? ` · ${winTrades} trades` : ''}` : '—',
      valueSub: journalPnl != null ? `${fmt$(journalPnl, 0)} P&L` : null,
      stale: journalStale ? journalAgeMark : null,
      color: winRate != null && winRate >= 50 ? BB.green : winRate != null ? BB.amber : 'var(--text3)',
      tip: `Active trading only (day + swing), broker round-trips · ${journalScope} · ${journalWindow}${journalAsOf ? ` · as_of ${String(journalAsOf).slice(0, 19).replace('T', ' ')}` : ''}${journalLastClose ? ` · last close ${journalLastClose}` : ''}${journalRefreshedMark}. Excludes long-term trims of old holds — those are in REALIZED. Win rate excludes $0 scratches.`,
      drill: { title: 'Trading (active)', subtitle: `Day + swing round-trips · ${journalScope} · ${journalWindow} · excludes long-term position trims${journalLastClose ? ` · through ${journalLastClose}` : ''} · REALIZED tile shows all closed incl. trims`, endpoint: '/api/v2/overview',
        rows: [{ trading_win_rate: overview?.journal?.win_rate, trading_trades: overview?.journal?.trade_count, trading_pnl: overview?.journal?.total_pnl, realized_win_rate: overview?.journal?.realized_win_rate, realized_trades: realizedCount, realized_pnl: realizedPnl, long_term_trim_pnl: longTermTrimPnl, basis: overview?.journal?.basis, account_scope: overview?.journal?.account_scope, time_window: overview?.journal?.time_window, as_of: overview?.journal?.as_of, last_close_date: overview?.journal?.last_close_date, last_ingested_at: overview?.journal?.last_ingested_at, ledger_last_trade_time: overview?.journal?.ledger_last_trade_time, paper_readiness_win_rate: readiness?.win_rate, paper_usable_trades: readiness?.closed_usable }] },
    },
    {
      label: 'REALIZED', value: realizedPnl != null ? fmt$(realizedPnl, 0) : '—',
      valueSub: null as string | null,
      stale: journalStale ? journalAgeMark : null,
      color: realizedPnl == null ? 'var(--text3)' : realizedPnl >= 0 ? BB.green : BB.red,
      tip: `All closed P&L incl. long-term trims of old buy-and-hold lots · ${journalScope} · ${journalWindow}${journalAsOf ? ` · as_of ${String(journalAsOf).slice(0, 19).replace('T', ' ')}` : ''}${longTermTrimPnl ? ` (${fmt$(longTermTrimPnl, 0)} of it is long-term trims)` : ''}${journalLastClose ? ` · last close ${journalLastClose}` : ''}${journalRefreshedMark}. Trading-only P&L is ${journalPnl != null ? fmt$(journalPnl, 0) : '—'}.`,
      drill: { title: 'Realized P&L (all closed)', subtitle: `Includes long-term position trims — not just trading · ${journalScope} · ${journalWindow}${journalLastClose ? ` · through ${journalLastClose}` : ''}`, endpoint: '/api/v2/overview',
        rows: [{ realized_pnl: realizedPnl, realized_trades: realizedCount, long_term_trim_pnl: longTermTrimPnl, trading_pnl: overview?.journal?.total_pnl, trading_trades: overview?.journal?.trade_count, basis: overview?.journal?.basis, account_scope: overview?.journal?.account_scope, time_window: overview?.journal?.time_window, as_of: overview?.journal?.as_of, last_close_date: overview?.journal?.last_close_date, last_ingested_at: overview?.journal?.last_ingested_at }] },
    },
    {
      label: 'REGIME',
      value: regimeLabel ? `${regimeLabel.replace(/_/g, ' ')}${regimeConf ? ` ${Math.round(regimeConf * 100)}%` : ''}` : '—',
      valueSub: null as string | null,
      color: regimeLabel === 'risk_off' ? BB.red : regimeLabel === 'risk_on' ? BB.green : BB.amber,
      tip: `Market regime from /api/v2/risk-regime/latest — weighs trend, breadth, and volatility signals into a risk-on/risk-off label with confidence.`,
      drill: { title: 'Market Regime', subtitle: 'From /api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest',
        rows: regime ? [{ regime_label: regime.regime_label, confidence: regime.confidence, volatility_state: regime.volatility_state, trend_state: regime.trend_state, breadth_state: regime.breadth_state, summary: regime.summary }] : [] },
    },
    {
      label: 'VIX', value: vix != null ? Number(vix).toFixed(1) : '—',
      valueSub: null as string | null,
      color: vix == null ? 'var(--text3)' : vix >= 25 ? BB.red : vix >= 18 ? BB.amber : BB.green,
      tip: `CBOE Volatility Index. Green <18 (low fear), amber 18-25 (elevated), red ≥25 (high fear).${vixSource ? ` · source ${vixSource}` : ''}${vixObsTime ? ` · observed ${String(vixObsTime).slice(0, 19).replace('T', ' ')}` : ''}`,
      drill: { title: 'VIX', subtitle: `Volatility index · source ${vixSource ?? 'unknown'}${vixObsTime ? ` · observed ${vixObsTime}` : ''}`, endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ vix: tradeAi.vix, vix_source: tradeAi.vix_source, vix_observation_time: tradeAi.vix_observation_time, market_regime: tradeAi.market_regime, run_label: tradeAi.run_label }] : [] },
    },
    {
      label: 'SETUPS · LATEST RUN',
      value: setupsValue,
      valueSub: setupsSub,
      // Extra amber mark when value already contains STALE (keeps label chip + as_of visible).
      stale: scanStale ? `${setupsAsOfMark || ' · stale'}` : null,
      // The captured header read "as_of 2026-09-04 17:39" with no zone, beside a
      // Home panel saying "9:00 AM scan · Sep 4" -- two renderings of one run,
      // eight hours apart, because one was the run's scheduled ET time and the
      // other a UTC cache stamp. The run's own id and timestamp are shown, and
      // the zone is stated.
      asOf: setupRun.runTimestamp ?? setupsFresh.asOf,
      asOfLabel: setupRun.runTimestamp ? 'run' : 'as_of',
      asOfNote: [
        setupRun.runId ? `id ${setupRun.runId}` : null,
        setupRun.unaccounted ? `${setupRun.unaccounted} UNACCOUNTED` : null,
      ].filter(Boolean).join(' · ') || null,
      color: scanStale ? BB.amber : setupRun.degraded ? BB.amber : setupRun.goPositive ? BB.green : 'var(--text3)',
      tip: scanStale
        ? `Scanner surface is STALE (${setupsFresh.reason || 'prior/empty cache'}). ${setupsRun}${setupsAsOfMark}. HTTP 200 is not a live claim — Trading → Trade AI shows the same payload.`
        : `Latest scanner run · ${setupRun.population || '—'}${setupRun.runId ? ` · run ${setupRun.runId}` : ''}${setupRun.runTimestamp ? ` · ${setupRun.runTimestamp}` : ''}${setupRun.integrity !== 'RECONCILED' ? ` · ${setupRun.integrity}` : ''}`,
      drill: { title: 'Trade Setups', subtitle: scanStale ? (setupsFresh.surfaceLabel || `STALE — last ${setupsRun}`) : `Latest scanner run · ${setupRun.population || '—'}${setupRun.runId ? ` · run ${setupRun.runId}` : ''}`, endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ scope: scanStale ? 'stale' : 'latest run only', run_id: tradeAi.run_id, setup_run_summary: tradeAi.setup_run_summary, universe_go: tradeAi.universe_go, universe_wait: tradeAi.universe_wait, universe_nogo: tradeAi.universe_nogo, run_label: tradeAi.run_label, run_date: tradeAi.run_date, cached_at: tradeAi.cached_at, cache_age_sec: tradeAi.cache_age_sec, stale: tradeAi.stale, surface_stale: setupsFresh.stale, surface_reason: setupsFresh.reason, vix: tradeAi.vix, vix_source: tradeAi.vix_source, market_regime: tradeAi.market_regime, run_health_status: tradeAi.run_health_status }] : [] },
    },
  ]

  return (
    <div className="metric-strip" style={{ display: 'flex', flexDirection: 'column', background: 'var(--bg0)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, padding: '8px 12px 6px', minWidth: 0, overflowX: 'auto' }}>
      <div
        data-testid="metric-strip-brand"
        style={{
          marginRight: 12,
          flex: '0 0 168px',
          maxWidth: 168,
          minWidth: 140,
          overflow: 'hidden',
          position: 'relative',
          zIndex: 1,
          background: 'var(--bg0)',
          paddingRight: 8,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <div style={{ fontSize: TYPE.md, fontWeight: 700, color: T.link, whiteSpace: 'nowrap' }}>Command Center v3</div>
        {pricesFace && (
          <div
            data-testid="metric-strip-prices"
            title={pricesTip}
            onClick={() => onDrill({
              title: 'Price Freshness',
              subtitle: `${priceStamp ?? ''}${quoteStatusTip ?? ''}${quoteObservedMark}`,
              endpoint: '/api/v2/overview',
              rows: [
                overview?.quote_selection ? { quote_selection: overview.quote_selection } : null,
                overview?.pricing ?? { last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source },
              ].filter(Boolean),
            })}
            style={{
              fontSize: TYPE.xs,
              color: quoteSel?.fallback_used || quoteSel?.status === 'UNAVAILABLE' ? BB.amber : 'var(--text3)',
              marginTop: 2,
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >{pricesFace}</div>
        )}
      </div>
      {tiles.map(t => (
        <div key={t.label}
          className="metric-strip-tile"
          title={(t as any).tip}
          onClick={() => onDrill(t.drill)}
          style={{
            padding: '2px 12px',
            cursor: 'pointer',
            textAlign: 'center',
            borderRight: '1px solid var(--border)',
            flex: t.label.startsWith('SETUPS') ? '1 1 200px' : '0 0 auto',
            minWidth: t.label.startsWith('SETUPS') ? 160 : undefined,
            maxWidth: t.label.startsWith('SETUPS') ? 320 : undefined,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            minHeight: 56,
          }}
        >
          <div className="metric-strip-label" style={{ fontSize: TYPE.xs, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', whiteSpace: 'nowrap' }}>
            {t.label}{(t as any).stale && <span style={{ color: BB.amber, fontWeight: 800 }} data-surface-stale>{' '}⚠ STALE</span>}
          </div>
          <div
            className="metric-strip-value"
            style={{
              fontSize: t.label.startsWith('SETUPS') ? TYPE.md : TYPE.lg,
              fontWeight: 700,
              color: t.color,
              fontFamily: 'monospace',
              whiteSpace: 'nowrap',
              lineHeight: 1.2,
            }}
          >
            {t.value}{(t as any).stale && !String(t.value).includes('STALE') && <span style={{ fontSize: TYPE.xs, color: BB.amber }}>{(t as any).stale}</span>}
          </div>
          {(t as any).valueSub && (
            <div
              className="metric-strip-sub"
              style={{
                fontSize: TYPE.xs,
                fontWeight: 600,
                color: t.label === 'TRADING' ? t.color : 'var(--text2)',
                fontFamily: 'monospace',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                marginTop: 1,
                lineHeight: 1.2,
              }}
            >
              {(t as any).valueSub}
            </div>
          )}
          {(t as any).asOf && (
            <div
              className="metric-strip-asof"
              style={{
                fontSize: TYPE.xs,
                color: (t as any).stale ? BB.amber : 'var(--text3)',
                marginTop: 2,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                lineHeight: 1.2,
              }}
              data-surface-as-of
            >
              {(t as any).asOfLabel || 'as_of'} {String((t as any).asOf).slice(0, 16).replace('T', ' ')}
              {(t as any).asOfNote ? ` · ${(t as any).asOfNote}` : ''}
            </div>
          )}
          {!(t as any).asOf && (t as any).undated && (
            <div
              className="metric-strip-asof"
              style={{ fontSize: TYPE.xs, color: BB.amber, marginTop: 2, whiteSpace: 'nowrap' }}
              data-surface-as-of
              data-surface-undated
            >
              {(t as any).asOfLabel || 'as_of'} UNDATED
            </div>
          )}
        </div>
      ))}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, paddingLeft: 8 }}>
      {approvals != null && approvals > 0 && (
        <div onClick={() => navigate('/')}
          title={`${approvals} pending approvals — Home → Action Inbox has CTAs to Risk and Trading`}
          style={{ padding: '4px 12px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700, cursor: 'pointer',
            background: BB.amberDim, color: BB.amber, whiteSpace: 'nowrap' }}>
          ⚑ {approvals} APPROVALS →
        </div>
      )}
      {healthWarn > 0 && (
        <div onClick={() => navigate('/health')}
          title={`${healthPopulation}. Open Health for remediate + coder dispatch — the badge and that page count the same population.`}
          style={{ padding: '4px 12px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700, cursor: 'pointer',
            background: BB.redDim, color: BB.red, whiteSpace: 'nowrap' }}>
          ♥ {healthWarn} HEALTH{healthCritical ? ` (${healthCritical} crit)` : ''} →
        </div>
      )}
      <div
        title={gate?.operator_status_label || (operatorLive ? 'Schwab operator live via standing unlock + per-order 2FA' : 'Autonomous Alpaca live gate not passed')}
        style={{
        padding: '4px 14px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700, whiteSpace: 'nowrap',
        background: operatorLive ? BB.greenDim : liveBadgeBlocked ? BB.amberDim : BB.greenDim,
        color: operatorLive ? BB.green : liveBadgeBlocked ? BB.amber : BB.green,
      }}>
        {liveBadge}
      </div>
      </div>
    </div>
    </div>
  )
}
