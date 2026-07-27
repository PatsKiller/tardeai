import { useState, type CSSProperties } from 'react'
import { useReEntryExitEvidence } from '../../hooks/useReEntryExitEvidence'
import { BB } from '../../lib/holdingsTerminalTokens'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 5 }
const button: CSSProperties = { fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 4, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }

export default function ReEntryEvidenceContractPanel() {
  const evidence = useReEntryExitEvidence(365)
  const [open, setOpen] = useState(false)
  const quantityRows = evidence.sources.reduce((sum, source) => sum + (evidence.sourceFieldCoverage[source.key]?.quantity ?? 0), 0)
  const priceRows = evidence.sources.reduce((sum, source) => sum + (evidence.sourceFieldCoverage[source.key]?.price ?? 0), 0)
  const proceedsRows = evidence.sources.reduce((sum, source) => sum + (evidence.sourceFieldCoverage[source.key]?.proceeds_usd ?? 0), 0)
  const sourceCount = evidence.sources.filter(source => source.available).length

  return <section style={{ ...panel, padding: 9 }} aria-label="Re-Entry evidence contract">
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div style={{ flex: 1 }}><b style={{ fontSize: 11 }}>DATA CONTRACT {evidence.contractVersion}</b><div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{sourceCount}/{evidence.sources.length} sources reporting · quantity-bearing source rows {quantityRows} · price-bearing {priceRows} · proceeds-bearing {proceedsRows}</div></div>
      <span style={{ fontSize: 10, color: quantityRows ? BB.green : BB.amber }}>{quantityRows ? 'QUANTITY EVIDENCE PRESENT' : 'NO SOURCE IS REPORTING SHARES'}</span>
      <button onClick={() => setOpen(value => !value)} style={button}>{open ? 'HIDE SOURCE MATRIX' : 'SHOW SOURCE MATRIX'}</button>
    </div>
    <div style={{ marginTop: 6, fontSize: 10, color: BB.text2, lineHeight: 1.45 }}>
      Redeploy book &amp; history supply events/proceeds; quantity comes from full-fidelity cache + closed-trade journal when present.
      {' '}Zero share counts on book/history are expected — those sources are event/proceeds feeds, not share sources.
    </div>
    {open && <div style={{ overflowX: 'auto', marginTop: 8 }}><div style={{ minWidth: 780 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '180px repeat(6,1fr)', gap: 6, padding: '5px 6px', fontSize: 10, color: BB.text3, borderBottom: '1px solid var(--border)' }}><span>Source</span><span>Rows</span><span>Account</span><span>Shares</span><span>Price</span><span>Proceeds</span><span>Reason</span></div>
      {evidence.sources.map(source => {
        const coverage = evidence.sourceFieldCoverage[source.key]
        return <div key={source.key} style={{ display: 'grid', gridTemplateColumns: '180px repeat(6,1fr)', gap: 6, padding: '6px', fontSize: 10, borderBottom: '1px solid var(--border)', background: source.available ? 'transparent' : 'var(--bg2)' }}><b>{source.label}</b><span>{source.rows}</span><span>{coverage?.account ?? 0}</span><span>{coverage?.quantity ?? 0}</span><span>{coverage?.price ?? 0}</span><span>{coverage?.proceeds_usd ?? 0}</span><span>{coverage?.description ?? 0}</span></div>
      })}
      <div style={{ marginTop: 7, fontSize: 10, color: BB.text3 }}>A blank transaction field is recoverable only when a compatible event or aggregate supplies it, or when two other numeric facts prove it arithmetically. The source matrix distinguishes a deployment/cache problem from genuinely absent broker evidence. Redeploy book/history rows with 0 shares are not defects — use journal/full-fidelity cache for quantity.</div>
    </div></div>}
  </section>
}
