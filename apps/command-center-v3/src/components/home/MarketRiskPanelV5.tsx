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
  if (c.leadership === 'LEADERSHIP_CONFIRMED') return <span className="st lead">LEADING · CONFIRMED</span>
  if (c.state === 'RESILIENT') return <span className="st res">RESILIENT</span>
  return <span className="st neu">{c.state ?? '—'}</span>
}

function Rotate({ r, stressed }: { r: NonNullable<CioPanel['rotate']>; stressed: string[] }) {
  const cands = r.candidates ?? []
  const plan = r.plan
  const closeAsOf = cands.find(c => c.close)?.close?.as_of
  return (
    <div className="col" data-testid="mr5-rotate">
      <h5>Rotate · defensives</h5>
      <p>{stressed.length ? `Stress is in ${stressed.join(' / ')}. ` : ''}{cands.filter(c => c.qualifies).length
        ? `${cands.filter(c => c.qualifies).map(c => c.label).join(' and ')} qualify on the market-risk sector table.`
        : 'No defensive group qualifies on the market-risk sector table yet.'}</p>
      <div className="rk">
        {cands.map(c => {
          const p = c.proposed
          const close = fv(c.close), avg = fv(c.avg20)
          return (
            <div className={`rc${c.qualifies ? '' : ' off'}`} key={c.symbol} data-testid="mr5-rotate-row" title={c.source_id}>
              <div className="h"><b>{c.symbol}</b><span className="nm">{c.label}</span>{stateBadge(c)}
                <span className="amt">{c.qualifies && p?.tranche1_usd ? `${usd(p.tranche1_usd)} tranche 1` : 'watch'}</span></div>
              <div className="sub">{c.rs20 != null ? `RS vs SPY ${c.rs20 > 0 ? '+' : ''}${c.rs20.toFixed(1)} pts over 20 sessions` : ''}{c.dd20 != null ? ` · ${pct(Math.abs(c.dd20))} off its 20-day high` : ''}{c.qualifies ? '' : ' · starts when it turns RESILIENT'}</div>
              {(close != null || p) && (
                <div className="ln">{close != null ? `Close ${close.toFixed(2)}` : ''}{avg != null ? ` · 20-day avg ${avg.toFixed(2)}` : ''}
                  {c.qualifies && p?.shares ? ` · ≈${p.shares} sh for tranche 1` : ''}
                  {p?.target_pct != null ? ` · target ${p.target_pct}% of book${p.target_usd != null ? ` (${usdShort(p.target_usd)})` : ''}${c.qualifies ? '' : ' when it qualifies'}` : ''}</div>
              )}
            </div>
          )
        })}
      </div>
      {plan && (
        <>
          <div><span className="pill prop" data-testid="mr5-proposed">PROPOSED · NEEDS YOUR OK</span></div>
          <div className="tot" data-testid="mr5-plan">
            {plan.tranche1_usd != null && <><span>Tranche 1 ({Math.round((plan.split?.[0] ?? 0.3) * 100)}%)</span><span>{usd(plan.tranche1_usd)}{plan.tranche1_pct_book != null ? ` · ${pct(plan.tranche1_pct_book)} of book` : ''}</span></>}
            {plan.tranche2_after && <><span>Tranche 2 ({Math.round((plan.split?.[1] ?? 0.3) * 100)}%)</span><span>after {plan.tranche2_after}</span></>}
            {plan.tranche3_when && <><span>Tranche 3 ({Math.round((plan.split?.[2] ?? 0.4) * 100)}%)</span><span>when {plan.tranche3_when}</span></>}
            {plan.cash_after_pct != null && <><span>Cash after tranche 1</span><span>{pct(plan.cash_after_pct)}</span></>}
          </div>
          {plan.rule && <div className="sub">Proposed rule: {plan.rule}.</div>}
        </>
      )}
      <div className="sub">Advisory only: no order is placed.{closeAsOf ? ` Prices: ${day(closeAsOf)} daily close.` : ''} State: market-risk sector table ({day(r.as_of)}).</div>
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
