/** LQ-20261107-1352 — the Home CIO card, design v5 (operator-approved 2026-11-08: "version 5 is approved").
 *  Reads the HomeCioCard@v1 projection (GET /api/v2/home/cio-card) through the caller. Every number is the server's and
 *  carries source_id + as_of; anything the server dropped as untraceable is simply not drawn. The CIO's stop advice
 *  (with its per-viewer Done boxes) is passed in as `actions` — the existing SinceCloseStops list, restyled here.
 *  Advisory only (MBI_BEHAVIOR = 0): no control here places, sizes or moves an order or a stop. */
import { useState, type CSSProperties, type ReactNode } from 'react'
import '../../styles/cioCard.css'
import { toneVars } from '../../lib/designTokens'
import { actionVerb, accountText, calDay, daysUntil, etDay, etTime, fv, meterParts, usd, usdShort, tierToneOf, type CioCard } from '../../lib/cioCard'

/** "DEFENSIVE — HOLD CASH" → "Hold cash." (the part after the dash, sentence case). */
function postureLine(p: string | undefined): string | null {
  if (!p) return null
  const tail = (p.split(/\s+[—–-]\s+/).pop() ?? p).trim().toLowerCase()
  if (!tail) return null
  return tail[0].toUpperCase() + tail.slice(1) + (/[.!?]$/.test(tail) ? '' : '.')
}

const short = (iso: string | undefined) => (iso ? `${etDay(iso)} ${etTime(iso).replace(/^\w+ /, '')}` : '')

export function tierStyle(tier: string | undefined): CSSProperties {
  const t = toneVars(tierToneOf(tier))
  return { '--t': t.color, '--t-bg': t.bg, '--t-line': t.border } as CSSProperties
}

