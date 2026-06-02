export default function HubPlaceholder({ name }: { name: string }) {
  return (
    <div style={{ padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text2)', marginBottom: 8 }}>{name} Hub</div>
      <div style={{ fontSize: 12, color: 'var(--text3)' }}>Awaiting build from spec document. Click any metric strip tile to test DetailDrawer.</div>
    </div>
  )
}
