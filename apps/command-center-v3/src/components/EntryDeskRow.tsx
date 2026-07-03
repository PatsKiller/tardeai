import { useState } from 'react'
import { deriveTradeAiRating, ratingLabel } from '../lib/manualTosRating'
import { exitLadder as ladderCalc, planWarnings as warningsCalc, MONITOR_RULES } from '../lib/exitLadder'
import { schwabTicketsFromLadder, ticketsText } from '../lib/schwabTickets'
import EntryDeskDiligenceStrip from './EntryDeskDiligenceStrip'
import type { SetupRow, SourceKind } from '../pages/ManualTosDesk'
import { desk } from '../lib/proposalDeskTheme'

export type TechGrade = {
  technical_grade?: string
  technical_score?: number
  verdict?: string
  action?: string
  narrative_snip?: string
}

type SetupState = 'READY' | 'GENERATED' | 'BROKER_OBSERVED' | 'EXCEPTION'
type AccountSnapshot = { key: string; label: string; cash: number | null; buyingPower: number | null; accountValue: number | null }

const C = { blue: '#60a5fa', green: '#22c55e', amber: '#f59e0b', red: '#ef4444', purple: '#a78bfa', dim: 'var(--text3)' }
const mono = { fontFamily: 'JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, monospace' as const }
const btn = (bg: string, fg = '#fff') => ({ fontSize: 10, fontWeight: 700, padding: '6px 10px', borderRadius: 6, border: 'none', background: bg, color: fg, cursor: 'pointer' as const })
const inputStyle = { fontSize: 10, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' } as const
const metricBox = { background: 'rgba(15,23,42,.48)', border: '1px solid var(--border)', borderRadius: 7, padding: '6px 7px' } as const

function money(v: number | null | undefined) {
  return v == null || !Number.isFinite(Number(v)) ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
}
function pct(v: number | null | undefined) {
  return v == null || !Number.isFinite(Number(v)) ? '—' : `${Number(v).toFixed(2)}%`
}
function acct(a: string) {
  return !a || a === 'ANY' ? 'ANY SCHWAB' : a.replace('schwab_', '').replace(/_/g, ' ').toUpperCase()
}
function analystColor(a: any) {
  const rating = deriveTradeAiRating(a).rating
  return rating === 'STRONG_BUY' ? C.green : rating === 'BUY' ? '#84cc16' : rating === 'HOLD' ? C.amber : rating === 'SELL' || rating === 'STRONG_SELL' ? C.red : C.dim
}
function badgeColor(source: SourceKind) {
  return source === 'PROPOSAL' ? C.green : source === 'WATCHLIST' ? C.blue : C.purple
}
function statusColor(state: SetupState) {
  return state === 'BROKER_OBSERVED' ? C.green : state === 'GENERATED' ? C.blue : state === 'EXCEPTION' ? C.red : C.dim
}
function decisionText(r: SetupRow) {
  const d = String(r.decision ?? '').toUpperCase()
  if (d === 'GO' || d === 'WAIT') return d
  return r.source === 'WATCHLIST' ? 'WATCHLIST ADVISORY' : 'DECISION PENDING'
}
function setupLine(r: SetupRow) {
  const price = r.entryPrice != null ? ` ${r.entryPrice.toFixed(2)}` : ''
  const exits = [
    r.stop != null ? `STOP ${r.stop.toFixed(2)}` : null,
    r.trail ? `TRAIL ${r.trail.offset}` : null,
    ...r.targets.map((t: any, i: number) => `TARGET${i + 1} ${Number(t.price).toFixed(2)}`),
  ].filter(Boolean).join(' | ')
  return `${r.side} ${r.qty} ${r.symbol} ${r.entryType}${price} ${r.tif}${exits ? ` | ${exits}` : ''}`
}
function sizing(r: SetupRow, account: AccountSnapshot | null) {
  const notional = r.entryPrice ? r.entryPrice * r.qty : null
  const cashBase = account?.cash ?? account?.buyingPower ?? null
  const acctBase = account?.accountValue ?? null
  const risk = r.entryPrice && r.stop && r.entryPrice > r.stop ? (r.entryPrice - r.stop) * r.qty : null
  const targetPrice = r.targets?.[0]?.price ? Number(r.targets[0].price) : null
  const reward = r.entryPrice && targetPrice && targetPrice > r.entryPrice ? (targetPrice - r.entryPrice) * r.qty : null
  const rr = risk && reward ? reward / risk : null
  return { notional, pctCash: notional && cashBase ? notional / cashBase * 100 : null, pctAccount: notional && acctBase ? notional / acctBase * 100 : null, risk, rr }
}
function techAccent(grade?: string) {
  const g = String(grade || '').toUpperCase()
  if (g.includes('STRONG')) return desk.green
  if (g.includes('_OK')) return desk.teal
  if (g.includes('MIXED')) return desk.amber
  if (g.includes('WEAK') || g.includes('INCOMPLETE')) return desk.red
  return C.dim
}
function techShort(grade?: string) {
  return String(grade || 'TECH_…').replace('TECH_', '')
}

type Props = {
  r: SetupRow
  state: SetupState
  hit: any
  account: AccountSnapshot | null
  streetTarget: number | null
  tech?: TechGrade | null
  accounts: string[]
  accountMap: Record<string, AccountSnapshot>
  onSetField: (id: string, patch: { account?: string; qty?: number; generated?: boolean }) => void
  onCopyMsg: (s: string) => void
  onPromote: (r: SetupRow, proposalId?: number) => void
  promoteBusy?: boolean
  focused?: boolean
}

export default function EntryDeskRow({
  r, state, hit, account, streetTarget, tech, accounts, accountMap, onSetField, onCopyMsg, onPromote, promoteBusy, focused,
}: Props) {
  const rating = deriveTradeAiRating(r)
  const sz = sizing(r, account)
  const ladder = ladderCalc(r.entryPrice, r.stop, r.targets?.[0]?.price ? Number(r.targets[0].price) : null, streetTarget)
  const warns = warningsCalc({
    entry: r.entryPrice, stop: r.stop,
    planTarget: r.targets?.[0]?.price ? Number(r.targets[0].price) : null,
    rr: sz.rr, pctCash: sz.pctCash, streetTarget,
    analystUpside: r.analystUpside != null ? Number(r.analystUpside) : null,
  })
  const [ackOpen, setAckOpen] = useState(false)
  const [ackTicker, setAckTicker] = useState('')
  const [ackBusy, setAckBusy] = useState(false)
  const [ackMsg, setAckMsg] = useState('')
  const [pendingKind, setPendingKind] = useState<'setup' | 'schwab_tickets'>('setup')

  const doCopy = (text: string, kind: 'setup' | 'schwab_tickets') => {
    const done = () => {
      onSetField(r.id, { generated: true })
      setPendingKind(kind)
      setAckOpen(true)
      setAckTicker('')
      setAckMsg('')
      onCopyMsg('copied — confirm below')
    }
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
    else done()
  }

  const submitAck = async () => {
    setAckBusy(true)
    setAckMsg('')
    try {
      const res = await fetch('/api/v2/entry-desk/ack-copy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: r.symbol,
          confirm_ticker: ackTicker,
          kind: pendingKind,
          setup_line: setupLine(r),
        }),
      }).then(x => x.json())
      if (res.ok) {
        setAckMsg('✓ 2FA ack logged')
        setTimeout(() => setAckOpen(false), 1400)
      } else {
        setAckMsg(res.error || 'ack failed')
      }
    } catch {
      setAckMsg('ack failed')
    } finally {
      setAckBusy(false)
    }
  }

  const canPromote = r.source !== 'DRAFT' && r.entryPrice && r.stop && r.targets?.[0]?.price

  return (
    <div
      data-testid="entry-desk-row"
      style={{
        border: focused
          ? `2px solid ${C.blue}`
          : `1px solid ${state === 'BROKER_OBSERVED' ? C.green : state === 'EXCEPTION' ? C.red : 'var(--border)'}`,
        borderRadius: 10,
        background: focused ? 'rgba(96,165,250,.06)' : 'var(--bg1)',
        padding: 13, marginBottom: 10,
        boxShadow: focused ? '0 0 0 1px rgba(96,165,250,.25)' : undefined,
      }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.35fr) minmax(0,1fr) auto', gap: 12, alignItems: 'start' }}>
        <div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 9, color: badgeColor(r.source), fontWeight: 900 }}>{r.source}</span>
            <span style={{ fontSize: 17, fontWeight: 900, ...mono }}>{r.symbol}</span>
            {r.company && <span style={{ fontSize: 10, color: C.dim }}>{r.company}</span>}
            <span style={{ fontSize: 9, color: statusColor(state), background: `${statusColor(state)}22`, padding: '2px 7px', borderRadius: 4 }}>
              {state === 'BROKER_OBSERVED' ? 'AUTO-LINKED FROM SCHWAB READ-ONLY' : state}
            </span>
            {tech?.technical_grade && (
              <span
                title={tech.narrative_snip || tech.action || ''}
                style={{
                  fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
                  color: techAccent(tech.technical_grade),
                  background: `${techAccent(tech.technical_grade)}18`,
                  border: `1px solid ${techAccent(tech.technical_grade)}33`,
                }}
              >
                TECH {techShort(tech.technical_grade)}{tech.technical_score != null ? ` ${tech.technical_score}` : ''}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginTop: 6, fontSize: 9 }}>
            <span style={{ color: C.amber }}>{decisionText(r)}</span>
            <span style={{ color: analystColor(r) }}>
              {rating.source === 'analyst' ? 'analyst' : 'Trade AI rating'} {ratingLabel(rating.rating)}
            </span>
            {r.analystCount != null && <span style={{ color: C.dim }}>{r.analystCount} analysts</span>}
            {r.analystUpside != null && (
              <span style={{ color: Number(r.analystUpside) >= 0 ? C.green : C.red }}>
                {Number(r.analystUpside) >= 0 ? '+' : ''}{r.analystUpside}%
              </span>
            )}
            <span style={{ color: C.blue }}>score {r.score != null ? String(r.score) : 'n/a'}</span>
            {r.sector && <span style={{ color: C.dim }}>{r.sector}</span>}
          </div>
          {r.reason && <div style={{ marginTop: 4, fontSize: 9, color: C.dim, lineHeight: 1.4 }}>{String(r.reason).slice(0, 200)}</div>}
          <div style={{ marginTop: 8, fontSize: 12, fontWeight: 800, ...mono }}>{setupLine(r)}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 7, fontSize: 9 }}>
            {r.entryPrice != null && <span>entry {r.entryType} {r.entryPrice.toFixed(2)}</span>}
            {r.stop != null && <span style={{ color: C.red }}>stop {r.stop.toFixed(2)}</span>}
            {r.targets.map((t: any, i: number) => (
              <span key={i} style={{ color: C.green }}>target {i + 1}: {Number(t.price).toFixed(2)}</span>
            ))}
          </div>
          {warns.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 7 }}>
              {warns.map((w, i) => <div key={i} style={{ fontSize: 9, color: w.color, fontWeight: 700 }}>⚠ {w.text}</div>)}
            </div>
          )}
          {ladder && (
            <div style={{ marginTop: 7, background: 'rgba(15,23,42,.48)', border: '1px solid var(--border)', borderRadius: 7, padding: '6px 8px' }}>
              <div style={{ fontSize: 8, color: C.dim, fontWeight: 900, textTransform: 'uppercase' }}>
                Exit ladder (advisory) · R = ${ladder.R.toFixed(2)}/sh
              </div>
              {ladder.steps.map((s, i) => (
                <div key={i} style={{ fontSize: 9.5, marginTop: 2 }}>
                  <span style={{ color: C.green, fontWeight: 800, ...mono }}>{s.label} {s.px.toFixed(2)}</span>
                  <span style={{ color: C.dim }}> — {s.action}</span>
                </div>
              ))}
              <div style={{ fontSize: 8.5, color: C.dim, marginTop: 4 }}>In-trade: {MONITOR_RULES}</div>
            </div>
          )}
          {hit ? (
            <div style={{ marginTop: 7, fontSize: 10, color: C.green }}>
              Observed {acct(hit.account_key)} · {hit.kind ?? 'activity'} · {String(hit.captured_at ?? '').slice(0, 16)}
            </div>
          ) : (
            <div style={{ marginTop: 7, fontSize: 10, color: C.dim }}>No matching Schwab activity observed yet.</div>
          )}
          <EntryDeskDiligenceStrip source={r.source} symbol={r.symbol} diligence={r.diligence} analystRating={ratingLabel(rating.rating)} />
          {tech?.action && (
            <div style={{ marginTop: 6, fontSize: 9, color: desk.textMuted, lineHeight: 1.4 }}>
              <span style={{ fontWeight: 800, color: techAccent(tech.technical_grade) }}>Tech action · </span>
              {tech.action}
            </div>
          )}
        </div>

        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px', gap: 8, marginBottom: 7 }}>
            <select value={r.account} onChange={e => onSetField(r.id, { account: e.target.value })} style={inputStyle}>
              {['ANY', ...accounts.filter(a => a !== 'ANY')].filter((v, i, arr) => arr.indexOf(v) === i).map(a => (
                <option key={a} value={a}>{acct(a)}</option>
              ))}
            </select>
            <input
              value={r.qty}
              onChange={e => onSetField(r.id, { qty: Number(e.target.value) || 1 })}
              style={inputStyle}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>Cash/BP</div><div style={{ fontSize: 11, fontWeight: 800 }}>{account ? money(account.cash ?? account.buyingPower) : 'select account'}</div></div>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>Notional</div><div style={{ fontSize: 11, fontWeight: 800 }}>{money(sz.notional)}</div></div>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>% Cash</div><div style={{ fontSize: 11, fontWeight: 800, color: sz.pctCash && sz.pctCash > 10 ? C.amber : 'var(--text0)' }}>{pct(sz.pctCash)}</div></div>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>Acct Value</div><div style={{ fontSize: 11, fontWeight: 800 }}>{account ? money(account.accountValue) : '—'}</div></div>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>% Account</div><div style={{ fontSize: 11, fontWeight: 800 }}>{pct(sz.pctAccount)}</div></div>
            <div style={metricBox}><div style={{ fontSize: 8, color: C.dim }}>Risk / R:R</div><div style={{ fontSize: 11, fontWeight: 800, color: sz.rr && sz.rr >= 2 ? C.green : C.amber }}>{money(sz.risk)} / {sz.rr ? sz.rr.toFixed(2) : '—'}</div></div>
          </div>
          <div style={{ marginTop: 6, fontSize: 9, color: C.dim }}>Sizing is read-only — does not place orders.</div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end', minWidth: 148 }}>
          <button onClick={() => doCopy(setupLine(r), 'setup')} style={btn('#1d4ed8')}>Copy setup</button>
          <button
            title="Copy Schwab ticket drafts — no API submit"
            onClick={() => {
              const tk = schwabTicketsFromLadder({ symbol: r.symbol, qty: r.qty, entry: r.entryPrice, stop: r.stop, ladder })
              if (tk.length) doCopy(ticketsText(tk), 'schwab_tickets')
            }}
            style={btn('#0e7490')}
          >
            Copy Schwab tickets
          </button>
          {canPromote && (
            <button
              disabled={promoteBusy}
              onClick={() => onPromote(r)}
              style={btn(promoteBusy ? '#334155' : '#15803d')}
              title="Queue to broker proposals — Stage 2b + Auto route (2FA) on Proposals tab"
            >
              {promoteBusy ? '…' : '→ Broker queue'}
            </button>
          )}
        </div>
      </div>

      {ackOpen && (
        <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 8, background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.25)' }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: C.green, marginBottom: 6 }}>
            2FA copy ack — type ticker to confirm manual ToS entry (audit only, no Schwab submit)
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={ackTicker}
              onChange={e => setAckTicker(e.target.value.toUpperCase())}
              placeholder={`ticker ${r.symbol}`}
              style={{ ...inputStyle, width: 88 }}
            />
            <button
              onClick={submitAck}
              disabled={ackBusy || ackTicker.trim().toUpperCase() !== r.symbol}
              style={btn(ackTicker.trim().toUpperCase() === r.symbol ? C.green : '#334155', '#0b1020')}
            >
              {ackBusy ? '…' : 'Ack copy ✓'}
            </button>
            <button onClick={() => setAckOpen(false)} style={btn('#334155')}>dismiss</button>
            {ackMsg && <span style={{ fontSize: 9, color: ackMsg.startsWith('✓') ? C.green : C.amber }}>{ackMsg}</span>}
          </div>
        </div>
      )}
    </div>
  )
}