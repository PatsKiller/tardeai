import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { MobileDetailSheet, useMobilePageDetail } from '../MobileDetailSheet'
import { RADIUS, TOKENS, TYPE } from '../../lib/designTokens'
import { accountName } from '../../lib/accountLabels'
import { conflictSource, conflictTime, conflictValue, reviewPresentation } from '../../lib/watchConflictPresentation'
import { useApi } from '../../hooks/useApi'

/** Finding.as_dict() from the shared engine. Unknown fields stay absent, never inferred. */
export type ConflictFinding = {
  schema: string; engine: string; kind: string; rule: string; key: string
  summary: string; clears_when: string; action: string; severity: string
  owner?: string | null; next_run?: string | null
  sides: {source: string; value: unknown; as_of: string | null; account?: string | null; source_label?: string | null}[]
}
export type ConflictSection = {
  findings: ConflictFinding[]; headline: string | null; gap: {reason?: string; [key: string]: unknown} | null
  source?: string; as_of?: string | null; stale?: boolean | null
}
export type ConflictDecision = {
  schema: 'ConflictDecision@v1'; actor_kind: string; actor?: string; chosen_side: string; reason: string
  evidence_refs: string[]; at?: string; expires_at: string
}
export type ConflictEvent = {
  schema: 'ConflictEvent@v1'; key: string; event: string; at: string; request_id?: string
}
export type ConflictRecord = Omit<ConflictFinding, 'schema'> & {
  schema: 'ConflictRecord@v1'; state: string; subject: {kind: string; id: string; label?: string}
  opened_at: string; updated_at: string; revision: number; tier?: number; never_auto?: boolean
  decision: ConflictDecision | null; history: ConflictEvent[]
}
type ActionSlot = ReactNode | ((record: ConflictRecord | null, refetch: () => void) => ReactNode)

/** One URL contract for all consuming pages. Browser Back closes the selected finding. */
export function useConflictSheet() {
  const detail = useMobilePageDetail('conflict')
  return {key: detail.id, mobile: detail.mobile, open: detail.open, close: detail.close}
}

export function ConflictFacts({finding}: {finding: ConflictFinding}) {
  return <section aria-label="What disagrees" data-testid="conflict-facts" style={{display: 'grid', gap: 12, color: TOKENS.text[1], fontSize: TYPE.base}}>
    <h2 tabIndex={-1} data-detail-focus style={{fontSize: TYPE.lg, color: TOKENS.text[0], margin: 0}}>What disagrees</h2>
    <strong>{finding.summary}</strong>
    {finding.sides.map((side, index) => <div key={index} data-testid="conflict-side" style={{padding: 12, border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md}}>
      <b>{conflictSource(side)}</b>: {conflictValue(side.value)}
      <div>{conflictTime(side.as_of)}</div>
      {side.account && <div>{accountName(side.account)}</div>}
    </div>)}
    <div><b>Why it needs attention:</b> {finding.summary}</div>
    <div><b>What clears it:</b> {finding.clears_when || 'The engine did not supply a clearing condition.'}</div>
    <div><b>Owner:</b> {finding.owner || 'Not supplied by the engine'}</div>
    <div><b>Next run:</b> {finding.next_run ? Number.isFinite(Date.parse(finding.next_run)) ? conflictTime(finding.next_run) : finding.next_run : 'Not supplied by the engine'}</div>
    <div><b>Next step:</b> {finding.action ? finding.action.replace(/_/g, ' ') : 'Not supplied'}</div>
    {finding.action === 'notify_operator' && <Link className="mobile-detail-primary" to={`/approvals?conflict=${encodeURIComponent(finding.key)}`}>Open shared Approvals →</Link>}
  </section>
}

const eventLabels: Record<string, string> = {
  opened: 'Finding opened', finding_changed: 'Evidence changed', review_queued: 'Review queued',
  review_completed: 'Review decision recorded', decided: 'Decision recorded', cleared: 'Cleared by the engine',
  superseded: 'Superseded by newer evidence', reopened: 'Finding reopened',
}

