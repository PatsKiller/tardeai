// Watcher operation, incident severity and this-poll delivery are different facts.
export type WatcherStatus = 'ok' | 'degraded' | 'down' | 'absent'
export type WatcherFact = { status: WatcherStatus; display_status?: string | null }
export type NotificationFact = { status?: string; delivered?: boolean; summary?: string | null }

export function watcherStatusText(watcher: WatcherFact): string {
  if (typeof watcher.display_status === 'string' && watcher.display_status.trim()) return watcher.display_status.trim()
  return { ok: 'Watching', degraded: 'Degraded', down: 'Failed', absent: 'Not measured' }[watcher.status] ?? 'Not measured'
}

export function notificationStatusText(notification: NotificationFact, incidentStatus: string): string {
  if (typeof notification.summary === 'string' && notification.summary.trim()) return notification.summary.trim()
  if (notification.delivered === true) return 'Delivered this poll'
  if (notification.status === 'NOT_REQUIRED') {
    return `No send requested this poll; incident status is ${incidentStatus}. Previous delivery is not measured.`
  }
  return notification.status?.toLowerCase().replace(/_/g, ' ') || 'Delivery not confirmed'
}

export function jobsPopulationText(summary: unknown): string | null {
  if (!summary || typeof summary !== 'object') return null
  const record = summary as Record<string, unknown>, groups = record.populations
  if (!groups || typeof groups !== 'object') return null
  const counts = groups as Record<string, unknown>
  const names: [string, string][] = [['scheduled', 'scheduled'], ['continuous_service', 'continuous services'],
    ['on_demand', 'on demand'], ['event_driven', 'event driven'], ['not_scheduled', 'not scheduled'],
    ['no_schedule_declared', 'without a declared schedule']]
  const parts = names.flatMap(([key, label]) => typeof counts[key] === 'number' && Number.isInteger(counts[key]) && Number(counts[key]) >= 0 ? [`${counts[key]} ${label}`] : [])
  return parts.length ? `Registry populations: ${parts.join(' · ')}. Due today is a different population from all registered components.` : null
}
