# Source Export: ProgressBar.tsx

- **Original path:** apps/command-center-v2/src/components/ProgressBar.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 411d3bbde6eb216515d3058defee03f37217db9e0cf47f314d4668e154d0120a
- **File size:** 3052 bytes
- **Exists:** YES

```tsx
import type { CSSProperties } from 'react'

interface ProgressBarProps {
  value: number // 0-100
  max?: number
  label?: string
  sublabel?: string
  color?: string
  height?: number
  showPct?: boolean
  markers?: { position: number; label: string; color?: string }[]
  gradient?: boolean
}

export default function ProgressBar({
  value, max = 100, label, sublabel, color = 'var(--accent)',
  height = 10, showPct = true, markers, gradient = false
}: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))
  const bg = gradient
    ? `linear-gradient(90deg, ${color}, ${color}88)`
    : color

  return (
    <div style={{ marginBottom: 4 }}>
      {(label || showPct) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
          {label && <span style={{ fontSize: 10, color: 'var(--text2)', fontFamily: 'var(--sans)', fontWeight: 600 }}>{label}</span>}
          {showPct && <span style={{ fontSize: 10, color: 'var(--text1)', fontWeight: 700, fontFamily: 'var(--sans)' }}>{pct.toFixed(0)}%</span>}
        </div>
      )}
      <div style={{ position: 'relative', height, background: 'var(--bg3)', borderRadius: height, overflow: 'visible' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: height,
          background: bg, transition: 'width 500ms ease-out',
          boxShadow: `0 0 8px ${color}40`,
        }} />
        {markers?.map((m, i) => {
          const mPos = Math.min(100, Math.max(0, (m.position / max) * 100))
          return (
            <div key={i} style={{
              position: 'absolute', left: `${mPos}%`, top: -3,
              width: 2, height: height + 6, background: m.color || 'var(--text1)',
              borderRadius: 1, opacity: 0.8,
            }}>
              <span style={{
                position: 'absolute', top: height + 8, left: '50%', transform: 'translateX(-50%)',
                fontSize: 8, color: m.color || 'var(--text3)', whiteSpace: 'nowrap', fontFamily: 'var(--sans)',
              }}>{m.label}</span>
            </div>
          )
        })}
      </div>
      {sublabel && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>{sublabel}</div>}
    </div>
  )
}


interface StatusIndicatorProps {
  status: 'good' | 'warning' | 'danger' | 'neutral' | 'info'
  label: string
  pulse?: boolean
}

export function StatusIndicator({ status, label, pulse = false }: StatusIndicatorProps) {
  const colors = { good: '#0ecb81', warning: '#f0b90b', danger: '#f6465d', neutral: '#6b7a8d', info: '#4a90f4' }
  const c = colors[status]
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        width: 8, height: 8, borderRadius: 99, background: c,
        boxShadow: pulse ? `0 0 8px ${c}80` : 'none',
        animation: pulse ? 'pulse 2s infinite' : 'none',
      }} />
      <span style={{ fontSize: 10, color: c, fontWeight: 600, fontFamily: 'var(--sans)' }}>{label}</span>
    </div>
  )
}
```
