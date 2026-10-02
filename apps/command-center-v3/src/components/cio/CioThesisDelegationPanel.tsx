import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import CioProjectionBlock, { CioProjectionGroup } from './CioProjectionBlock'

const SLOW_POLL_MS = 300_000 // never faster than 5 min; nothing loads until opened

/** Thesis & delegation — the CIO's desk thesis, desk note, open actions, open
 * plans, Hermes delegation/challenges, data-broker snapshot and sector
 * opportunity synthesis. Read-only; fetched only while the section is open.
 */
export default function CioThesisDelegationPanel() {
  const [open, setOpen] = useState(false)
  const on = { enabled: open }
  const { data: thesis, loading: thesisLoading, error: thesisError } = useApi<any>('/api/v3/cio/thesis', SLOW_POLL_MS, on)
  const { data: deskNote, loading: noteLoading, error: noteError } = useApi<any>('/api/v3/cio/desk-note', SLOW_POLL_MS, on)
  const { data: actions, loading: actionsLoading, error: actionsError } = useApi<any>('/api/v3/cio/actions', SLOW_POLL_MS, on)
  const { data: plans, loading: plansLoading, error: plansError } = useApi<any>('/api/v3/cio/plans?limit=12', SLOW_POLL_MS, on)
  const { data: delegation, loading: delegationLoading, error: delegationError } = useApi<any>('/api/v3/cio/delegation', SLOW_POLL_MS, on)
  const { data: snapshot, loading: snapshotLoading, error: snapshotError } = useApi<any>('/api/v3/cio/snapshot', SLOW_POLL_MS, on)
  const { data: sectors, loading: sectorsLoading, error: sectorsError } = useApi<any>('/api/v2/cio/sector-opportunities', SLOW_POLL_MS, on)

  const deleg = delegation?.delegation || null
  const planRows: any[] = plans?.plans || []
  return (
    <CioProjectionGroup
      title="Thesis & delegation — desk thesis, desk note, actions, plans, Hermes delegation, sectors"
      testId="cio-thesis-delegation"
      open={open}
      onToggle={setOpen}
      note="Loaded only while open; refreshed at most every 5 minutes. READ_ONLY_ADVISORY — nothing here is an order."
    >
      <CioProjectionBlock
        title={`Desk thesis ${thesis?.thesis_version ? `· ${thesis.thesis_version}` : '· version NOT_IN_PAYLOAD'}`}
        block={thesis ? { as_of: thesis.as_of, thesis_version: thesis.thesis_version, authority: thesis.authority } : null}
        testId="cio-desk-thesis" loading={thesisLoading} error={thesisError}
      >
        {typeof thesis?.thesis === 'string'
          ? <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: 'var(--text2)', margin: '6px 0 0', maxHeight: 240, overflow: 'auto' }}>{thesis.thesis}</pre>
          : <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>{thesis?.thesis ? JSON.stringify(thesis.thesis).slice(0, 600) : 'No pinned desk thesis in payload'}</div>}
      </CioProjectionBlock>

      <CioProjectionBlock
        title={`Desk note ${deskNote?.version || ''}`}
        block={deskNote ? { ok: deskNote.ok, as_of: deskNote.as_of, thesis_version: deskNote.thesis_version, cash_stage: deskNote.cash_stage, error: deskNote.error } : null}
        rows={deskNote?.sector_posture?.tensions}
        rowsLabel="sector tensions"
        testId="cio-desk-note" loading={noteLoading} error={noteError}
      >
        {deskNote?.note && <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11, color: 'var(--text2)', margin: '6px 0 0', maxHeight: 240, overflow: 'auto' }}>{String(deskNote.note)}</pre>}
      </CioProjectionBlock>

      <CioProjectionBlock
        title={`Open CIO actions (${actions?.count ?? 0})`}
        block={actions ? { as_of: actions.as_of, count: actions.count } : null}
        rows={(actions?.actions || []).map((a: any) => ({ title: a.title || a.summary || a.cio_action_id, state: a.status }))}
        rowsLabel="actions (status from the action ledger)"
        testId="cio-open-actions" loading={actionsLoading} error={actionsError}
      />

      <CioProjectionBlock
        title={`Open plans (${plans?.count ?? 0})`}
        block={plans ? { as_of: plans.as_of, count: plans.count, authority: plans.authority } : null}
        testId="cio-open-plans" loading={plansLoading} error={plansError}
      >
        <ul style={{ margin: '4px 0 0 16px', padding: 0, fontSize: 11, color: 'var(--text2)' }}>
          {planRows.slice(0, 12).map((p) => (
            <li key={p.plan_id}>
              <Link to={`/cio?tab=decisions&plan=${encodeURIComponent(p.plan_id)}`} style={{ color: 'var(--accent)' }}>{p.title || p.plan_id}</Link>
              {' · '}{p.situation_label || p.situation_type || 'situation NOT_IN_PAYLOAD'} · {p.status || 'status NOT_IN_PAYLOAD'}
            </li>
          ))}
        </ul>
      </CioProjectionBlock>

      <CioProjectionBlock
        title="Delegation — agent handoffs and Hermes challenges"
        block={delegation ? { as_of: delegation.as_of, handoffs_total: deleg?.handoffs?.total, challenges_pending: deleg?.challenges?.pending, challenge_streams: deleg?.challenges?.unique_streams } : null}
        rows={deleg ? [
          ...Object.entries(deleg.handoffs?.statuses || {}).map(([k, v]) => `handoff ${k} · ${v}`),
          ...Object.entries(deleg.challenges?.statuses || {}).map(([k, v]) => `challenge ${k} · ${v}`),
        ] : undefined}
        rowsLabel="status counts"
        testId="cio-delegation" loading={delegationLoading} error={delegationError}
      />

      <CioProjectionBlock
        title="Data-broker snapshot"
        block={snapshot?.snapshot ?? null}
        rows={snapshot?.snapshot?.health ? Object.entries(snapshot.snapshot.health).map(([k, v]) => `${k} · ${typeof v === 'object' ? JSON.stringify(v).slice(0, 80) : String(v)}`) : undefined}
        rowsLabel="domain health"
        testId="cio-broker-snapshot" loading={snapshotLoading} error={snapshotError}
      />

      <CioProjectionBlock
        title="Sector opportunity synthesis"
        block={sectors}
        rows={sectors?.sectors || sectors?.opportunities}
        rowsLabel="sectors"
        testId="cio-sector-opportunities" loading={sectorsLoading} error={sectorsError}
      />
    </CioProjectionGroup>
  )
}
