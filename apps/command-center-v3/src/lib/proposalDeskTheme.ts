/** Mature institutional tokens for the Path B proposals desk — derived from index.css vars. */



export const desk = {
  bg: 'var(--bg1)',
  bgElevated: 'var(--bg2)',
  bgInset: 'var(--bg3)',
  border: 'var(--border)',
  borderSubtle: 'var(--border-subtle)',
  text: 'var(--text0)',
  textMuted: 'var(--text2)',
  textDim: 'var(--text3)',
  mono: 'var(--mono)',
  radius: 'var(--radius)',
  radiusLg: '10px',
  radiusXl: '12px',
  green: 'var(--green)',
  red: 'var(--red)',
  amber: 'var(--amber)',
  blue: 'var(--blue)',
  purple: 'var(--purple)',
  teal: 'var(--teal, #2dd4bf)',
  greenDim: 'var(--green-dim)',
  redDim: 'var(--red-dim)',
  amberDim: 'var(--amber-dim)',
  accentDim: 'var(--accent-dim)',
  blueDim: 'rgba(96,165,250,.08)',
} as const

export const panel = {
  padding: '12px 14px',
  gap: 10,
} as const

export const sectionLabel: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: 'var(--text3)',
  textTransform: 'uppercase',
  letterSpacing: '0.45px',
  marginBottom: 6,
}

export const cardShell = (blocked = false): React.CSSProperties => ({
  borderRadius: desk.radiusXl,
  background: desk.bg,
  border: `1px solid ${blocked ? 'rgba(239,68,68,.28)' : desk.border}`,
  overflow: 'hidden',
})

export const statusPill = (color: string, muted = false): React.CSSProperties => ({
  fontSize: 10,
  fontWeight: 700,
  padding: '3px 8px',
  borderRadius: desk.radius,
  background: muted ? desk.bgInset : `${color}14`,
  color: muted ? desk.textMuted : color,
  border: `1px solid ${muted ? desk.borderSubtle : `${color}33`}`,
  letterSpacing: '0.2px',
  whiteSpace: 'nowrap',
})

