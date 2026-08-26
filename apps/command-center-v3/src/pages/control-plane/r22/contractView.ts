/** Display-only copies of ControlPlane@v1.0.0 enums.
 * Do not infer, extend, or derive RuntimeStatus / node kinds here. */

import type { RuntimeStatus, WorkflowNodeKind } from '../../../control-plane/contractV1'

export const RUNTIME_STATUS_ORDER = [
  'LIVE_EVENT_DRIVEN',
  'LIVE_SCHEDULED',
  'CALLABLE_ONLY',
  'EXPECTED_IDLE',
  'SHADOW',
  'DISABLED',
  'BROKEN',
] as const satisfies readonly RuntimeStatus[]

export const WORKFLOW_LINEAGE_ORDER = [
  'event',
  'entity',
  'materiality',
  'graph',
  'research',
  'specialist',
  'council',
  'cio',
  'notification',
  'checkpoint',
  'outcome',
  'learning',
] as const satisfies readonly WorkflowNodeKind[]

export const WORKFLOW_LINEAGE_ARROW =
  'event → entity → materiality → graph → research → specialist → council → cio → notification → checkpoint → outcome → learning'

export type RuntimeStatusTone = (typeof RUNTIME_STATUS_ORDER)[number]
