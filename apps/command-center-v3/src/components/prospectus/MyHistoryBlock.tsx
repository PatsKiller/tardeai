/** Prospectus — "My history" (the operator's own trades in this ticker) and the fund profile.
 *  Operator 2026-10-26: "What is my average cost? Have I won or lost, P&L? What were the catalysts that hit? ... If I
 *  owned it multiple round trips, should that be analyzed? This is a customized prospectus for me."
 *  Renders blocks.my_history (scripts/lib/prospectus/my_history.py) right after the verdict tiles, and
 *  blocks.fund_profile (etf_profile.py). Generic: any absent field shows "—"; an absent block shows nothing (never
 *  traded) or "not available". Accounts arrive by name only. Phone: lots and trips are tap-to-open rows (44px+). */
import { Card, NotAvailable } from './ProspectusBlocks'
import { CiteText } from './Citations'
import {
  dayText, daysText, eventLabel, eventTone, fundProfileOf, headline, lessonValue, money, myHistoryOf, numText, pctText,
  reactionText, tone, whyText, type HistoryEvent, type RoundTrip,
} from '../../lib/myHistoryModel'
import './MyHistoryBlock.css'

function Events({ events, testId }: { events?: HistoryEvent[]; testId: string }) {
  if (!events?.length) return <p className="psp-muted" data-testid={testId}>No recorded catalysts, earnings, 8%+ days or stop fills in this window.</p>
  return (
    <ul className="psp-mh-events" data-testid={testId}>
      {events.map((e, i) => (
        <li key={i} className="psp-mh-event">
          <span className={`psp-mh-dot psp-mh-dot-${eventTone(e)}`} aria-hidden="true" />
          <span className="psp-mh-ev-date">{dayText(e.date)}</span>
          <span className="psp-mh-ev-what">{eventLabel(e)}</span>
          <span className="psp-mh-ev-react psp-muted">{reactionText(e)}</span>
        </li>
      ))}
    </ul>
  )
}

function TripRow({ t }: { t: RoundTrip }) {
  const flags = [(t.wash_sale?.flag ? 'Wash-sale window' : null), (t.stopped_out ? 'Stopped out' : null)].filter(Boolean) as string[]
  return (
    <details className="psp-mh-trip" data-testid="prospectus-mh-trip" data-trip={t.trip}>
      <summary className="psp-mh-trip-sum">
        <span className="psp-mh-trip-n">Trip {t.trip}</span>
        <span className="psp-mh-trip-dates">{dayText(t.entry_date)} → {dayText(t.exit_date)}</span>
        <span className={`psp-mh-trip-pl psp-tone-${tone(t.realized_usd)}`} data-testid="prospectus-mh-trip-pl">
          {money(t.realized_usd, true)} <span className="psp-muted">({pctText(t.realized_pct)})</span>
        </span>
        <span className="psp-mh-trip-meta psp-muted">{t.account ?? '—'} · {daysText(t.hold_days)}</span>
        {flags.map(f => <span key={f} className={`psp-chip psp-tone-${f.startsWith('Wash') ? 'warning' : 'danger'}`} data-testid="prospectus-mh-flag">{f}</span>)}
      </summary>
      <div className="psp-mh-trip-body">
        <div className="psp-mh-grid">
          <div><span className="psp-mh-k">Entry</span><b>{money(t.entry_price)}</b> <span className="psp-muted">{dayText(t.entry_date)}</span></div>
          <div><span className="psp-mh-k">Exit</span><b>{money(t.exit_price)}</b> <span className="psp-muted">{dayText(t.exit_date)}</span></div>
          <div><span className="psp-mh-k">Shares · hold</span><b>{numText(t.shares)}</b> <span className="psp-muted">{daysText(t.hold_days)} · {t.term ? `${t.term}-term` : '—'}</span></div>
          <div><span className="psp-mh-k">R-multiple</span><b>{t.r_multiple == null ? '—' : `${numText(t.r_multiple)}R`}</b> <span className="psp-muted">{t.tax_character ?? ''}</span></div>
        </div>
        <p className="psp-body-sm" data-testid="prospectus-mh-why"><b>Why you got in:</b> {whyText(t)}{t.thesis_at_entry ? ` — “${t.thesis_at_entry}”` : ''}</p>
        {t.entry_vs_52w_range_pct != null && <p className="psp-muted">Entry sat at {numText(t.entry_vs_52w_range_pct, 0)}% of its 52-week range.</p>}
        <div className="psp-mh-k">What happened while you held it</div>
        <Events events={t.while_held} testId="prospectus-mh-trip-events" />
        {t.journal?.lesson && <p className="psp-body-sm"><b>Journal:</b> {t.journal.lesson}</p>}
        {t.wash_sale?.flag && (
          <p className="psp-body-sm psp-tone-warning" data-testid="prospectus-mh-wash">
            Loss sale with a repurchase inside the 61-day wash-sale window
            {(t.wash_sale.replacements ?? []).length ? ` (bought again ${(t.wash_sale.replacements ?? []).map(r => dayText(r.date)).join(', ')})` : ''}.
          </p>
        )}
      </div>
    </details>
  )
}

