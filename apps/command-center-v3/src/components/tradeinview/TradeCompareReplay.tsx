import { useEffect, useRef, useState } from 'react'
import TradeReplayChart from '../TradeReplayChart'
import { useApi } from '../../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle } from '../../lib/designTokens'
import { buildReplayTrade } from '../../lib/replayTrade'
import { replayPayload, responseReason, serverMoney, storedReplayPath } from '../../lib/tradeInViewModel'

/** Compare recorded trade identities. The new page never falls through to provider chart fetching. */
export default function TradeCompareReplay({ trades, onClose, storedOnly = false, initialTradeId }: { trades: any[]; onClose: () => void; storedOnly?: boolean; initialTradeId?: string }) {
  const dialog = useRef<HTMLDivElement>(null), close = useRef<HTMLButtonElement>(null), closeAction = useRef(onClose)
  closeAction.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    close.current?.focus()
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeAction.current(); return }
      if (e.key !== 'Tab') return
      const targets = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select:not(:disabled),input:not(:disabled),a[href]') || []).filter(el => el.getBoundingClientRect().height > 0)
      const first = targets[0], last = targets[targets.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
    }
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('keydown', key); previous?.focus() }
  }, [])
  const identity = (t: any, i: number) => String(t?.trade_id || t?.trade_key || `legacy-row-${i}`)
  const current = trades.find(t => t.trade_id === initialTradeId)
  const [a, setA] = useState<any>(storedOnly ? current || trades[0] : trades.find(t => t.pnl > 0) || trades[0])
  const [b, setB] = useState<any>(storedOnly ? trades.find(t => t.trade_id !== current?.trade_id && t.pnl > 0) : trades.find(t => t.pnl < 0) || trades[1])
  const [showA, setShowA] = useState(false), [showB, setShowB] = useState(false)
  return <div ref={dialog} role="dialog" aria-modal="true" aria-label="Compare recorded trades" className="tradeinview-compare" data-testid="trade-compare" style={{ position: 'fixed', inset: '4vh 2vw', zIndex: 1001, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: 16, overflowY: 'auto', color: TOKENS.text[0] }}>
    <div className="tradeinview-heading"><h2 style={{ margin: 0, fontSize: TYPE.lg }}>Compare with a win</h2><button ref={close} type="button" aria-label="Close comparison" onClick={onClose} style={{ ...chipStyle('neutral', 'outline', 'md'), cursor: 'pointer' }}>Close</button></div>
    <div className="tradeinview-compare-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginTop: 12 }}>
      {[{ t: a, side: 'a', label: storedOnly ? 'Selected trade' : 'A (pick)', show: showA }, { t: storedOnly && a?.trade_id === b?.trade_id ? null : b, side: 'b', label: storedOnly ? 'Winning trade' : 'B (pick)', show: showB }].map(({ t, side, label, show }) => <section key={side} style={{ minWidth: 0, padding: 12, background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>
        <label style={{ fontSize: TYPE.base }}>{label}<select aria-label={label} value={t ? identity(t, trades.indexOf(t)) : ''} onChange={e => { const chosen = trades.find((x, i) => identity(x, i) === e.target.value); if (side === 'a') setA(chosen); else setB(chosen) }} style={{ width: '100%', margin: '8px 0', background: TOKENS.bg[2], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, padding: 8, fontSize: TYPE.base }}>
          {!t && <option value="">Recorded comparison trade unavailable</option>}{trades.filter(x => !storedOnly || side !== 'b' || x.pnl > 0 && x.trade_id !== a?.trade_id).map((x) => <option key={identity(x, trades.indexOf(x))} value={identity(x, trades.indexOf(x))}>{x.symbol} · {x.account_label || 'Unlabelled account'} · {x.entry_date || 'entry date unavailable'} → {x.exit_date || 'open'} · {serverMoney(x.pnl)}</option>)}
        </select></label>
        {t ? <><div style={{ fontFamily: FONT.mono, fontSize: TYPE.base }}>{t.symbol} · {serverMoney(t.pnl)}</div>{storedOnly ? <StoredChart key={t.trade_id} trade={t} /> : <><button type="button" style={{ ...chipStyle('info', 'soft', 'md'), marginTop: 8 }} onClick={() => side === 'a' ? setShowA(true) : setShowB(true)}>Replay</button>{show && <TradeReplayChart trade={buildReplayTrade(t)} onClose={() => side === 'a' ? setShowA(false) : setShowB(false)} />}</>}</> : <p className="tradeinview-gap">No stored trade satisfies this comparison.</p>}
      </section>)}
    </div>
  </div>
}
function StoredChart({ trade }: { trade: any }) {
  const api = useApi<any>(storedReplayPath(trade.trade_id || '', '1D'), undefined, { enabled: !!trade.trade_id })
  const data = replayPayload(api.data, { trade_id: trade.trade_id || '', interval: '1D' })
  if (!trade.trade_id) return <p className="tradeinview-gap">Recorded trade identity unavailable; no chart request made.</p>
  if (!data) return <p className="tradeinview-gap">{api.loading ? 'Loading stored comparison…' : `Stored comparison unavailable — ${api.error || responseReason(api.data) || 'response schema unavailable'}`}</p>
  return <><TradeReplayChart key={trade.trade_id} trade={buildReplayTrade(trade)} embedded providedData={data} onClose={() => {}} /><p className="tradeinview-gap" style={{ fontSize: TYPE.sm }}>{data.source.table || 'Source unavailable'} · {data.source.bar_basis} · {data.stats.metrics_missing_reason || data.stats.metrics_basis}</p>{data.gaps.map((g, i) => <div key={i} className="tradeinview-gap" style={{ fontSize: TYPE.sm }}>{g.source}: {g.reason}</div>)}</>
}
