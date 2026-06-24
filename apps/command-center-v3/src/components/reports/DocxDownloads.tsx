export default function DocxDownloads({ itemDocx }: { itemDocx?: { filename: string; url: string; size_kb?: number } | null }) {
  if (!itemDocx?.url) return null
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase' }}>Downloads</span>
      <a href={itemDocx.url} download={itemDocx.filename} style={{
        fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6,
        border: '1px solid #60a5fa55', background: '#60a5fa14', color: '#60a5fa', textDecoration: 'none',
      }}>
        Word · {itemDocx.filename}{itemDocx.size_kb ? ` (${itemDocx.size_kb} KB)` : ''} ↓
      </a>
    </div>
  )
}