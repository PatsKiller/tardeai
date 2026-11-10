/** LQ-20261107-1352 — the Market Risk panel under the CIO card, design v5 (operator-approved 2026-11-08).
 *  Reads the HomeCioCard@v1 projection's `panel` + `notes` (GET /api/v2/home/cio-card). Sector state is the market-risk
 *  record's; other engines' disagreements are listed in the notes, never blended. Sizing is a PROPOSED rule and is
 *  labelled "proposed, needs your OK". Acknowledge / Open Risk / Review stops are the banner's own row (MarketRiskAckRow).
 *  Advisory only (MBI_BEHAVIOR = 0): every link opens a review page; nothing here places or edits an order or a stop. */
import { Link } from 'react-router-dom'
import '../../styles/cioCard.css'
import { fv, accountText, calDay, etDay, etTime, pct, px, triggerFill, usd, usdShort, type CioNote, type CioPanel, type RotateCandidate } from '../../lib/cioCard'
import type { MarketRisk } from '../../lib/marketRisk'
import { MarketRiskAckRow } from './MarketRiskBanner'
import { tierStyle } from './CioCardV5'

const when = (iso: string | undefined) => (iso ? `${etDay(iso)} ${etTime(iso).replace(/^\w+ /, '')}` : '')
const day = (d: string | undefined) => (d && /^\d{4}-\d{2}-\d{2}$/.test(d) ? calDay(d) : when(d))

function stateBadge(c: RotateCandidate) {
  if (c.leadership === 'LEADERSHIP_CONFIRMED') return <span className="st lead">LEADING (confirmed)</span>
  if (c.state === 'RESILIENT') return <span className="st res">RESILIENT</span>
  return <span className="st neu">{c.state ?? '—'}</span>
}

/** LQ-20261107-1655 / -1784 — the individual names under a defensive ETF row. The server ordered them (held names
 *  first, then the group's best RS20 constituents) and already dropped every name that fails the price, liquidity,
 *  split or RS-sanity floor. Each name is ONE line: symbol, held flag, price, and the server's relational phrase
 *  ("weaker than XLV by 6.5 pts"). A HELD name that fails a floor is still listed with its plain flag — the holding
 *  is a fact about the book, not a rank. The date and source ride in the title, never in the line. */
function StockRows({ c }: { c: RotateCandidate }) {
  const rows = c.stocks ?? []
  if (!rows.length) return c.stocks_gap ? <div className="sub sgap" data-testid="mr5-stock-gap">{c.stocks_gap}</div> : null
  const floor = c.stocks_min_price
  const cap = floor != null && Number.isFinite(floor) ? `Stocks (liquid, ≥$${floor})` : 'Stocks (liquid)'
  return (
    <div className="sk" data-testid="mr5-rotate-stocks">
      <div className="cap">{cap}</div>
      <ul>{rows.map(s => {
        const close = fv(s.close)
        // a value the server could not trace is absent; a name row without a traceable close is not drawn
        if (close == null) return null
        return (
          <li className="sr" key={s.symbol} data-testid="mr5-stock-row" title={`${s.source_id} · ${s.close.as_of}`}>
            <div className="sl" data-testid="mr5-stock-line">
              <b>{s.symbol}</b>{s.held ? ' held' : ''} {px(close)}
              {s.flag ? ` · ${s.flag}` : s.compare ? ` · ${s.compare}` : ''}
            </div>
          </li>
        )
      })}</ul>
      {c.stocks_note ? <div className="sub sgap" data-testid="mr5-stocks-note">{c.stocks_note}</div> : null}
    </div>
  )
}

/** LQ-20261107-1784 — ONE action line per group, drawn only from facts the projection already carries: a holding
 *  (HOLD), a qualifying group under the CIO's gate (WAIT), a sized tranche (PROPOSED), or a group that has not
 *  qualified yet (NO ACTION). This never derives a verdict of its own — the CIO owns the verdict, and every word
 *  here is a restatement of FILLED / the gate / qualifies. */
