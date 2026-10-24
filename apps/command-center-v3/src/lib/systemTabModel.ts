/** System navigation is URL state; no system-health or business facts are calculated here. */
export const SYSTEM_TABS = ['Platform', 'Pipeline', 'Control Plane', 'Data Sources', 'Queue', 'SIEM', 'Jobs', 'Apps', 'Access', 'Admin', 'Brokers', 'Crons', 'LLM', 'Hermes', 'OpenClaw', 'TradeAI'] as const
export type SystemTab = typeof SYSTEM_TABS[number]

export function systemTab(params: URLSearchParams): SystemTab {
  const requested = params.get('tab')?.trim().toLowerCase()
  return SYSTEM_TABS.find(tab => tab.toLowerCase() === requested) || 'Pipeline'
}

/** Preserve report focus, search context and any unrelated bookmark parameters. */
export function systemTabParams(params: URLSearchParams, tab: SystemTab): URLSearchParams {
  const next = new URLSearchParams(params)
  next.set('tab', tab)
  return next
}