export function MyHistoryBlock({ blocks, symbol, phone }: { blocks?: unknown; symbol: string; phone?: boolean }) {
  const mh = myHistoryOf(blocks)
  const title = phone ? 'My history' : `My history · your trades in ${symbol}`
  if (!mh) return null
  if (mh.scope === 'never_traded') {
    return (
      <Card title={title} testId="prospectus-my-history" label="My history">
        <p className="psp-muted" data-testid="prospectus-mh-never">You have no position and no round trips on record in {symbol}.</p>
      </Card>
    )
  }
  if (mh.scope !== 'held' && mh.scope !== 'previously_traded') {
    return <Card title={title} testId="prospectus-my-history" label="My history"><NotAvailable what="My history" gaps={mh.gaps} /></Card>
  }
  const kpis = headline(mh)
  const lots = mh.open_lots ?? []
  const trips = [...(mh.trips ?? [])].reverse()
  const stats = mh.lessons?.stats ?? []
  const notes = mh.lessons?.journal_notes ?? []
  const tax = mh.tax ?? {}
  return (
    <Card title={title} testId="prospectus-my-history" label="My history" className="psp-mh">
      <div className="psp-mh-kpis" data-testid="prospectus-mh-kpis">
        {kpis.map(k => (
          <div key={k.id} className="psp-mh-kpi" data-testid={`prospectus-mh-${k.id}`}>
            <span className="psp-mh-k">{k.k}</span>
            <b className={k.tone ? `psp-tone-${k.tone}` : undefined}>{k.v}</b>
            {k.sub && <span className="psp-muted">{k.sub}</span>}
          </div>
        ))}
      </div>
      {mh.writer_note?.summary && <p className="psp-body" data-testid="prospectus-mh-summary"><CiteText text={mh.writer_note.summary} /></p>}

      {lots.length > 0 && (
        <section aria-label="Open lots" data-testid="prospectus-mh-lots">
          <h3 className="psp-mh-h">Open position by account</h3>
          {phone ? (
            <ul className="psp-mh-cards">
              {lots.map((l, i) => (
                <li key={i} className="psp-mh-card" data-testid="prospectus-mh-lot">
                  <div className="psp-mh-card-top"><b>{l.account ?? '—'}</b><span className={`psp-tone-${tone(l.unrealized_usd)}`}>{money(l.unrealized_usd, true)} ({pctText(l.unrealized_pct)})</span></div>
                  <div className="psp-muted">{numText(l.shares)} sh @ {money(l.avg_cost)} · {daysText(l.holding_days)} · {l.term ? `${l.term}-term` : 'term n/a'} · {l.tax_character ?? ''}</div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="psp-table-wrap">
              <table className="psp-table">
                <thead><tr><th>Account</th><th>Shares</th><th>Avg cost</th><th>Unrealized</th><th>Held</th><th>Term</th><th>Tax</th></tr></thead>
                <tbody>
                  {lots.map((l, i) => (
                    <tr key={i} data-testid="prospectus-mh-lot">
                      <td>{l.account ?? '—'}</td><td>{numText(l.shares)}</td><td>{money(l.avg_cost)}</td>
                      <td className={`psp-tone-${tone(l.unrealized_usd)}`}>{money(l.unrealized_usd, true)} ({pctText(l.unrealized_pct)})</td>
                      <td>{daysText(l.holding_days)}{l.acquired_first ? <span className="psp-muted"> since {dayText(l.acquired_first)}</span> : null}</td>
                      <td title={l.lot_dating_note ?? undefined}>{l.term ? `${l.term}-term` : '—'}{l.lot_dating === 'unreconciled' ? ' *' : ''}</td>
                      <td>{l.tax_character ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {lots.some(l => l.lot_dating === 'unreconciled') && <p className="psp-muted">* lot dates could not be reconciled with the journal (transfers or older lots); held days are not guessed.</p>}
        </section>
      )}

      {mh.current_hold && (
        <details className="psp-mh-trip" data-testid="prospectus-mh-current">
          <summary className="psp-mh-trip-sum"><span className="psp-mh-trip-n">While you&apos;ve held it</span>
            <span className="psp-mh-trip-dates">since {dayText(mh.current_hold.since)} · {daysText(mh.current_hold.days)}</span></summary>
          <div className="psp-mh-trip-body"><Events events={mh.current_hold.while_held} testId="prospectus-mh-current-events" /></div>
        </details>
      )}

      {trips.length > 0 && (
        <section aria-label="Round trips" data-testid="prospectus-mh-trips">
          <h3 className="psp-mh-h">Round trips <span className="psp-muted">· newest first · tap to open</span></h3>
          {trips.map(t => <TripRow key={t.trip} t={t} />)}
        </section>
      )}

      {(stats.length > 0 || notes.length > 0 || mh.writer_note?.lessons) && (
        <section aria-label="Lessons" data-testid="prospectus-mh-lessons">
          <h3 className="psp-mh-h">Lessons from your trades</h3>
          {mh.writer_note?.lessons && <p className="psp-body-sm"><CiteText text={mh.writer_note.lessons} /></p>}
          <ul className="psp-mh-stats">
            {stats.map(s => <li key={s.id}><span>{s.label}</span><b>{lessonValue(s)}</b><span className="psp-muted">{s.n != null ? `${s.n} trips` : ''}</span></li>)}
            {notes.slice(0, 4).map(n => <li key={`j${n.trip}`}><span>Journal, trip {n.trip}</span><span className="psp-mh-quote">{n.lesson}</span><span /></li>)}
          </ul>
          <p className="psp-muted">Patterns in your past trades, not advice.</p>
        </section>
      )}

      {((tax.flags ?? []).length > 0 || tax.open_window || (tax.accounts ?? []).length > 0) && (
        <section aria-label="Tax flags" data-testid="prospectus-mh-tax">
          <h3 className="psp-mh-h">Tax flags</h3>
          <div className="psp-mh-chips">
            {(tax.accounts ?? []).map(a => <span key={a.account} className="psp-chip psp-tone-neutral">{a.account}: {a.character}</span>)}
            {(tax.flags ?? []).map((f, i) => <span key={i} className="psp-chip psp-tone-warning" data-testid="prospectus-mh-tax-flag">Trip {f.trip}: wash-sale window ({dayText(f.sale_date)})</span>)}
            {tax.open_window && <span className="psp-chip psp-tone-warning" data-testid="prospectus-mh-window">Window today: {tax.open_window.label ?? tax.open_window.kind}</span>}
          </div>
          {tax.note && <p className="psp-muted">{tax.note}</p>}
        </section>
      )}
      {(mh.gaps ?? []).length > 0 && <p className="psp-muted" data-testid="prospectus-mh-gaps">Not available: {(mh.gaps ?? []).slice(0, 3).join('; ')}</p>}
      <p className="psp-muted">Your own trades, from the position store, the trade journal and Rec Intelligence. Advisory — no AI places, sizes or stops orders.</p>
    </Card>
  )
}

export function FundProfileBlock({ blocks }: { blocks?: unknown }) {
  const fp = fundProfileOf(blocks)
  if (!fp) return null
  const rows: [string, string][] = [
    ['Category', fp.category ?? '—'],
    ['Sector exposure · sector ETF', `${fp.sector ?? 'broad'} · ${fp.sector_etf ?? 'none'}`],
    ['Peer funds', (fp.peers ?? []).join(', ') || '—'],
    ['Expense ratio', fp.expense_ratio_pct == null ? '—' : `${fp.expense_ratio_pct.toFixed(2)}%`],
    ['Assets under management', fp.aum_usd == null ? 'not available' : money(fp.aum_usd)],
    ['Distribution yield · trailing 12m', `${pctText(fp.dividend_yield_pct, false, 2)} · ${money(fp.ttm_distribution)}`],
    ['Last distribution · cadence', `${money(fp.last_distribution)} ${dayText(fp.last_distribution_date)} · ${fp.distribution_cadence ?? '—'}`],
    ['Analyst look-through', fp.analyst_look_through_pct == null ? '—' : `${pctText(fp.analyst_look_through_pct)}${fp.analyst_basis ? ` (${fp.analyst_basis})` : ''}`],
  ]
  return (
    <Card title="Fund profile" testId="prospectus-fund-profile" label="Fund profile">
      <div className="psp-kv">
        {rows.map(([k, v]) => <div key={k} className="psp-kv-row"><span className="psp-kv-k">{k}</span><span className="psp-kv-v">{v}</span></div>)}
      </div>
      {(fp.top_holdings ?? []).length > 0 && (
        <ul className="psp-mh-stats" data-testid="prospectus-fund-holdings">
          {(fp.top_holdings ?? []).map(h => <li key={h.name}><span>{h.name}</span><b>{pctText(h.weight_pct, false)}</b><span /></li>)}
        </ul>
      )}
      {(fp.gaps ?? []).length > 0 && <p className="psp-muted" data-testid="prospectus-fund-gaps">{(fp.gaps ?? []).join('; ')}</p>}
    </Card>
  )
}

export default MyHistoryBlock
