/** Tooltip + MetricGuide (PR2, 2026-09-27). Hover, keyboard focus and tap all open it;
 *  Escape closes; the trigger gets aria-describedby so screen readers read the guide. */
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { RADIUS, SHADOW, TOKENS, TYPE } from '../../lib/designTokens'
import { fillGuide, useMetricGuide, type MetricGuideKey } from '../../lib/metricGuide'

export type Placement = 'top' | 'bottom' | 'left' | 'right'

const bubble = (placement: Placement): CSSProperties => ({
  position: 'absolute', zIndex: 60, minWidth: 200, maxWidth: 340,
  background: TOKENS.bg[1], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`,
  borderRadius: RADIUS.md, boxShadow: SHADOW[2], padding: '8px 10px',
  fontSize: TYPE.sm, lineHeight: 1.45, fontWeight: 500, textAlign: 'left', whiteSpace: 'normal',
  ...(placement === 'top' ? { bottom: 'calc(100% + 6px)', left: 0 } :
      placement === 'bottom' ? { top: 'calc(100% + 6px)', left: 0 } :
      placement === 'left' ? { right: 'calc(100% + 6px)', top: 0 } : { left: 'calc(100% + 6px)', top: 0 }),
})

export function Tooltip({ content, placement = 'top', children, style, as: Tag = 'span' }: {
  content: ReactNode
  placement?: Placement
  children: ReactNode
  style?: CSSProperties
  as?: 'span' | 'div'
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const ref = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('keydown', onKey); document.addEventListener('mousedown', onDoc)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onDoc) }
  }, [open])
  if (!content) return <>{children}</>
  const El = Tag as any
  return (
    <El
      ref={ref}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={(e: MouseEvent) => { e.stopPropagation(); setOpen(o => !o) }}
      style={{ position: 'relative', display: Tag === 'div' ? 'block' : 'inline-flex', cursor: 'help', outline: 'none', ...style }}
    >
      {children}
      {open && <div role="tooltip" id={id} style={bubble(placement)}>{content}</div>}
    </El>
  )
}

/** The four answers every metric owes the reader, from the guide store; `values` fills {placeholders}. */
export function MetricGuideBody({ guideKey, values, phase = 'full' }: {
  guideKey: MetricGuideKey
  values?: Record<string, unknown>
  phase?: 'short' | 'full'
}) {
  const g = useMetricGuide(guideKey)
  if (!g) return <div style={{ color: TOKENS.text[3] }}>Guide entry <code>{guideKey}</code> is not on file yet.</div>
  const line = (label: string, text?: string) => text ? (
    <div style={{ marginTop: 4 }}><b style={{ color: TOKENS.text[0] }}>{label}.</b> {fillGuide(text, values)}</div>
  ) : null
  return (
    <div>
      <div style={{ fontWeight: 800, color: TOKENS.text[0] }}>{g.label}</div>
      <div style={{ marginTop: 2 }}>{fillGuide(g.short, values)}</div>
      {phase === 'full' && (
        <>
          {line('What it is', g.definition)}
          {line('Why it matters', g.why_it_matters)}
          {line('How to read it', g.interpretation)}
          {line('Benchmark', g.benchmark)}
          {g.watch && <div style={{ marginTop: 4, color: TOKENS.warning }}><b>Watch:</b> {fillGuide(g.watch, values)}</div>}
          {g.warning && <div style={{ marginTop: 4, color: TOKENS.danger, fontWeight: 700 }}>{fillGuide(g.warning, values)}</div>}
        </>
      )}
    </div>
  )
}

/** Wrap anything with the guide for a key. */
export function MetricGuide({ guideKey, values, placement, children, phase }: {
  guideKey: MetricGuideKey
  values?: Record<string, unknown>
  placement?: Placement
  phase?: 'short' | 'full'
  children: ReactNode
}) {
  return <Tooltip placement={placement} content={<MetricGuideBody guideKey={guideKey} values={values} phase={phase} />}>{children}</Tooltip>
}
