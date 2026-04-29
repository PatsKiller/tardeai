interface SectionHeaderProps {
  title: string
  count?: number
}

export default function SectionHeader({ title, count }: SectionHeaderProps) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      marginBottom: 8,
      marginTop: 16,
    }}>
      <h2 style={{ fontFamily: 'var(--sans)', fontSize: 11, fontWeight: 600, color: 'var(--text2)', margin: 0, textTransform: 'uppercase', letterSpacing: '.5px' }}>{title}</h2>
      {count !== undefined && (
        <span style={{
          fontSize: 9,
          color: 'var(--accent)',
          background: 'var(--accent-dim)',
          padding: '0px 6px',
          borderRadius: 8,
          fontWeight: 700,
          lineHeight: '16px',
        }}>
          {count}
        </span>
      )}
      <div style={{ flex: 1, height: 1, background: 'var(--border-subtle)', marginLeft: 6 }} />
    </div>
  )
}