/** Keyed reader prevents a retained result from a previous security appearing in this sheet. */
function SelectedConflict({selectedKey, section, onSelect, children}: {selectedKey: string; section: ConflictSection; onSelect: (key: string) => void; children?: ActionSlot}) {
  const read = useApi<ConflictRecord | {data?: ConflictRecord}>(`/api/v3/conflicts/${encodeURIComponent(selectedKey)}`, 15_000)
  const raw = read.data && 'data' in read.data ? read.data.data : read.data as ConflictRecord | null
  const record = raw?.schema === 'ConflictRecord@v1' && raw.key === selectedKey && typeof raw.summary === 'string' && Array.isArray(raw.sides)
    && Array.isArray(raw.history) && raw.history.every(event => event.key === selectedKey) && raw.subject?.id ? raw : null
  const snapshot = section.findings.find(finding => finding.key === selectedKey)
  const finding = record ? {...record, schema: 'ConflictFinding@v1'} : snapshot
  const status = reviewPresentation(record)
  return <>
    {section.gap && <p role="status" data-testid="conflict-gap">Conflict check unavailable: {typeof section.gap.reason === 'string' ? section.gap.reason : 'engine result not supplied'}</p>}
    {finding ? <ConflictFacts finding={finding} /> : <h2 tabIndex={-1} data-detail-focus>What disagrees</h2>}
    {!record && <p role="status" data-testid="conflict-record-gap">{read.loading ? 'Loading the saved finding and review history…' : `Saved finding and review history unavailable${read.error ? `: ${read.error}` : ': the selected record was not supplied'}.`}
      {snapshot && ' Showing the last supplied engine finding; its review state is unknown.'}</p>}
    {record && <section aria-label="Saved review history" style={{display: 'grid', gap: 12, marginTop: 16}}>
      <strong role="status" data-testid="conflict-record-state" data-state={record.state}>{status.label}</strong>
      <div>Updated {conflictTime(record.updated_at)}</div>
      {read.stale || read.error ? <p role="status">Saved review status is out of date{read.error ? `: ${read.error}` : '; refresh pending'}. The last recorded state is shown.</p> : null}
      {record.decision && <section aria-label="Recorded decision">
        <h3>Recorded decision</h3><p>{record.decision.reason}</p>
        <p>Chosen side: {conflictValue(record.decision.chosen_side)} · Recorded by: {record.decision.actor || record.decision.actor_kind}</p>
        <p>Expires {conflictTime(record.decision.expires_at)}</p>
        <p>Evidence: {record.decision.evidence_refs?.join(' · ') || 'Not supplied'}</p>
      </section>}
      <h3 style={{margin: 0}}>History</h3>
      {record.history.length ? <ol style={{paddingLeft: 20}}>{record.history.map((event, index) => <li key={index} style={{marginBottom: 8}}>
        {eventLabels[event.event] || event.event.replace(/_/g, ' ')} · {conflictTime(event.at)}
      </li>)}</ol> : <p>Event history was not supplied.</p>}
    </section>}
    <div style={{marginTop: 16}}>{typeof children === 'function' ? children(record, read.refetch) : children}</div>
    {section.findings.length > 1 && <nav aria-label="Other recorded findings" style={{display: 'grid', gap: 8, marginTop: 16}}>
      <h3>Recorded findings</h3>
      {section.findings.map(item => <button type="button" key={item.key} aria-current={item.key === selectedKey ? 'true' : undefined}
        onClick={() => onSelect(item.key)} style={{minHeight: 44, padding: 8, textAlign: 'left', color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md}}>{item.summary}</button>)}
    </nav>}
  </>
}

/** Shared shell and sole selected-record reader for Watch/Home/CIO/Risk/Ops. */
export default function ConflictSheet({title, section, mobile, onBack, children}: {
  title: string; section: ConflictSection; mobile?: boolean; onBack?: () => void; children?: ActionSlot
}) {
  const route = useConflictSheet()
  const panel = useRef<HTMLElement>(null)
  const phone = mobile ?? route.mobile
  const back = onBack ?? route.close
  useEffect(() => {
    if (!phone) panel.current?.querySelector<HTMLElement>('[data-detail-focus]')?.focus()
  }, [phone, route.key])
  const body = route.key ? <SelectedConflict key={route.key} selectedKey={route.key} section={section} onSelect={route.open}>{children}</SelectedConflict>
    : <p role="status" data-testid="conflict-record-gap">No finding is selected.</p>
  if (phone) return <MobileDetailSheet title={title} onBack={back}>{body}</MobileDetailSheet>
  return createPortal(<aside ref={panel} role="dialog" aria-modal="false" aria-label={title} style={{position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 1100,
    width: 'min(560px, 45vw)', boxSizing: 'border-box', overflowY: 'auto', padding: 16, minWidth: 0,
    borderLeft: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0]}}>
    <button type="button" onClick={back} style={{minHeight: 44, minWidth: 80, marginBottom: 12, color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, cursor: 'pointer'}}>← Back</button>
    {body}
  </aside>, document.body)
}
