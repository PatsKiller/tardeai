/**
 * LABELED FIXTURE — ControlPlane@v1.0.0 preview JSON.
 * Byte-identical copies of fixtures/control_plane/v1.0.0/{research,stores,identity,notifications}.json.
 *
 * NOT the CONTROL_PLANE_API_V1_BASELINE HTTP envelope (data, not payload).
 * NOT live page data. Forbidden as a fallback when GET returns UNAVAILABLE.
 * Allowed for tests / explicitly labeled FIXTURE layout only.
 */

import type { ControlPlaneEnvelope } from '../../../control-plane/contractV1'
import type {
  CanonicalStoresPayload,
  IdentityPayload,
  NotificationsPayload,
  ResearchAttentionPayload,
} from './payloadTypes'
import research from './preview/research.json'
import stores from './preview/stores.json'
import identity from './preview/identity.json'
import notifications from './preview/notifications.json'

export const R23_PREVIEW_ROLE = 'FIXTURE' as const

export const RESEARCH_PREVIEW = research as ControlPlaneEnvelope<ResearchAttentionPayload>
export const STORES_PREVIEW = stores as ControlPlaneEnvelope<CanonicalStoresPayload>
export const IDENTITY_PREVIEW = identity as ControlPlaneEnvelope<IdentityPayload>
export const NOTIFICATIONS_PREVIEW = notifications as ControlPlaneEnvelope<NotificationsPayload>
