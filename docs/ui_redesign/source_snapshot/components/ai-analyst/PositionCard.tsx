import { useNavigate } from 'react-router-dom'
import { useToast } from '../ToastProvider'

interface PositionCardProps {
  symbol: string
  name: string
  allocation: string
  recommendation: string
  rationale: string
  selected?: boolean
  onSelect: () => void
}

export default function PositionCard({ symbol, name, allocation, recommendation, rationale, selected, onSelect }: PositionCardProps) {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const rec = recommendation.toUpperCase()
  const isHighRisk = rec.includes('TRIM') || rec.includes('SELL') || rec.includes('REDUCE')

  return (
    <div onClick={onSelect} style={{
      background: selected ? 'rgba(74,144,244,0.08)' : 'rgba(22,26,34,0.95)',
      border: `1px solid ${selected ? 'var(--accent)' : isHighRisk ? 'rgba(246,70,93,0.4)' : 'rgba(255,255,255,0.07)'}`,
      borderRadius: 12, padding: 20, cursor: 'pointer', transition: 'all 0.12s',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{symbol}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{name} · {allocation}</div>
        </div>
        <div style={{ padding: '4px 14px', borderRadius: 9999, fontSize: 11, fontWeight: 700,
          background: isHighRisk ? 'rgba(246,70,93,0.15)' : rec === 'ADD' ? 'rgba(14,203,129,0.15)' : 'rgba(74,144,244,0.15)',
          color: isHighRisk ? 'var(--red)' : rec === 'ADD' ? 'var(--green)' : 'var(--accent)',
        }}>{recommendation}</div>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.55, marginBottom: 16, display: '-webkit-box', WebkitLineClamp: 4, WebkitBoxOrient: 'vertical', overflow: 'hidden' as const }}>
        {rationale}
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button onClick={e => { e.stopPropagation(); navigate(`/portfolio?symbol=${symbol}`) }} style={btn}>Holdings</button>
        <button onClick={e => { e.stopPropagation(); navigate(`/risk?symbol=${symbol}`) }} style={btn}>Risk</button>
        <button onClick={e => { e.stopPropagation(); navigate(`/research?symbol=${symbol}`) }} style={btn}>Research</button>
        <button onClick={e => { e.stopPropagation(); showToast(`${symbol} noted for journal`, 'info') }} style={btn}>Journal</button>
      </div>
    </div>
  )
}

const btn: React.CSSProperties = { fontSize: 10, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }
