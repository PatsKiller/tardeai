import type { ReportCardItem } from '../SynthesizedReportCard'

const SEV: Record<string, string> = { critical: '#ef4444', urgent: '#ef4444', warning: '#f59e0b', info: '#60a5fa' }
const CLASS_SHORT: Record<string, string> = {
  stop_triggered: 'Stop', unprotected_position: 'Unprot', approval_needed: 'Approval',
  system_health: 'System', research_needed: 'Research', hermes_review: 'Hermes',
}

function ago(iso?: string): string {
  if (!iso) return ''
  const h = (Date.now() - Date.parse(iso)) / 3.6e6
  if (!Number.isFinite(h)) return ''
  return h < 1 ? 'now' : h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`
}

export default function ArchiveListItem({ item, selected, onClick }: { item: ReportCardItem & { action_count?: number; synthesized_insight?: string }; selected?: boolean; onClick: () => void }) {
  const sev = (item.severity || 'info').toLowerCase()
  const accent = SEV[sev] || '#60a5fa'
  const syms = (item.symbols?.length ? item.symbols : item.symbol ? [item.symbol] : []).slice(0, 3)
  const insight = item.synthesized_insight || ''
  const actionPills = (item.action_classes || []).slice(0, 2)

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
        padding: '10px 12px', borderRadius: 8,
        border: `1px solid ${selected ? accent + '88' : 'var(--border-subtle)'}`,
        background: selected ? accent + '0c' : 'var(--bg1)',
        borderLeft: `3px solid ${accent}`,
        transition: 'border-color .12s, background .12s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 3 }}>
            <span style={{ fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 4, background: accent + '22', color: accent, textTransform: 'uppercase' }}>{sev}</span>
            {item.has_actions && item.action_count != null && item.action_count > 0 && (
              <span style={{ fontSize: 8, fontWeight: 800, padding: '1px 6px', borderRadius: 4, background: '#f59e0b18', color: '#f59e0b' }}>{item.action_count} act</span>
            )}
          </div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title}</div>
          {insight && (
            <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{insight}</div>
          )}
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6, alignItems: 'center' }}>
            {syms.map(s => <span key={s} style={{ fontSize: 10, fontWeight: 800, fontFamily: 'var(--mono)', color: '#60a5fa' }}>{s}</span>)}
            {actionPills.map(c => (
              <span key={c} style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text3)' }}>{CLASS_SHORT[c] || c}</span>
            ))}
          </div>
        </div>
        <div style={{ textAlign: 'right', flexShrink: 0 }}>
          <div style={{ fontSize: 9, color: 'var(--text2)', fontWeight: 700 }}>{ago(item.created_at)}</div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 3, maxWidth: 72, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.channel}</div>
        </div>
      </div>
    </button>
  )
}