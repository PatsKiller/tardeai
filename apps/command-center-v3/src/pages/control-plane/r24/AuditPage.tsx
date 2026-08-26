/** Control-plane Audit page (R24). Side-by-side preview.
 *  Live path: GET CONTROL_PLANE_API_V1_BASELINE and render data.items.
 *  known_gaps / readiness are shown only when present on the envelope; otherwise absent.
 *  No marketing claims. Does not claim R20-R24 live.
 *  Labeled FIXTURE may still show payload.claims + payload.known_gaps for tests only. */

import {
  EnvelopeBanner,
  FieldTable,
  NeutralChip,
  PageFrame,
  Panel,
  PayloadDump,
  ProjectionStatePanel,
  projectionEmptyLabel,
  renderField,
} from './controlPlaneChrome'
import { CONTROL_PLANE_PREVIEW_ROUTES } from './frozenEnvelope'
import { AUDIT_SECTIONS, claimSectionIds } from './payloadTypes'
import { extraPresent, useControlPlaneEnvelope } from './useControlPlaneEnvelope'

const CLAIM_COLUMNS = [
  'claim_id',
  'claim',
  'implementation_ref',
  'test_ref',
  'evidence_ref',
  'evidence_class',
  'limitations',
  'reproduction_command',
]

function claimRow(claim: Record<string, unknown>): unknown[] {
  return [
    claim.claim_id,
    claim.claim,
    claim.implementation_ref,
    claim.test_ref,
    claim.evidence_ref,
    claim.evidence_class,
    claim.limitations,
    claim.reproduction_command,
  ]
}

export default function AuditPage(props: { envelope?: unknown }) {
  const view = useControlPlaneEnvelope('audit', props.envelope)
  const claims = view.items
  const gapsPresent = extraPresent(view, 'known_gaps')
  const gaps = Array.isArray(view.extras.known_gaps) ? view.extras.known_gaps : []
  const readinessPresent = extraPresent(view, 'readiness')
  const liveLabel = view.fixtureLabel ? 'FIXTURE payload.claims' : 'data.items'

  const claimsBySection: Record<string, Record<string, unknown>[]> = {}
  for (const section of AUDIT_SECTIONS) claimsBySection[section.id] = []
  for (const claim of claims) {
    for (const sectionId of claimSectionIds(claim)) {
      claimsBySection[sectionId]?.push(claim)
    }
  }

  return (
    <PageFrame>
      <EnvelopeBanner
        title="Audit"
        route={CONTROL_PLANE_PREVIEW_ROUTES.audit}
        view={view}
        extra={
          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <NeutralChip>liveClaim={renderField(view.liveClaim)}</NeutralChip>
            <NeutralChip>readiness={readinessPresent ? renderField(view.extras.readiness) : 'absent'}</NeutralChip>
            <NeutralChip>data.items={renderField(claims.length)}</NeutralChip>
          </div>
        }
      />

      <ProjectionStatePanel view={view} />

      <Panel title="readiness" kicker="from envelope when present · not a live R20-R24 claim" testId="audit-readiness">
        <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
          {readinessPresent ? renderField(view.extras.readiness) : 'absent'}
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
          No marketing claims. This page does not claim R20-R24 live. Capability statements below
          are data.items rows (FIXTURE payload.claims) with implementation_ref, test_ref, evidence_ref,
          evidence_class, limitations, and reproduction_command.
        </div>
      </Panel>

      {AUDIT_SECTIONS.map(section => {
        if (section.id === 'known_gaps') {
          return (
            <Panel key={section.id} title="Known gaps" kicker="extras.known_gaps · else absent" testId="audit-section-known_gaps">
              <FieldTable
                columns={['known_gap']}
                rows={gaps.map(gap => [gap])}
                empty={
                  gapsPresent
                    ? projectionEmptyLabel(view.viewState, 'known_gaps is empty')
                    : 'known_gaps absent'
                }
              />
            </Panel>
          )
        }
        if (section.id === 'reproduction_commands') {
          return (
            <Panel
              key={section.id}
              title="Reproduction commands"
              kicker={`claim.reproduction_command from ${liveLabel}`}
              testId="audit-section-reproduction_commands"
            >
              <FieldTable
                columns={['claim_id', 'reproduction_command']}
                rows={claims.map(claim => [claim.claim_id, claim.reproduction_command])}
                empty={projectionEmptyLabel(view.viewState, `no reproduction_command in ${liveLabel}`)}
              />
            </Panel>
          )
        }
        if (section.id === 'evidence') {
          return (
            <Panel
              key={section.id}
              title="Evidence"
              kicker={`claim.evidence_ref + claim.evidence_class from ${liveLabel}`}
              testId="audit-section-evidence"
            >
              <FieldTable
                columns={['claim_id', 'evidence_ref', 'evidence_class']}
                rows={claims.map(claim => [claim.claim_id, claim.evidence_ref, claim.evidence_class])}
                empty={projectionEmptyLabel(view.viewState, `no evidence fields in ${liveLabel}`)}
              />
            </Panel>
          )
        }
        return (
          <Panel
            key={section.id}
            title={section.label}
            kicker={`from ${liveLabel} tagged section=${section.id}`}
            testId={`audit-section-${section.id}`}
          >
            <FieldTable
              columns={CLAIM_COLUMNS}
              rows={(claimsBySection[section.id] ?? []).map(claimRow)}
              empty={projectionEmptyLabel(view.viewState, `no ${liveLabel} assigned to ${section.label}`)}
            />
          </Panel>
        )
      })}

      <Panel title={liveLabel} kicker="full claim roster" testId="audit-claims">
        <FieldTable
          columns={CLAIM_COLUMNS}
          rows={claims.map(claimRow)}
          empty={projectionEmptyLabel(view.viewState, view.fixtureLabel ? 'payload.claims is empty' : 'data.items is empty')}
        />
      </Panel>

      <Panel title={view.fixtureLabel ? 'FIXTURE payload (as received)' : 'data (as received)'} kicker="no client rewrite">
        <PayloadDump payload={view.data} />
      </Panel>
    </PageFrame>
  )
}
