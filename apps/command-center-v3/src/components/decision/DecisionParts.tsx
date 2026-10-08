/** Decision-speed UI parts (operator 2026-10-08): "80% of the screen should answer only three questions — what needs
 *  action right now, what is my highest risk, what is my highest opportunity. Numbers first: huge number, small label,
 *  colour card. Never mix opportunity and risk in the same visual area."
 *
 *  Strict colour discipline — five families, each one theme token (light + dark), never a raw hex:
 *    critical → danger (red) · high → warning (amber) · medium → info (blue) · opportunity → success (green)
 *    · security → ai (purple). */
import type { CSSProperties, ReactNode } from 'react'
import { RADIUS, TOKENS, numStyle } from '../../lib/designTokens'

export type Family = 'critical' | 'high' | 'medium' | 'opportunity' | 'security' | 'neutral'

const TONE: Record<Family, string> = {
  critical: 'danger', high: 'warning', medium: 'info', opportunity: 'success', security: 'ai', neutral: 'neutral',
}

/** Card colours for a family. Critical gets a stronger fill so it reads before anything else on the screen. */
export function familyStyle(f: Family): { color: string; bg: string; border: string } {
  const t = TONE[f]
  const color = `var(--${t}-color)`
  const strength = f === 'critical' ? 26 : 14
  return { color, bg: `color-mix(in srgb, ${color} ${strength}%, var(--bg1))`, border: color }
}

/** One mapping from a Communications item to its colour family (used by every feed card and badge). */
export function familyFor(priority?: string | null, category?: string | null): Family {
  if (category === 'security_alert') return 'security'
  if (category === 'reward' || category === 'high_conviction_opportunity' || category === 're_entry'
    || category === 'watchlist_candidate') return priority === 'critical' ? 'critical' : 'opportunity'
  if (priority === 'critical') return 'critical'
  if (priority === 'high') return 'high'
  if (priority === 'medium') return 'medium'
  return 'neutral'
}

export const FAMILY_ICON: Record<Family, string> = {
  critical: '🚨', high: '⚠️', medium: '🔷', opportunity: '🟢', security: '🔐', neutral: '•',
}

/** Huge number, small label, colour card. */
export function BigNumberCard({ icon, label, value, family, sub, onClick, testId }: {
  icon?: string; label: string; value: ReactNode; family: Family; sub?: ReactNode; onClick?: () => void; testId?: string
}) {
  const s = familyStyle(family)
  return (
    <button type="button" onClick={onClick} data-testid={testId} data-family={family} disabled={!onClick}
      style={{ all: 'unset', cursor: onClick ? 'pointer' : 'default', display: 'block', background: s.bg,
        border: `1px solid ${s.border}`, borderRadius: RADIUS.lg, padding: '12px 14px', minWidth: 0 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: s.color, letterSpacing: '.06em', textTransform: 'uppercase' }}>
        {icon ? `${icon} ` : ''}{label}
      </div>
      <div style={{ ...numStyle, fontSize: 34, fontWeight: 900, color: 'var(--text0)', lineHeight: 1.1, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 2 }}>{sub}</div>}
    </button>
  )
}

/** Executive strip: large numbers, tiny labels, unequal sizing (the first item dominates). */
export function ExecutiveStrip({ items }: { items: { label: string; value: ReactNode; sub?: ReactNode; tone?: string }[] }) {
  return (
    <div data-testid="executive-strip" style={{ display: 'grid', gridTemplateColumns: `2fr ${items.slice(1).map(() => '1fr').join(' ')}`,
      gap: 18, alignItems: 'end', padding: '14px 18px', borderTop: '2px solid var(--border)', borderBottom: '2px solid var(--border)', marginBottom: 14 }}>
      {items.map((it, i) => (
        <div key={it.label} style={{ minWidth: 0 }}>
          <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.08em' }}>{it.label}</div>
          <div style={{ ...numStyle, fontSize: i === 0 ? 40 : 26, fontWeight: 900, color: it.tone || 'var(--text0)', lineHeight: 1.1 }}>{it.value}</div>
          {it.sub && <div style={{ ...numStyle, fontSize: 12, color: it.tone || 'var(--text2)' }}>{it.sub}</div>}
        </div>
      ))}
    </div>
  )
}

/** A full-width decision card: one family, one question, one call to action. */
export function ActionCard({ family, icon, title, children, cta, testId, style }: {
  family: Family; icon: string; title: string; children: ReactNode
  cta?: { label: string; href?: string; onClick?: () => void }; testId?: string; style?: CSSProperties
}) {
  const s = familyStyle(family)
  return (
    <section data-testid={testId} data-family={family}
      style={{ background: s.bg, border: `1px solid ${s.border}`, borderLeft: `5px solid ${s.border}`, borderRadius: RADIUS.lg, padding: '14px 18px', ...style }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 900, color: s.color, letterSpacing: '.06em', textTransform: 'uppercase' }}>{icon} {title}</div>
        {cta && (cta.href
          ? <a href={cta.href} style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', border: `1px solid ${s.border}`, borderRadius: RADIUS.md, padding: '5px 14px', textDecoration: 'none' }}>{cta.label}</a>
          : <button type="button" onClick={cta.onClick} style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', background: 'transparent', border: `1px solid ${s.border}`, borderRadius: RADIUS.md, padding: '5px 14px', cursor: 'pointer' }}>{cta.label}</button>)}
      </div>
      {children}
    </section>
  )
}

/** A big number with a small label inside an ActionCard. */
export function Stat({ value, label, tone }: { value: ReactNode; label: string; tone?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ ...numStyle, fontSize: 30, fontWeight: 900, color: tone || 'var(--text0)', lineHeight: 1.05 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
    </div>
  )
}

export const TONE_TOKEN = TOKENS
