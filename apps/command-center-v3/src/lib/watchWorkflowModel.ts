/** Watch prospects workflow strip — a fixed-order per-security pipeline strip (WS-B).
 *
 *  Each node's status is DERIVED from the prospect payload's real fields only, so the strip shows
 *  which stages the record actually carries versus which are wired or dark. Display-only: no fetch,
 *  no write, no re-run, no decision. The five states:
 *    LIVE    — a concrete, current field proves the stage produced.
 *    PARTIAL — the field has a value but it is stale or incomplete.
 *    UNWIRED — the field exists on the record but holds nothing.
 *    DARK    — the record carries no field for the stage (no producer wired).
 *    UNKNOWN — not derivable from any payload field (never guessed).
 *
 *  The node order is fixed by the operator directive (AGENTS.md §13.4 pipeline stages, plus the
 *  MBI_BEHAVIOR rail) — never reorder it here. */

import type { ProspectRow } from './watchProspectsModel.ts'

export type WorkflowState = 'LIVE' | 'PARTIAL' | 'UNWIRED' | 'DARK' | 'UNKNOWN'
export type WorkflowNode = { key: string; label: string; state: WorkflowState; note: string }

export const WORKFLOW_LABELS = {
  event: 'Event',
  security: 'Security/Sector/Catalyst',
  identity: 'Identity',
  materiality: 'Materiality',
  instrument: 'InstrumentRecord',
  gap: 'Research gap',
  judgment: 'JUDGMENT',
  specialist: 'Specialist dispatch',
  commitment: 'Commitment',
  product: 'CIO product',
  notification: 'Notification',
  delivery: 'Delivery',
  outcome: 'Outcome',
  scoring: 'Scoring',
  mbi: 'MBI_BEHAVIOR',
} as const

export const WORKFLOW_ORDER = Object.keys(WORKFLOW_LABELS) as (keyof typeof WORKFLOW_LABELS)[]

const node = (key: keyof typeof WORKFLOW_LABELS, state: WorkflowState, note: string): WorkflowNode =>
  ({ key, label: WORKFLOW_LABELS[key], state, note })

const isConfirmed = (s: string | null | undefined) => String(s || '').toUpperCase() === 'CONFIRMED'

function eventNode(row: ProspectRow): WorkflowNode {
  const facts = row.company_facts
  const cat = facts?.catalyst
  if (!facts) return node('event', 'DARK', 'no company facts on this record (no producer wired)')
  if (cat?.status === 'CURRENT' && cat?.headline) return node('event', 'LIVE', `catalyst: ${cat.headline}`)
  if (cat && (cat.headline || cat.status === 'STALE' || cat.reason || cat.missing_reason)) {
    return node('event', 'PARTIAL',
      cat.headline ? `catalyst ${String(cat.status || 'unverified').toLowerCase()}: ${cat.headline}` : 'catalyst present but stale or unverified')
  }
  return node('event', 'UNWIRED', 'company facts recorded, no catalyst event on file')
}

function securityNode(row: ProspectRow): WorkflowNode {
  const facts = row.company_facts
  if (!facts) return node('security', 'DARK', 'no company facts on this record (no producer wired)')
  const security = facts.company?.value
  const sector = facts.sector?.value || facts.industry?.value
  const catalyst = facts.catalyst?.headline || facts.catalyst?.status === 'CURRENT'
  const filled = [security, sector, catalyst].filter(Boolean).length
  if (filled === 3) return node('security', 'LIVE', 'security, sector and catalyst all on file')
  if (filled > 0) return node('security', 'PARTIAL', `${filled} of security / sector / catalyst on file`)
  return node('security', 'UNWIRED', 'company facts present but no security, sector or catalyst value')
}

function identityNode(row: ProspectRow): WorkflowNode {
  if (isConfirmed(row.identity_status) || row.security_guid) {
    return node('identity', 'LIVE', row.security_guid ? 'resolved to a security GUID' : `identity ${row.identity_status}`)
  }
  if (row.identity_status != null) return node('identity', 'PARTIAL', `identity ${row.identity_status} — not confirmed`)
  return node('identity', 'UNWIRED', 'identity unresolved (no confirmed security GUID)')
}

