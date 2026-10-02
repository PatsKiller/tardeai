import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

const SLOW_POLL_MS = 300_000 // never faster than 5 min; nothing loads until opened

/** Brain projections served on their own routes (not inside /api/v3/cio/brain):
 * the L0–L7 maturity contract and per-field policy provenance. Read-only. */
export default function CioBrainProjectionsPanel() {
  const [open, setOpen] = useState(false)
  const on = { enabled: open }
  const { data: contract, loading: contractLoading, error: contractError } = useApi<any>('/api/v3/cio/brain/maturity-contract', SLOW_POLL_MS, on)
  const { data: provenance, loading: provLoading, error: provError } = useApi<any>('/api/v3/cio/brain/policy-provenance', SLOW_POLL_MS, on)
  const levels: any[] = contract?.levels || []
  const fields: any[] = provenance?.fields || []
  return (
    <CioProjectionGroup
      title="Maturity contract & policy provenance"
      testId="cio-brain-route-projections"
      open={open}
      onToggle={setOpen}
      note="missing_evidence is shown as the payload states it (UNMEASURED is not a pass)."
    >
      <CioProjectionBlock
        title="Trade AI maturity contract (L0–L7)"
        block={contract}
        rows={levels.map((l) => ({ label: l.level ?? l.id ?? l.name, summary: l.name ?? l.description ?? l.summary }))}
        rowsLabel="levels"
        testId="cio-maturity-contract" loading={contractLoading} error={contractError}
      />
      <CioProjectionBlock
        title="Operator policy registry"
        block={provenance?.registry ?? null}
        testId="cio-policy-registry" loading={provLoading} error={provError}
      />
      <CioProjectionBlock
        title="Policy provenance"
        block={provenance}
        testId="cio-policy-provenance" loading={provLoading} error={provError}
      >
        {fields.length > 0 && (
          <div style={{ overflowX: 'auto', marginTop: 6 }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 11, color: 'var(--text2)', borderRadius: RADIUS.sm }}>
              <thead>
                <tr>{['field', 'value', 'confirmed', 'authority', 'source', 'version', 'effective_at'].map((h) => <th key={h} style={{ textAlign: 'left', padding: '2px 8px', color: 'var(--text3)' }}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.field}>
                    <td style={{ padding: '2px 8px', fontFamily: 'var(--mono)' }}>{f.field}</td>
                    <td style={{ padding: '2px 8px' }}>{f.value == null ? 'null' : typeof f.value === 'object' ? JSON.stringify(f.value) : String(f.value)}</td>
                    <td style={{ padding: '2px 8px' }}>{String(f.confirmed)}</td>
                    <td style={{ padding: '2px 8px' }}>{f.authority ?? 'NOT_IN_PAYLOAD'}</td>
                    <td style={{ padding: '2px 8px' }}>{f.source ?? 'NOT_IN_PAYLOAD'}</td>
                    <td style={{ padding: '2px 8px' }}>{f.version ?? 'NOT_IN_PAYLOAD'}</td>
                    <td style={{ padding: '2px 8px' }}>{f.effective_at ?? 'NOT_IN_PAYLOAD'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CioProjectionBlock>
    </CioProjectionGroup>
  )
}