function actionFor(c: RotateCandidate, gated: GatedRotate['gated']): { verb: string; text: string; next?: string } {
  const p = c.proposed
  const held = c.held
  const live = fv(c.price)
  const close = fv(c.close)
  const gateWord = gated?.gate?.value ?? 'no buys'
  const priceNow = live != null ? `Now ${px(live)}` : close != null ? `No live price (last close ${px(close)})` : 'No live price'
  if (held) {
    const shares = held.shares != null ? `${held.shares} sh` : '—'
    const text = held.filled === true
      ? `Tranche 1 filled: ${shares} @ ${px(held.avg_cost)}${live != null ? ` (now ${px(live)})` : ''}.`
      : `Holding ${shares}${held.avg_cost != null ? ` @ ${px(held.avg_cost)}` : ''}${live != null ? ` (now ${px(live)})` : ''}.`
    const nt = c.next_tranche
    let next: string | undefined
    if (nt) {
      const size = `tranche ${nt.tranche} ≈ ${usdShort(nt.usd)}${nt.shares != null ? ` (~${nt.shares} sh)` : ''}`
      next = gated ? `Next: ${size}. Waiting on the CIO buys line (now ${gateWord}).`
        : nt.after ? `Next: ${size}. After ${nt.after}.`
        : `Next: ${size}.`
    } else if (gated) {
      next = `Next: tranche 1 waits on the CIO buys line (now ${gateWord}).`
    } else if (p?.tranche1_usd != null) {
      next = `Next: tranche 1 ${usd(p.tranche1_usd)}${p.shares != null ? ` (~${p.shares} sh)` : ''}. Needs your OK.`
    }
    return { verb: 'HOLD', text, next }
  }
  if (!c.qualifies) {
    const tgt = p?.target_pct != null
      ? `Starts at RESILIENT → ${p.target_pct}%${p.target_usd != null ? ` ≈ ${usdShort(p.target_usd)}` : ''}.`
      : 'No target is set.'
    const move = live != null
      ? `${priceNow}${c.dd20 != null ? `, ${pct(Math.abs(c.dd20))} off its 20-day high` : ''}.`
      : `${priceNow}.`
    return { verb: 'NO ACTION', text: `${tgt} ${move}` }
  }
  if (gated) {
    const when = gated.until?.value || gated.until_short?.value
    return { verb: 'WAIT', text: `Tranche 1 waits on ${when ?? 'the CIO buys line'} (buys now ${gateWord}).` }
  }
  if (p?.tranche1_usd != null) {
    // LQ-20261107-1654: the count is floor(usd / CURRENT price), never a count off yesterday's close. No quote
    // means no count — said plainly, not filled in from the daily close.
    const size = p.shares != null
      ? ` ≈ ${p.shares} sh${live != null ? ` at ${px(live)}` : ''}`
      : ' — share count needs a live price'
    return { verb: 'PROPOSED', text: `Tranche 1 ${usd(p.tranche1_usd)}${size}. Needs your OK.` }
  }
  return { verb: 'NO ACTION', text: `${priceNow}.` }
}

/** LQ-20261107-1389: the CIO's buys gate rides on the rotate item as its own facts (value + source + as_of).
 *  Read from the projection rather than the card so this column can state the gate without a second read. */
type GateFact = { value?: string; source_id?: string; as_of?: string }
export type GatedRotate = NonNullable<CioPanel['rotate']> & {
  gated?: { gate?: GateFact; until?: GateFact; until_short?: GateFact; line?: GateFact } | null
}