function instrumentNode(row: ProspectRow): WorkflowNode {
  if (row.summary) return node('instrument', 'LIVE', 'the instrument record is composed on this page')
  return node('instrument', 'UNWIRED', 'no summary on the record')
}

function gapNode(row: ProspectRow): WorkflowNode {
  if ((row.whats_missing || []).length > 0) {
    return node('gap', 'LIVE', `gaps named: ${(row.whats_missing || []).join(' · ')}`)
  }
  return node('gap', 'UNKNOWN', 'no gaps recorded — cannot tell none-found from not-run')
}

function judgmentNode(row: ProspectRow): WorkflowNode {
  if (row.stance) return node('judgment', 'LIVE', `stance: ${String(row.stance).replace(/_/g, '-')}`)
  return node('judgment', 'UNWIRED', 'no stance recorded yet')
}

function specialistNode(row: ProspectRow): WorkflowNode {
  if ((row.conviction_components || []).length > 0) {
    return node('specialist', 'LIVE', `${row.conviction_components.length} specialist component(s) contributed`)
  }
  return node('specialist', 'UNWIRED', 'no specialist conviction components recorded')
}

function productNode(row: ProspectRow): WorkflowNode {
  const hasConviction = row.conviction != null && Number.isFinite(row.conviction)
  const hasStance = !!row.stance
  if (hasConviction && hasStance) return node('product', 'LIVE', 'conviction and stance composed')
  if (hasConviction || hasStance) return node('product', 'PARTIAL', 'conviction or stance missing from the composed product')
  return node('product', 'UNWIRED', 'no composed CIO product yet')
}

function surfaceFor(row: ProspectRow, name: string) {
  return (row.surfaces || []).find(s => s.surface === name)
}

function notificationNode(row: ProspectRow): WorkflowNode {
  const tg = surfaceFor(row, 'Telegram')
  if (!tg) return node('notification', 'DARK', 'no Telegram surface on this record')
  if (tg.joined) return node('notification', 'LIVE', `Telegram joined: ${tg.value}`)
  return node('notification', 'PARTIAL', `Telegram not joined: ${tg.value || 'no value'}`)
}

function deliveryNode(row: ProspectRow): WorkflowNode {
  if (row.review_state?.publication_verified) return node('delivery', 'LIVE', 'research published into the canonical CIO memory')
  const tg = surfaceFor(row, 'Telegram')
  if (tg?.joined) return node('delivery', 'LIVE', `delivered to Telegram: ${tg.value}`)
  if (tg) return node('delivery', 'UNKNOWN', 'no delivery receipt on this record')
  return node('delivery', 'DARK', 'no delivery surface on this record')
}

function scoringNode(row: ProspectRow): WorkflowNode {
  if (row.conviction != null && Number.isFinite(row.conviction)) {
    return node('scoring', 'LIVE', `conviction ${row.conviction.toFixed(0)} / 100`)
  }
  return node('scoring', 'UNWIRED', 'not scored')
}

/** The per-security workflow strip: one node per fixed stage, status derived from real fields only. */
export function workflowStrip(row: ProspectRow): WorkflowNode[] {
  return [
    eventNode(row),
    securityNode(row),
    identityNode(row),
    node('materiality', 'UNKNOWN', 'materiality is not represented on the Watch prospect record'),
    instrumentNode(row),
    gapNode(row),
    judgmentNode(row),
    specialistNode(row),
    node('commitment', 'UNKNOWN', 'commitments are not on the Watch prospect record'),
    productNode(row),
    notificationNode(row),
    deliveryNode(row),
    node('outcome', 'UNKNOWN', 'outcome is not on the Watch prospect record (the round trip lives on the position record)'),
    scoringNode(row),
    node('mbi', 'UNKNOWN', 'not a payload field — the behaviour rail is enforced unconditionally in code (BehaviorWriteRefused); no behaviour write can be recorded'),
  ]
}
