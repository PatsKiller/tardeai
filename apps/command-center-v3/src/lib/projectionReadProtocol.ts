// Payload major versions are independent of the /api/v2 transport namespace.
// URL separation also separates useApi's path-keyed revalidation state.
const READ_PATHS = Object.freeze({
  today: '/api/v2/coordination/n8n-today?projection_version=2',
  events: '/api/v2/coordination/events?projection_version=2&limit=200',
  runs: '/api/v2/coordination/events?projection_version=2&source=runs&limit=40',
  outbox: '/api/v2/coordination/outbox?projection_version=2&hours=24',
})
export type ProjectionRead = keyof typeof READ_PATHS

export function projectionReadPath(kind: ProjectionRead): string {
  if (!Object.prototype.hasOwnProperty.call(READ_PATHS, kind)) throw new Error('unsupported projection read')
  return READ_PATHS[kind]
}
