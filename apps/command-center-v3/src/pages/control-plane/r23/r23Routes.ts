/** Intended side-by-side routes for R23. Not registered in App.tsx or NavRail.tsx. */
export const R23_INTENDED_ROUTES = {
  research: '/control-plane/research',
  data: '/control-plane/data',
  identity: '/control-plane/identity',
  notifications: '/control-plane/notifications',
} as const

/** HTTP freeze consumed by these pages. Field vocabulary remains ControlPlane@v1.0.0. */
export const R23_CONTRACT = 'CONTROL_PLANE_API_V1_BASELINE' as const
export const R23_VOCABULARY_CONTRACT = 'ControlPlane@v1.0.0' as const
export const R23_LIVE_CLAIM = false
