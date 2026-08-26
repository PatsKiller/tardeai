/** Payload shapes from ControlPlane@v1.0.0 fixtures. Do not invent row states here. */

import type {
  CanonicalStoreStatus,
  IdentityStatus,
  NotificationStatus,
  ResearchAttentionStatus,
} from '../../../control-plane/contractV1'

export interface ResearchAttentionPayload {
  universe: string
  adaptive_cadence: { state: string; label: string }
  rows: ResearchAttentionStatus[]
}

export interface CanonicalStoresPayload {
  persistent_root: string
  legacy_root: string
  stores: CanonicalStoreStatus[]
}

export interface IdentityPayload {
  never_mint_from_ticker: boolean
  rows: IdentityStatus[]
}

export interface NotificationsPayload {
  funnel: Record<string, number>
  rows: NotificationStatus[]
}
