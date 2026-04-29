import s from './MorningBrief.module.css'

interface Cell { label: string; val: string; sub?: string; color?: string; onClick?: () => void }

export default function MorningCommandStrip({ cells }: { cells: Cell[] }) {
  return (
    <div className={s.strip}>
      {cells.map(c => (
        <div key={c.label} className={s.stripCell} data-click={c.onClick ? '' : undefined} onClick={c.onClick}>
          <div className={`${s.stripLabel} ${s.sans}`}>{c.label}</div>
          <div className={`${s.stripVal} ${s.sans}`} style={{ color: c.color || 'var(--text0)' }}>{c.val}</div>
          {c.sub && <div className={`${s.stripSub} ${s.sans}`} style={{ color: c.color || 'var(--text3)' }}>{c.sub}</div>}
        </div>
      ))}
    </div>
  )
}