function Rotate({ r, stressed }: { r: GatedRotate; stressed: string[] }) {
  const cands = r.candidates ?? []
  const gated = r.gated
  const closeAsOf = cands.find(c => c.close)?.close?.as_of
  return (
    <div className="col" data-testid="mr5-rotate">
      <h5>Rotate · defensives</h5>
      <p>{stressed.length ? `Stress is in ${stressed.join(' / ')}. ` : ''}{cands.filter(c => c.qualifies).length
        ? `${cands.filter(c => c.qualifies).map(c => c.label).join(' and ')} qualify on the market-risk sector table.`
        : 'No defensive group qualifies on the market-risk sector table yet.'}</p>
      <div className="rk">
        {cands.map(c => {
          const act = actionFor(c, gated)
          return (
            <div className={`rc${c.qualifies ? '' : ' off'}`} key={c.symbol} data-testid="mr5-rotate-row" title={c.source_id}>
              {/* LQ-20261107-1784: one header line — GROUP · ETF · STATE — with explicit separators. The old row
                  ran the label into the ticker and the state badge into the amount ("XLVHealthcareLEADING · CONFIRMEDFILLED"). */}
              <div className="h">
                <b>{String(c.label ?? '').toUpperCase()}</b><span className="sep">·</span>
                <span className="nm">{c.symbol}</span><span className="sep">·</span>
                {stateBadge(c)}
              </div>
              {/* ONE action line, then at most one next step. The action word is a restatement of a fact the
                  projection already carries — never a verdict this view invents (the CIO owns the verdict). */}
              <div className="act" data-testid="mr5-action">
                <span className="go" aria-hidden="true">▶</span> <b>{act.verb}</b>. {act.text}
              </div>
              {act.next ? <div className="act next" data-testid="mr5-next">{act.next}</div> : null}
              <StockRows c={c} />
            </div>
          )
        })}
      </div>
      {/* LQ-20261107-1784: TODAY is the CIO's own buys line, which now stops naming a release that has already
          printed (the gate owner is time-aware). One line, derived, never a second verdict. */}
      {r.buys?.line?.value && (
        <div className="today" data-testid="mr5-today">
          <b>TODAY:</b> {r.buys.line.value}{/\.$/.test(r.buys.line.value) ? '' : '.'}
        </div>
      )}
      {/* LQ-20261107-1654: "Prices as of <ET time>" is the quote the share counts rest on. No quote → say so rather
          than label yesterday's close as the price. */}
      <div className="sub" data-testid="mr5-prices-asof">Advisory only: no order is placed.
        {r.prices_as_of ? ` Prices as of ${etTime(r.prices_as_of).replace(/^\w+ /, '')}.` : ' No current quote: share counts need a live price.'}
        {r.prices_missing?.length ? ` Not priced: ${r.prices_missing.join(', ')}.` : ''}
        {closeAsOf ? ` Last daily close ${day(closeAsOf)}.` : ''} State: market-risk sector table ({day(r.as_of)}).</div>
      <Link className="sub" to="/rotation" style={{ color: 'var(--info-color)', fontWeight: 600, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Rotation desk →</Link>
    </div>
  )
}

export default function MarketRiskPanelV5({ panel, notes, mr }: { panel: CioPanel; notes?: CioNote[]; mr: MarketRisk | null }) {
  const h = panel.header ?? {}
  const tier = fv(h.tier)
  const score = fv(h.score)
  const held = h.held
  const sec = h.sectors
  const ex = panel.exposure ?? {}
  const protect = panel.protect ?? []
  const acts = protect.filter(p => p.kind === 'action')
  const watch = protect.filter(p => p.kind === 'watch')
  const hedge = panel.hedge
  const pos = panel.positions
  const stressed = sec?.stressed ?? []
  const it = hedge?.if_triggered
  const stressedUsd = fv(ex.stressed_usd)

  return (
    <section className="mr5" data-testid="mr5-panel" aria-label="Market risk detail" style={tierStyle(tier)}>
      <div className="mr-h">
        <div className="mr-t">
          <span className="tier" style={{ fontSize: 11, padding: '4px 8px' }} data-testid="mr5-tier">{tier}</span>
          <span className="ttl">Market risk</span>
          {score != null && <span className="sc" data-testid="mr5-score">{score.toFixed(1)}<small>/100</small></span>}
          {held && <span className="pill watch" data-testid="mr5-held">readings support {held.readings_support} · held {held.held_tier}</span>}
        </div>
        <div className="mr-meta">
          {[
            h.evaluated ? `evaluated ${when(fv(h.evaluated))}` : '',
            h.confirming ? `${h.confirming.n} of ${h.confirming.of} categories confirm` : '',
            h.episode?.opened_at ? `${h.episode.tier ?? tier} since ${when(h.episode.opened_at)}` : '',
            h.episode?.acknowledged_at ? `you acknowledged ${when(h.episode.acknowledged_at)}` : '',
            'drivers in the card above',
          ].filter(Boolean).join(' · ')}
        </div>
        {sec && sec.measured != null && (
          <div className="mr-where" data-testid="mr5-where">
            {stressed.length ? <>Stress is in <b>{stressed.join(' / ')}</b></> : 'No sector is stressed'}
            {sec.stressed_sectors != null ? ` (${sec.stressed_sectors} of ${sec.measured} sectors stressed).` : '.'}
            {sec.down_5d != null ? ` ${sec.down_5d} of ${sec.measured} sectors down over 5 sessions.` : ''}
            {sec.resilient?.length ? ` Holding up: ${sec.resilient.join(', ')}.` : ''}
          </div>
        )}
      </div>

      {(ex.book_usd || ex.cash_pct_book || ex.stressed_usd || ex.largest) && (
        <div className="expo" data-testid="mr5-exposure">
          {ex.book_usd && <div title={ex.book_usd.source_id}><div className="k">Book</div><div className="v">{usd(fv(ex.book_usd))}</div><div className="s">all accounts incl. cash · {day(ex.book_usd.as_of)}</div></div>}
          {ex.cash_pct_book && <div title={ex.cash_pct_book.source_id}><div className="k">Cash</div><div className="v">{pct(fv(ex.cash_pct_book))}</div>{ex.cash_usd && <div className="s">{usd(fv(ex.cash_usd))}</div>}</div>}
          {ex.stressed_usd && <div title={ex.stressed_usd.source_id}><div className="k">In stressed groups</div><div className="v" style={{ color: 'var(--danger-color)' }}>{usd(stressedUsd)}</div>{ex.stressed_pct_book && <div className="s">{pct(fv(ex.stressed_pct_book))} of book</div>}</div>}
          {ex.largest && <div title={ex.largest.source_id}><div className="k">Largest stressed</div><div className="v">{ex.largest.symbol}</div><div className="s">{ex.largest.share != null ? `${Math.round(ex.largest.share * 100)}% ${ex.largest.group ?? ''} look-through` : ''}{ex.largest.account_label ? ` · ${ex.largest.account_label}` : ''}</div></div>}
        </div>
      )}

      <div className="cols">
        <div className="col" data-testid="mr5-protect">
          <h5>Protect · <b>{acts.length} stop change{acts.length === 1 ? '' : 's'}</b>{watch.length ? ` + ${watch.length} to watch` : ''}</h5>
          {acts.map((p, i) => (
            <div className="pr" key={`a${i}`} title={p.source_id}>
              <span className="who">{p.symbol}<span>{p.account ? accountText(p.account) : ''}{p.held_qty != null ? ` · ${Math.round(p.held_qty)} sh` : ''}</span></span>
              <a className="go" href="#cio5-acts" onClick={e => { e.preventDefault(); document.getElementById('cio5-acts')?.scrollIntoView({ behavior: 'smooth' }) }}>Action {p.n ?? i + 1} ↑</a>
              <span className="why">{p.answer === 'ADD_STOP' ? 'No working stop.' : p.stop_now != null ? `Stop ${px(p.stop_now)}.` : ''}{p.suggested_stop != null ? ` CIO suggests ${p.answer === 'ADD_STOP' ? 'adding' : 'moving'} a stop near ${p.suggested_stop.toFixed(2)}.` : ''}</span>
            </div>
          ))}
          {watch.map((p, i) => (
            <div className="pr w" key={`w${i}`} title={p.source_id}>
              <span className="who">{p.symbol}<span>{p.account_label ?? ''}</span></span>
              <Link className="go" to={`/risk?tab=exposure&symbol=${encodeURIComponent(p.symbol)}`}>Review stop →</Link>
              <span className="why">{p.stop_distance_pct != null ? `Stop ${pct(p.stop_distance_pct)} below the last close.` : ''}{p.stressed_share != null ? ` ${Math.round(p.stressed_share * 100)}% in stressed groups.` : ''}{p.value_usd != null ? ` ${usd(p.value_usd)}.` : ''}</span>
            </div>
          ))}
          {protect.length === 0 && <p className="sub">No stop change or close stop on the book.</p>}
          <div className="sub">Advisory only: each link opens the stop review. No order is placed.</div>
        </div>

        {hedge && (
          <div className="col" data-testid="mr5-hedge">
            <h5>Hedge · needed?</h5>
            <p><span className="pill watch">{hedge.verdict ?? 'UNKNOWN'}</span>{hedge.cash_pct_book != null ? ` Cash is ${pct(hedge.cash_pct_book)} of the book. ` : ' '}A paid hedge is weighed if one of these trips:</p>
            <div className="trg">
              {(hedge.triggers ?? []).map(t => {
                const f = triggerFill(t)
                const unit = t.key.endsWith('pct_book') ? '%' : ''
                return (
                  <div className="t" key={t.key} data-testid="mr5-trigger" title={t.source_id}>
                    <span>{t.label}</span>
                    <span className="v">{t.value}{unit}{t.consider != null ? ` / ${t.consider}${unit} consider` : ''}{t.act != null ? `${t.consider != null ? ' ·' : ' /'} ${t.act}${unit} act` : ''}</span>
                    {f != null && <span className="tbar"><i style={{ width: `${Math.round(f * 100)}%` }} /></span>}
                  </div>
                )
              })}
              {held && <div className="t"><span>Market tier</span><span className="v">{held.held_tier}, held · readings {held.readings_support}</span></div>}
            </div>
            {hedge.gap_to_consider_usd != null && <div className="sub">≈{usd(hedge.gap_to_consider_usd)} more in {(hedge.stressed_labels ?? stressed).join(' / ') || 'stressed'} exposure reaches the consider line.</div>}
            {it && (
              <div className="rc" data-testid="mr5-hedge-pick">
                <div className="h"><b>{it.symbol}</b><span className="amt">if triggered</span></div>
                <div className="sub">{it.stress_led_by?.length ? `Stress is led by ${it.stress_led_by.join(', ')}. ` : ''}{it.proposed_size_usd != null ? `Proposed size: up to half the stressed ${usd(stressedUsd)} (≈${usd(it.proposed_size_usd)}), staged 30/30/40 — proposed, needs your OK.` : ''}{it.others?.length ? ` Also considered: ${it.others.join(', ')}.` : ''}</div>
              </div>
            )}
            <Link className="sub" to="/defense" style={{ color: 'var(--info-color)', fontWeight: 600, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>Defense desk →</Link>
          </div>
        )}

        {panel.rotate && <Rotate r={panel.rotate} stressed={stressed} />}
      </div>

      {pos && (pos.rows ?? []).length > 0 && (
        <>
          <div className="tblw" data-testid="mr5-positions">
            <table className="pos">
              <thead><tr><th>Symbol</th><th>Account</th><th>Value</th><th>% acct</th><th>Stressed</th><th>$ exposed</th>{pos.stops_known && <th>Stop</th>}<th>Stance</th></tr></thead>
              <tbody>
                {(pos.rows ?? []).map((r, i) => (
                  <tr key={`${r.symbol}${r.account_label}${i}`}>
                    <td>{r.symbol}</td><td>{r.account_label ?? ''}</td><td>{usd(r.value_usd)}</td><td>{pct(r.pct_account)}</td>
                    <td>{r.stressed_share != null ? `${Math.round(r.stressed_share * 100)}%` : '—'}</td><td>{usd(r.usd_exposed)}</td>
                    {pos.stops_known && (r.stop_distance_pct != null ? <td>{pct(r.stop_distance_pct)} below</td> : <td className="nostop">no stop</td>)}
                    <td>{r.stance ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="tcap">Book read {day(pos.as_of)} ({pos.source_id}). Stop distance vs the last close.{pos.more_count ? ` +${pos.more_count} more (${usd(pos.more_usd)}).` : ''}{pos.zero_exposure_symbols?.length ? ` ${pos.zero_exposure_symbols.join(', ')} at 0% in stressed groups.` : ''}</div>
        </>
      )}

      {(panel.stopped_out ?? []).length > 0 && (
        <div className="sso" data-testid="mr5-stopped-out">
          <h5>Since you were stopped out</h5>
          <div className="sso-g">
            {(panel.stopped_out ?? []).map((s, i) => (
              <div className="ss" key={`${s.symbol}${i}`} title={s.source_id}>
                <span className="l1">{s.symbol}{s.exit_price != null ? ` · exit ${px(s.exit_price)}` : ''}{s.exit_date ? ` ${day(s.exit_date)}` : ''}{s.account_label ? ` · ${s.account_label}` : ''}
                  {s.verdict && <span className={`badge${/confirm/i.test(s.verdict) ? '' : ' g'}`}>{s.verdict.toUpperCase()}</span>}</span>
                {s.last_close != null && <span className="l2">{s.last_date ? `${day(s.last_date)} close` : 'Close'} {s.last_close.toFixed(2)}{s.pct_vs_exit != null ? <> <span className={s.pct_vs_exit >= 0 ? 'up' : 'dn'}>({pct(s.pct_vs_exit, 1, true)} vs exit)</span></> : null}{s.held_elsewhere?.length ? ` · still held in ${s.held_elsewhere.join(', ')}` : ''}</span>}
                <span className="sub">{s.stage1_met != null && s.stage1_of != null ? `Stage 1: ${s.stage1_met} of ${s.stage1_of} met. ` : ''}{s.waiting_for?.length ? `Waiting for: ${s.waiting_for.join(', ')}. ` : ''}{s.invalidation != null ? `Invalidates below ${s.invalidation.toFixed(2)}.` : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {(notes ?? []).length > 0 && (
        <details className="notes" data-testid="mr5-notes">
          <summary>Who says what ({(notes ?? []).length} notes: where other engines differ)</summary>
          <ol>{(notes ?? []).map(n => <li key={n.topic} title={n.source_id}><b>{n.topic}.</b> {n.text}</li>)}</ol>
        </details>
      )}

      <div className="foot">
        <div className="sub">Advisory. No order, size or stop level is placed from this panel; proposed sizes need your OK.</div>
        {mr && mr.state !== 'not_evaluated' && <MarketRiskAckRow mr={mr} />}
      </div>
    </section>
  )
}
