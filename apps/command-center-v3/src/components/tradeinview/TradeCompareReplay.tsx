import { useState } from 'react'
import TradeReplayChart from '../TradeReplayChart'
import { buildReplayTrade } from '../../lib/replayTrade'

/** Side-by-side win vs loss replay for same setup (P6). */
export default function TradeCompareReplay({ trades, onClose }: { trades: any[]; onClose: () => void }) {
  const [a, setA] = useState<any>(trades.find(t => t.pnl > 0) || trades[0])
  const [b, setB] = useState<any>(trades.find(t => t.pnl < 0) || trades[1])
  const [showA, setShowA] = useState(false)
  const [showB, setShowB] = useState(false)

  const pick = (t: any, side: 'a' | 'b') => {
    if (side === 'a') setA(t); else setB(t)
  }

  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000 }} />
      <div style={{ position: 'fixed', top: '5vh', left: '50%', transform: 'translateX(-50%)', width: 960, maxWidth: '96vw', maxHeight: '90vh', overflow: 'auto', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 12, zIndex: 1001, padding: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <span style={{ fontSize: 14, fontWeight: 700 }}>Compare setups — win vs loss</span>
          <button onClick={onClose} style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}>×</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[{ t: a, side: 'a' as const, label: 'A (pick)' }, { t: b, side: 'b' as const, label: 'B (pick)' }].map(({ t, side, label }) => (
            <div key={side} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 700, marginBottom: 6 }}>{label}: {t?.symbol} {t?.pnl != null ? `$${t.pnl}` : ''}</div>
              <select value={t?.symbol} onChange={e => pick(trades.find(x => x.symbol === e.target.value) || t, side)} style={{ width: '100%', fontSize: 9, marginBottom: 6 }}>
                {trades.map((x, i) => <option key={i} value={x.symbol}>{x.symbol} ${x.pnl}</option>)}
              </select>
              <button onClick={() => (side === 'a' ? setShowA(true) : setShowB(true))} style={{ fontSize: 9, padding: '4px 10px', borderRadius: 4, border: '1px solid var(--border)', cursor: 'pointer' }}>📈 Replay</button>
            </div>
          ))}
        </div>
      </div>
      {showA && a && <TradeReplayChart trade={buildReplayTrade(a)} onClose={() => setShowA(false)} />}
      {showB && b && <TradeReplayChart trade={buildReplayTrade(b)} onClose={() => setShowB(false)} />}
    </>
  )
}