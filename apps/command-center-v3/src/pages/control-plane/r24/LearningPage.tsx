/** Control-plane Learning page (R24). Side-by-side preview.
 *  Live path: GET CONTROL_PLANE_API_V1_BASELINE and render data.items grouped by kind.
 *  If the API item/envelope does not include auto_promotions, show absent.
 *  This page does not auto-promote policy. No promote control is rendered.
 *  UNAVAILABLE / INVALID_SCHEMA is the page truth. MEMORY_BEHAVIOR_INFLUENCE=0.
 *  Labeled FIXTURE may still show payload.items for tests only. */

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
import {
  LEARNING_KIND_LABELS,
  LEARNING_KINDS,
  isLearningKind,
  type LearningKind,
} from './payloadTypes'
import { extraPresent, useControlPlaneEnvelope } from './useControlPlaneEnvelope'

const ITEM_COLUMNS = [
  'item_id',
  'kind',
  'status',
  'score',
  'evidence_class',
  'proof_refs',
  'limiting_factor',
  'next_proof',
]

function itemRow(item: Record<string, unknown>): unknown[] {
  return [
    item.item_id,
    item.kind,
    item.status,
    item.score,
    item.evidence_class,
    item.proof_refs,
    item.limiting_factor,
    item.next_proof,
  ]
}

export default function LearningPage(props: { envelope?: unknown }) {
  const view = useControlPlaneEnvelope('learning', props.envelope)
  const items = view.items
  const autoPromotionsPresent = extraPresent(view, 'auto_promotions')

  const byKind: Record<LearningKind, Record<string, unknown>[]> = {
    decision: [],
    checkpoint: [],
    outcome: [],
    lesson: [],
    hypothesis: [],
    experiment: [],
    specialist_performance: [],
    model_performance: [],
    routing_candidate: [],
  }
  const otherKinds: Record<string, unknown>[] = []
  for (const item of items) {
    const kind = item.kind
    if (typeof kind === 'string' && isLearningKind(kind)) byKind[kind].push(item)
    else otherKinds.push(item)
  }

  const itemsKicker = view.fixtureLabel
    ? 'FIXTURE payload.items · tests only'
    : 'live path data.items'

  return (
    <PageFrame>
      <EnvelopeBanner
        title="Learning"
        route={CONTROL_PLANE_PREVIEW_ROUTES.learning}
        view={view}
        extra={
          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <NeutralChip>liveClaim={renderField(view.liveClaim)}</NeutralChip>
            <NeutralChip>kinds={LEARNING_KINDS.length}</NeutralChip>
            <NeutralChip>data.items={renderField(items.length)}</NeutralChip>
          </div>
        }
      />

      <ProjectionStatePanel view={view} />

      <Panel
        title="auto_promotions"
        kicker="policy is not auto-promoted"
        testId="learning-auto-promotions"
      >
        <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>
          {autoPromotionsPresent ? renderField(view.extras.auto_promotions) : 'absent'}
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
          If the API item/envelope does not include auto_promotions, show absent.
          This page does not auto-promote policy, lessons, models, or routing candidates.
          No promote control is rendered. MEMORY_BEHAVIOR_INFLUENCE=0.
        </div>
      </Panel>

      {LEARNING_KINDS.map(kind => (
        <Panel
          key={kind}
          title={LEARNING_KIND_LABELS[kind]}
          kicker={`kind=${kind} · ${itemsKicker}`}
          testId={`learning-kind-${kind}`}
        >
          <FieldTable
            columns={ITEM_COLUMNS}
            rows={byKind[kind].map(itemRow)}
            empty={projectionEmptyLabel(view.viewState, `no data.items with kind=${kind}`)}
          />
        </Panel>
      ))}

      {otherKinds.length > 0 ? (
        <Panel title="Other kinds in data.items" kicker="rendered, not dropped" testId="learning-kind-other">
          <FieldTable columns={ITEM_COLUMNS} rows={otherKinds.map(itemRow)} empty="none" />
        </Panel>
      ) : null}

      <Panel title={view.fixtureLabel ? 'FIXTURE payload (as received)' : 'data (as received)'} kicker="no client rewrite">
        <PayloadDump payload={view.data} />
      </Panel>
    </PageFrame>
  )
}
