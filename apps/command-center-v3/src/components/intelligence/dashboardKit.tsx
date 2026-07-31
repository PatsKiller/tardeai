import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'

const MUTED = 'var(--text3)'
const DIM = 'var(--text3)'
const GREEN = 'var(--green)'
const RED = 'var(--red)'
const AMBER = 'var(--amber)'
const BLUE = 'var(--blue)'

export const dashboardCard: React.CSSProperties = {
  background: 'var(--bg1)',
  border: '1px solid var(--border)',
  borderRadius: 10,
  padding: 14,
}

export function KPI({ label, value, sub, color = 'var(--text0)', active = false, onClick }: {
  label: string
  value: React.ReactNode
  sub?: string
  color?: string
  active?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={onClick ? 'Click to filter / focus this set' : undefined}
      style={{
        textAlign: 'left',
        background: active ? `${color}1f` : 'var(--bg2)',
        border: `1px solid ${active ? color : 'var(--border)'}`,
        borderRadius: 10,
        padding: '10px 12px',
        cursor: onClick ? 'pointer' : 'default',
        width: '100%',
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 950, color }}>{value}</div>
      <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', letterSpacing: '.05em', marginTop: 3 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: active ? color : DIM, marginTop: 4 }}>{sub}</div>}
    </button>
  )
}

export function ChartCard({ title, subtitle, children, accent = BLUE }: {
  title: string
  subtitle?: string
  children: React.ReactNode
  accent?: string
}) {
  return (
    <div style={{ ...dashboardCard, borderLeft: `4px solid ${accent}`, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: subtitle ? 2 : 10 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 10, color: MUTED, marginBottom: 10 }}>{subtitle}</div>}
      {children}
    </div>
  )
}

const DONUT_PALETTE = [GREEN, BLUE, AMBER, RED, 'var(--purple)', 'var(--teal)']

export function DonutStat({ data, height = 140, onSliceClick }: {
  data: { name: string; value: number; color?: string }[]
  height?: number
  onSliceClick?: (name: string) => void
}) {
  const filtered = data.filter(d => d.value > 0)
  if (!filtered.length) {
    return <div style={{ fontSize: 11, color: MUTED, padding: 12, textAlign: 'center' }}>No data</div>
  }
  const total = filtered.reduce((a, d) => a + d.value, 0)
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ width: height, height, minWidth: height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={filtered}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius="58%"
              outerRadius="88%"
              paddingAngle={2}
              onClick={(_, i) => onSliceClick?.(filtered[i]?.name ?? '')}
              style={{ cursor: onSliceClick ? 'pointer' : 'default' }}
            >
              {filtered.map((d, i) => (
                <Cell key={d.name} fill={d.color ?? DONUT_PALETTE[i % DONUT_PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(v: number, name: string) => [`${v} (${total ? Math.round((v / total) * 100) : 0}%)`, name]}
              contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 120 }}>
        {filtered.map((d, i) => {
          const pct = total ? Math.round((d.value / total) * 100) : 0
          const c = d.color ?? DONUT_PALETTE[i % DONUT_PALETTE.length]
          return (
            <button
              key={d.name}
              type="button"
              onClick={() => onSliceClick?.(d.name)}
              style={{
                display: 'grid',
                gridTemplateColumns: '10px 1fr auto',
                gap: 8,
                alignItems: 'center',
                background: 'transparent',
                border: 0,
                padding: 0,
                cursor: onSliceClick ? 'pointer' : 'default',
                textAlign: 'left',
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 4, background: c }} />
              <span style={{ fontSize: 11, color: 'var(--text1)' }}>{d.name}</span>
              <span style={{ fontSize: 10, color: MUTED }}>{d.value} ({pct}%)</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function MiniBarRow({ rows, onRowClick }: {
  rows: { label: string; value: number; max?: number; color?: string; sub?: string }[]
  onRowClick?: (label: string) => void
}) {
  const maxVal = Math.max(1, ...rows.map(r => r.max ?? r.value))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map(r => {
        const pct = Math.min(100, (r.value / maxVal) * 100)
        const c = r.color ?? (pct >= 75 ? GREEN : pct >= 40 ? AMBER : RED)
        return (
          <button
            key={r.label}
            type="button"
            onClick={() => onRowClick?.(r.label)}
            style={{
              display: 'grid',
              gridTemplateColumns: '120px 1fr auto',
              gap: 10,
              alignItems: 'center',
              background: 'transparent',
              border: 0,
              padding: 0,
              cursor: onRowClick ? 'pointer' : 'default',
              textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 11, color: 'var(--text1)', fontWeight: 700 }}>{r.label}</span>
            <div style={{ background: 'var(--bg2)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, background: c, height: '100%', transition: 'width .2s' }} />
            </div>
            <span style={{ fontSize: 10, color: MUTED, whiteSpace: 'nowrap' }}>{r.sub ?? r.value}</span>
          </button>
        )
      })}
    </div>
  )
}

export function SeverityDot({ severity }: { severity: string }) {
  const s = severity.toLowerCase()
  const color = /crit|urgent/.test(s) ? RED : /warn|high|medium/.test(s) ? AMBER : /pos|good|low/.test(s) ? GREEN : BLUE
  return <span style={{ width: 7, height: 7, borderRadius: 4, background: color, flexShrink: 0, display: 'inline-block' }} />
}

export function SectionHeader({ title, subtitle, accent = BLUE, right }: {
  title: string
  subtitle?: string
  accent?: string
  right?: React.ReactNode
}) {
  return (
    <div style={{
      ...dashboardCard,
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      flexWrap: 'wrap',
      gap: 10,
      borderLeft: `4px solid ${accent}`,
    }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 10, color: MUTED, marginTop: 2 }}>{subtitle}</div>}
      </div>
      {right}
    </div>
  )
}
