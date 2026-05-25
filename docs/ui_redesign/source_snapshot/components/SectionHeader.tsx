interface SectionHeaderProps {
  title: string
  count?: number
}

export default function SectionHeader({ title, count }: SectionHeaderProps) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      marginBottom: 10,
      marginTop: 18,
    }}>
      <h2 style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 700, color: 'var(--text1)', margin: 0, textTransform: 'uppercase', letterSpacing: '.5px' }}>{title}</h2>
      {count !== undefined && (
        <span style={{
          fontSize: 9,
          color: 'var(--accent)',
          background: 'rgba(74,144,244,0.1)',
          padding: '2px 8px',
          borderRadius: 9999,
          fontWeight: 700,
          lineHeight: '16px',
          minWidth: 20,
          textAlign: 'center',
        }}>
          {count}
        </span>
      )}
      <div style={{ flex: 1, height: 1, background: 'var(--border)', marginLeft: 4 }} />
    </div>
  )
}
