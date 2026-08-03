/**
 * Canonical lane label registry.
 * Import this single source of truth wherever a lane id needs a human-readable name.
 */
export const LANE_LABELS: Record<string, string> = {
  'deepseek-flash': 'DeepSeek Flash',
  'deepseek-v4': 'DeepSeek v4',
  grok: 'Grok OAuth',
  chatgpt: 'ChatGPT OAuth',
  local: 'Local LLM',
  claude: 'Claude',
}

/**
 * Returns a human-readable label for a lane id, or the lane id itself, or a fallback.
 */
export const laneLabel = (lane?: string): string =>
  LANE_LABELS[lane || ''] || lane || 'AI'

/**
 * Semantic color for each lane (used for badges, chips, indicators).
 */
export const LANE_COLORS: Record<string, string> = {
  'deepseek-flash': '#6c5ce7',
  'deepseek-v4': '#a29bfe',
  grok: '#1d9bf0',
  chatgpt: '#10a37f',
  local: '#2dd4bf',
  claude: '#d97757',
}

/**
 * Icons for each lane (used in button / badge decoration).
 */
export const LANE_ICONS: Record<string, string> = {
  'deepseek-flash': '⚡',
  'deepseek-v4': '✦',
  grok: '𝕏',
  chatgpt: '◎',
  local: '🖥',
  claude: '✶',
}

/**
 * All recognized cloud / LLM lane ids.
 */
export const ALL_LANES: string[] = [
  'deepseek-flash',
  'deepseek-v4',
  'grok',
  'chatgpt',
  'local',
  'claude',
]
