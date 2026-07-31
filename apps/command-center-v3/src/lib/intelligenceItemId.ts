/** Content-derived id — stable across polls/reorders (same algorithm as Command Center). */
export function intelligenceItemId(type: string, source: string, symbol: string | undefined, title: string) {
  const s = `${type}|${source}|${symbol ?? ''}|${title}`
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0
  return `${type}-${(h >>> 0).toString(36)}`
}

export type IntelligenceItemType = 'news' | 'research_gap' | 'research_brief' | 'library' | 'topic' | 'signal'

export type IntelligenceItemStatus = 'active' | 'dismissed' | 'reviewed'
