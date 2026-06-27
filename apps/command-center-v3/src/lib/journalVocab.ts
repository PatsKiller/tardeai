export type VocabConfig = {
  storageKey: string
  defaults: readonly string[]
  selectPlaceholder: string
  addTitle: string
  addHint: string
  addPlaceholder: string
  addConfirmLabel: string
  emptyError: string
  normalize?: (raw: string) => string
  loadDbOptions?: () => Promise<string[]>
}

export function loadCustomVocab(storageKey: string): string[] {
  try {
    const raw = localStorage.getItem(storageKey)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

function saveCustomVocab(storageKey: string, items: string[]): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(items))
  } catch {
    /* ignore */
  }
}

export function mergeVocab(config: VocabConfig, extra: string[] = []): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  const norm = config.normalize ?? ((s: string) => s.trim())
  const add = (s: string) => {
    const t = norm(s)
    if (!t) return
    const k = t.toLowerCase()
    if (seen.has(k)) return
    seen.add(k)
    out.push(t)
  }
  for (const f of config.defaults) add(f)
  for (const f of loadCustomVocab(config.storageKey)) add(f)
  for (const f of extra) add(f)
  return out.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
}

export function addVocabItem(config: VocabConfig, name: string): string {
  const norm = config.normalize ?? ((s: string) => s.trim())
  const trimmed = norm(name)
  if (!trimmed) return ''
  const lower = trimmed.toLowerCase()
  const existing = mergeVocab(config).find(f => f.toLowerCase() === lower)
  if (existing) return existing
  const custom = loadCustomVocab(config.storageKey)
  custom.push(trimmed)
  saveCustomVocab(config.storageKey, custom)
  return trimmed
}