export default function CioCardV5({ card, adviceOk, adviceReason, nowMs, actions }: {
  card: CioCard; adviceOk: boolean; adviceReason?: string | null; nowMs: number; actions?: ReactNode
}) {
  const [why, setWhy] = useState(false)
  const tier = fv(card.tier)
  const score = fv(card.score)
  const gate = fv(card.buys_gate)
  const until = fv(card.buys_until)
  const untilShort = fv(card.buys_until_short)
  const stopsN = fv(card.stops_actionable)
  const stopsOf = fv(card.stops_total)
  const lu = card.largest_unprotected
  const head = postureLine(fv(card.posture))
  const noBuys = gate && String(gate).toUpperCase() === 'NONE'
  const drivers = card.drivers ?? []
  const parts = meterParts(drivers)
  const sum = fv(card.score_sum)
  const cat = card.catalyst
  const tMinus = cat ? daysUntil(cat.date, nowMs) : null
  const held = card.held
  const sectors = card.sectors
  const doNow = card.do_now
  const scrollToActs = () => { try { document.getElementById('cio5-acts')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) } catch { /* no DOM */ } }

  return (
    <article className="cio5" data-testid="cio-card-v5" data-tier={tier} aria-label={`CIO card: market tier ${tier}`} style={tierStyle(tier)}>
      <div className="band">
        <div className="band-top">
          <span className="tier" data-testid="cio5-tier"><span className="dot" aria-hidden="true" />{tier}</span>
          {score != null && <span className="score" data-testid="cio5-score">risk {score.toFixed(1)}</span>}
          <span className="asof" title={card.tier?.source_id}>{short(card.tier?.as_of)}</span>
        </div>
        {(head || (noBuys && untilShort)) && (
          <h3 className="headline" data-testid="cio5-headline">
            {head}{noBuys && untilShort ? <> <em>No buys before {untilShort}.</em></> : null}
            {stopsN ? <span className="desk-only-inline"> {stopsN} stop{stopsN === 1 ? '' : 's'} need a decision.</span> : null}
          </h3>
        )}
        <div className="chips">
          {gate && (
            <div className={`chip ${noBuys ? 'cr' : 'b'}`} data-testid="cio5-chip-buys" title={card.buys_gate?.source_id}>
              <div className="k">Buys</div><div className="v">{gate}</div>{until && <div className="s">until {until}</div>}
            </div>
          )}
          {stopsN != null && (
            <div className={`chip ${stopsN > 0 ? 'a' : ''}`} data-testid="cio5-chip-stops" title={card.stops_actionable?.source_id}>
              <div className="k">Stops</div><div className="v">{stopsN} to decide</div>{stopsOf != null && <div className="s">of {stopsOf} stop items</div>}
            </div>
          )}
          {lu && (
            <div className="chip a" data-testid="cio5-chip-unprotected" title={lu.source_id}>
              <div className="k">Unprotected</div><div className="v num">{lu.value != null ? usdShort(lu.value) : lu.symbol}</div>
              <div className="s">{lu.symbol}{lu.shares != null ? ` ${Math.round(lu.shares)} sh` : ''}{lu.account ? ` · ${accountText(lu.account)}` : ''}</div>
            </div>
          )}
          {card.reentry && card.reentry.ready != null && (
            <div className="chip b desk-only" data-testid="cio5-chip-reentry" title={card.reentry.source_id}>
              <div className="k">Re-entry</div><div className="v">{card.reentry.ready} ready</div>
              {card.reentry.near != null && <div className="s">{card.reentry.near} near entry{card.reentry.tracked != null ? ` of ${card.reentry.tracked}` : ''}</div>}
            </div>
          )}
        </div>
      </div>

      {(drivers.length > 0 || cat || held || card.calm || (card.gaps ?? []).length > 0) && (
        <div className="drv" data-testid="cio5-drivers">
          <div className="drv-h">
            <h4>What's driving {head ? `"${head.replace(/\.$/, '').toLowerCase()}"` : `${tier}`}</h4>
            <span className="src">market_risk · as of {short(card.score?.as_of)}{sum != null && drivers.length ? ` · score ${sum.toFixed(1)} = ${drivers.filter(d => (d.points ?? 0) > 0).map(d => (d.points ?? 0).toFixed(1)).join(' + ')}` : ''}</span>
          </div>
          {parts.length > 0 && (
            <>
              <div className="meter" role="img" aria-label={`Risk score ${score?.toFixed(1) ?? '—'}: ${drivers.map(d => `${d.name} ${(d.points ?? 0).toFixed(1)}`).join(', ')}`}>
                {parts.map(p => <i key={p.name} style={{ width: `${p.width}%` }} />)}
              </div>
              <div className="meter-k"><span>0</span><span>{tier} {score?.toFixed(1)}</span><span>100</span></div>
            </>
          )}
          <div className="drv-g">
            {drivers.map(d => (
              <div className="d" key={d.name} data-testid="cio5-driver" title={d.source_id}>
                <span className="n">{d.name}{d.state && <span className="st s">{d.state}</span>}</span>
                <span className="pts">+{(d.points ?? 0).toFixed(1)}</span>
                {d.detail && <span className="det">{d.detail}{d.as_of ? ` (${short(d.as_of)})` : ''}</span>}
              </div>
            ))}
            {cat && (
              <div className="d next" data-testid="cio5-catalyst" title={cat.source_id}>
                <span className="n">Next catalyst: {cat.label}</span>
                <span className="pts" style={{ color: 'var(--text-0)' }}>{tMinus != null && tMinus >= 0 ? `T−${tMinus}d` : ''}</span>
                <span className="det">The next scheduled print that can move the tier.{noBuys ? ' No buys until it prints.' : ''}</span>
              </div>
            )}
            {held && (
              <div className="d hold" data-testid="cio5-held" title={held.source_id}>
                <span className="n">Why still {held.held_tier}</span>
                <span className="pts" style={{ color: 'var(--warning-color)' }}>held</span>
                <span className="det">Today's readings alone support <b>{held.readings_support}</b>. {held.held_tier} is held by the completed-session rule ({held.sessions_recorded} of {held.sessions_needed} sessions recorded).</span>
              </div>
            )}
            {card.calm && (
              <div className="d calm" data-testid="cio5-calm" title={card.calm.source_id}>
                <span className="n">{card.calm.n} of {card.calm.of} categories calm<span className="st c">CALM</span></span>
                <span className="pts" style={{ color: 'var(--text-2)' }}>0</span>
                {(card.calm.names ?? []).length > 0 && <span className="det">{(card.calm.names ?? []).join(' · ')}</span>}
              </div>
            )}
            {(card.gaps ?? []).map(g => (
              <div className="d calm" key={g.name} data-testid="cio5-gap" title={g.source_id}>
                <span className="n">Not measured: {g.name}<span className="st nm">GAP</span></span>
                <span className="pts" style={{ color: 'var(--text-2)' }}>—</span>
                {g.detail && <span className="det">{g.detail}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {!adviceOk && (
        <div className="advice-off" role="status" data-testid="cio5-advice-off">Do-now advice is paused: {adviceReason || 'an input is not current'}. The tier and drivers above carry their own times.</div>
      )}

      {adviceOk && doNow && (
        <div className="action" data-testid="cio5-do-now" title={doNow.source_id}>
          <div className="k">Do now{doNow.n && doNow.of ? ` · ${doNow.n} of ${doNow.of}` : ''}</div>
          <div className="what">{doNow.symbol}{doNow.account ? `, ${accountText(doNow.account)}` : ''}: {actionVerb(doNow).toLowerCase()}{doNow.suggested_stop != null ? <> to <b>{doNow.suggested_stop.toFixed(2)}</b></> : null}</div>
          {why && doNow.reason && <div style={{ fontSize: 13, color: 'var(--text-1)' }}>{doNow.reason}</div>}
          <div className="row">
            <button className="btn" type="button" onClick={scrollToActs} data-testid="cio5-review">Review {doNow.of ?? stopsN ?? ''} stop decision{(doNow.of ?? stopsN) === 1 ? '' : 's'}</button>
            {doNow.reason && <button className="btn ghost" type="button" aria-expanded={why} onClick={() => setWhy(!why)}>{why ? 'Hide why' : 'Why'}</button>}
          </div>
        </div>
      )}

      <div className="rows">
        {card.buys_line && (
          <div className="r" data-testid="cio5-row-buys"><span className={`bar ${noBuys ? 'red' : 'blu'}`} /><span className="lab">Buys</span>
            <div className="txt"><div className="main">{fv(card.buys_line)}</div></div></div>
        )}
        {(tier || sectors) && (
          <div className="r" data-testid="cio5-row-market"><span className="bar red" /><span className="lab">Market</span>
            <div className="txt">
              <div className="main">Tier <span className="tagr">{tier}</span>{fv(card.shock) ? ` · ${String(fv(card.shock)).toLowerCase()} shock` : ''}{sectors?.stressed?.length ? `: ${sectors.stressed.join(' / ')}` : ''}</div>
              {sectors && sectors.measured != null && (
                <div className="sub">{sectors.stressed_sectors != null ? `${sectors.stressed_sectors} of ${sectors.measured} sectors stressed` : ''}{sectors.down_5d != null ? ` · ${sectors.down_5d} of ${sectors.measured} down over 5 sessions` : ''}{sectors.resilient?.length ? ` · holding up: ${sectors.resilient.join(', ').toLowerCase()}` : ''}</div>
              )}
            </div></div>
        )}
        {card.book && (
          <div className="r" data-testid="cio5-row-book" title={card.book.source_id}><span className="bar amb" /><span className="lab">Book</span>
            <div className="txt">
              <div className="main">{card.book.positions != null && <><span className="num">{card.book.positions}</span> positions</>}{card.book.accounts != null && <> · <span className="num">{card.book.accounts}</span> accounts</>}{card.book.cash != null && <> · <span className="num">{usd(card.book.cash)}</span> cash</>}</div>
              {lu && <div className="sub">Largest unprotected: <span className="taga">{lu.symbol}{lu.shares != null ? ` ${Math.round(lu.shares)} sh` : ''}{lu.value != null ? ` (~${usd(lu.value)})` : ''}</span>{lu.account ? `, ${accountText(lu.account)}` : ''}.</div>}
            </div></div>
        )}
        {card.reentry && (
          <div className="r" data-testid="cio5-row-reentry" title={card.reentry.source_id}><span className="bar blu" /><span className="lab">Re-entry</span>
            <div className="txt">
              <div className="main"><span className="num">{card.reentry.near ?? '—'}</span> near entry · <span className="num">{card.reentry.ready ?? '—'}</span> ready of <span className="num">{card.reentry.tracked ?? '—'}</span></div>
              {card.reentry.line && card.reentry.line.includes(':') && <div className="sub">Review open, not a buy call: {card.reentry.line.split(':').slice(1).join(':').trim()}</div>}
            </div></div>
        )}
        {(card.this_week ?? []).length > 0 && (
          <div className="r" data-testid="cio5-row-week"><span className="bar" /><span className="lab">This week</span>
            <div className="txt"><div className="cal">
              {(card.this_week ?? []).map((e, i) => (
                <span key={`${e.date}${e.label}${i}`} className={`ev${e.held ? ' held' : ''}${cat && e.kind === 'macro' && e.date === cat.date && e.label === cat.event ? ' hot' : ''}`} title={e.source_id}>
                  <b>{calDay(e.date).split(' ')[0]}{e.time_et ? ` ${e.time_et}` : ''}</b> {e.label}
                </span>
              ))}
            </div></div></div>
        )}
      </div>

      {actions && (
        <div className="acts" id="cio5-acts" data-testid="cio5-actions">
          {actions}
        </div>
      )}
    </article>
  )
}
