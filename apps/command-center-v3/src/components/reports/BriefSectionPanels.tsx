import type { BriefSection } from './briefUtils'

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }

const ACCENT: Record<string, string> = {
  exec: '#60a5fa', risk: '#ef4444', steph: '#a855f7', recovery: '#f59e0b',
  rotation: '#22c55e', next: '#f59e0b', intel: '#60a5fa',
}

export default function BriefSectionPanels({ sections, executiveFallback }: { sections: BriefSection[]; executiveFallback?: string }) {
  if (!sections.length && executiveFallback) {
    return (
      <div style={{ ...card, borderLeft: '4px solid #60a5fa' }}>
        <div style={{ fontSize: 11, fontWeight: 900, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: 0.4 }}>Executive Summary</div>
        <div style={{ fontSize: 12.5, color: 'var(--text1)', lineHeight: 1.6, marginTop: 8, whiteSpace: 'pre-wrap' }}>{executiveFallback}</div>
      </div>
    )
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10 }}>
      {sections.map(s => (
        <div key={s.id} style={{ ...card, borderLeft: `4px solid ${ACCENT[s.id] || '#94a3b8'}` }}>
          <div style={{ fontSize: 11, fontWeight: 900, color: ACCENT[s.id] || 'var(--text2)', textTransform: 'uppercase', letterSpacing: 0.35 }}>{s.label}</div>
          <div style={{ fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.55, marginTop: 8, whiteSpace: 'pre-wrap', maxHeight: 220, overflow: 'auto' }}>
            {s.body.trim().slice(0, 1800)}
          </div>
        </div>
      ))}
    </div>
  )
}