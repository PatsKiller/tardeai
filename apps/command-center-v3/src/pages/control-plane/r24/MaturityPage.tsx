/** Control-plane Maturity page (R24). Side-by-side preview.
 *  Live path: GET CONTROL_PLANE_API_V1_BASELINE and render data.items.
 *  Does not invent a certification score. Does not compute overall / min / mean / weighted scores.
 *  limiting_dimension is shown only when present on the envelope — not argmin(score).
 *  UNAVAILABLE is the page truth. Do not keep populated FIXTURE dimensions as live data.
 *  Labeled FIXTURE may still show payload.dimensions for tests only. */

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
import { MATURITY_RENDER_FIELDS } from './payloadTypes'
import { extraPresent, useControlPlaneEnvelope } from './useControlPlaneEnvelope'

function dimensionRow(row: Record<string, unknown>): unknown[] {
  return [
    row.dimension,
    row.score,
    row.evidence_class,
    row.proof_refs,
    row.limiting_factor,
    row.next_proof,
  ]
}

export default function MaturityPage(props: { envelope?: unknown }) {
  const view = useControlPlaneEnvelope('maturity', props.envelope)
  const dimensions = view.items
  const certFlagPresent = extraPresent(view, 'overall_is_not_a_certification')
  const limitingPresent = extraPresent(view, 'limiting_dimension')
  const tableTitle = view.fixtureLabel ? 'FIXTURE payload.dimensions' : 'data.items'
  const emptyFallback = view.fixtureLabel ? 'payload.dimensions is empty' : 'data.items is empty'

  return (
    <PageFrame>
      <EnvelopeBanner
        title="Maturity"
        route={CONTROL_PLANE_PREVIEW_ROUTES.maturity}
        view={view}
        extra={
          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <NeutralChip>liveClaim={renderField(view.liveClaim)}</NeutralChip>
            <NeutralChip>computes_maturity={renderField(view.computesMaturity)}</NeutralChip>
            <NeutralChip>data.items={renderField(dimensions.length)}</NeutralChip>
          </div>
        }
      />

      <ProjectionStatePanel view={view} />

      <Panel
        title="overall_is_not_a_certification"
        kicker="no certification score in this UI"
        testId="maturity-not-certification"
      >
        <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
          {certFlagPresent ? renderField(view.extras.overall_is_not_a_certification) : 'absent'}
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
          This page does not invent a certification score. It does not average, min, max, or
          weight data.items (or FIXTURE payload.dimensions). Independent dimension scores are
          shown exactly as received. computes_maturity=false.
        </div>
      </Panel>

      <Panel
        title="limiting_dimension"
        kicker="from envelope when present, not argmin(score)"
        testId="maturity-limiting-dimension"
      >
        <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
          {limitingPresent ? renderField(view.extras.limiting_dimension) : 'absent'}
        </div>
      </Panel>

      <Panel
        title={tableTitle}
        kicker="independent dimensions · evidence_class · limiting_factor · next_proof"
        testId="maturity-dimensions"
      >
        <FieldTable
          columns={[...MATURITY_RENDER_FIELDS]}
          rows={dimensions.map(dimensionRow)}
          empty={projectionEmptyLabel(view.viewState, emptyFallback)}
        />
      </Panel>

      <Panel title={view.fixtureLabel ? 'FIXTURE payload (as received)' : 'data (as received)'} kicker="no client rewrite">
        <PayloadDump payload={view.data} />
      </Panel>
    </PageFrame>
  )
}
