import { useNavigate } from 'react-router-dom'
import { useToast } from '../ToastProvider'

interface ChecklistItem { text: string; status: 'good' | 'warning' | 'bad' }

interface StrategyCardProps {
  title: string
  recommendation: string
  detail: string
  checklist: ChecklistItem[]
  rotationTarget?: string
  actionLabel?: string
  actionRoute?: string
  onApply?: () => void
}

const STATUS_ICON: Record<string, string> = { good: '✅', warning: '⚠️', bad: '❌' }
const STATUS_COLOR: Record<string, string> = { good: 'var(--green)', warning: 'var(--amber)', bad: 'var(--red)' }

export default function StrategyCard({ title, recommendation, detail, checklist, rotationTarget, actionLabel, actionRoute, onApply }: StrategyCardProps) {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const recColor = recommendation.includes('TRIM') || recommendation.includes('SELL') ? 'var(--amber)' : recommendation.includes('ADD') || recommendation.includes('BUY') ? 'var(--green)' : 'var(--accent)'

  const handleAction = () => {
    if (onApply) onApply()
    else if (actionRoute) navigate(actionRoute)
    else showToast('Strategy queued for review', 'success')
  }

  return (
    <div style={{ background: 'rgba(22,26,34,0.95)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: 22 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{title}</div>
        <span style={{ padding: '4px 16px', borderRadius: 9999, fontSize: 11, fontWeight: 700, background: `color-mix(in srgb, ${recColor} 15%, transparent)`, color: recColor }}>{recommendation}</span>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 16 }}>{detail}</div>

      {checklist.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          {checklist.map((item, i) => (
            <div key={i} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: i < checklist.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none', alignItems: 'flex-start' }}>
              <span style={{ fontSize: 12, flexShrink: 0 }}>{STATUS_ICON[item.status]}</span>
              <span style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>{item.text}</span>
            </div>
          ))}
        </div>
      )}

      {rotationTarget && (
        <div style={{ padding: '10px 14px', background: 'rgba(14,203,129,0.06)', border: '1px solid rgba(14,203,129,0.15)', borderRadius: 8, fontSize: 10, color: 'var(--text1)', lineHeight: 1.6, marginBottom: 16 }}>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', marginBottom: 4 }}>Rotation Target</div>
          {rotationTarget}
        </div>
      )}

      <button onClick={handleAction} style={{
        width: '100%', padding: 14, background: `color-mix(in srgb, ${recColor} 10%, transparent)`,
        border: `1px solid ${recColor}`, color: recColor, fontWeight: 700, borderRadius: 10, fontSize: 12, cursor: 'pointer', fontFamily: 'var(--sans)',
      }}>
        {actionLabel || 'Apply Strategy'} →
      </button>
    </div>
  )
}
