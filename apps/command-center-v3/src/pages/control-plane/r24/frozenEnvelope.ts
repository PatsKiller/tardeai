/** Labeled FIXTURE ControlPlane@v1.0.0 envelopes for R24 unit tests only.
 *  Live pages consume CONTROL_PLANE_API_V1_BASELINE (`data`, not `payload`).
 *  These JSON files must not be the live view when GET is UNAVAILABLE.
 *  Equality with fixtures/control_plane/v1.0.0 is enforced by tests/test_r24_*.py.
 *  This module does not infer RuntimeStatus, EvidenceClass, or maturity scores. */

import {
  CONTROL_PLANE_CONTRACT_VERSION,
  type ControlPlaneEnvelope,
} from '../../../control-plane/contractV1'
import type { AuditPayload, LearningPayload, MaturityPayload } from './payloadTypes'
import learningJson from './frozen/learning.json'
import maturityJson from './frozen/maturity.json'
import auditJson from './frozen/audit.json'

export type ControlPlanePageName = 'learning' | 'maturity' | 'audit'

export const CONTROL_PLANE_GET = {
  learning: '/api/v3/control-plane/learning',
  maturity: '/api/v3/control-plane/maturity',
  audit: '/api/v3/control-plane/audit',
} as const

export const CONTROL_PLANE_PREVIEW_ROUTES = {
  learning: '/control-plane/learning',
  maturity: '/control-plane/maturity',
  audit: '/control-plane/audit',
} as const

export function isControlPlaneEnvelope<T>(
  value: unknown,
  page: ControlPlanePageName,
): value is ControlPlaneEnvelope<T> {
  if (value === null || typeof value !== 'object') return false
  const row = value as Record<string, unknown>
  return (
    row.schema === CONTROL_PLANE_CONTRACT_VERSION &&
    row.page === page &&
    row.authority === 'READ_ONLY_ADVISORY' &&
    row.memory_behavior_influence === 0 &&
    row.computes_cio_decisions === false &&
    row.computes_agent_state === false &&
    row.computes_maturity === false &&
    row.computes_notification_eligibility === false &&
    Object.prototype.hasOwnProperty.call(row, 'payload') &&
    typeof row.as_of === 'string' &&
    typeof row.evidence_class === 'string' &&
    typeof row.source_sha === 'string' &&
    typeof row.data_quality === 'string'
  )
}

function requireFrozen<T>(value: unknown, page: ControlPlanePageName): ControlPlaneEnvelope<T> {
  if (!isControlPlaneEnvelope<T>(value, page)) {
    throw new Error(`frozen ${page} fixture is not ${CONTROL_PLANE_CONTRACT_VERSION}`)
  }
  return value
}

/** Labeled FIXTURE — tests only. Not the live view. */
export const FROZEN_LEARNING = requireFrozen<LearningPayload>(learningJson, 'learning')
/** Labeled FIXTURE — tests only. Not the live view. */
export const FROZEN_MATURITY = requireFrozen<MaturityPayload>(maturityJson, 'maturity')
/** Labeled FIXTURE — tests only. Not the live view. */
export const FROZEN_AUDIT = requireFrozen<AuditPayload>(auditJson, 'audit')

/** Labeled FIXTURE map — tests only. Live pages must not default to this. */
export const FROZEN_ENVELOPES = {
  learning: FROZEN_LEARNING,
  maturity: FROZEN_MATURITY,
  audit: FROZEN_AUDIT,
} as const
