/** Presentation-only formatters. Missing item keys render as "absent". No state inference. */

export const ABSENT = 'absent'

export function displayScalar(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

export function displayList(values: string[] | null | undefined): string {
  if (!values || values.length === 0) return '—'
  return values.join(', ')
}

export function displayRecord(
  rec: Record<string, string | number | null | undefined> | null | undefined,
): string {
  if (!rec) return '—'
  const keys = Object.keys(rec)
  if (keys.length === 0) return '—'
  return keys
    .map((key) => `${key}=${displayScalar(rec[key])}`)
    .join(' ')
}

/** Envelope / present-value formatter. null stays "null"; undefined is absent. */
export function displayPresent(value: unknown): string {
  if (value === undefined) return ABSENT
  if (value === null) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number' || typeof value === 'bigint') return String(value)
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((entry) => displayPresent(entry)).join(', ')
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return ABSENT
    }
  }
  return String(value)
}

/** Render an item key that exists; missing keys are "absent". Do not invent values. */
export function displayItemField(
  item: Record<string, unknown> | null | undefined,
  key: string,
): string {
  if (!item || !Object.prototype.hasOwnProperty.call(item, key)) return ABSENT
  return displayPresent(item[key])
}

/** Nested identifier-style lookup. Missing parent or child => "absent". */
export function displayNestedField(
  item: Record<string, unknown> | null | undefined,
  parent: string,
  key: string,
): string {
  if (!item || !Object.prototype.hasOwnProperty.call(item, parent)) return ABSENT
  const rec = item[parent]
  if (rec === null) return 'null'
  if (typeof rec !== 'object' || Array.isArray(rec)) return ABSENT
  return displayItemField(rec as Record<string, unknown>, key)
}

export function presentItemKeys(item: Record<string, unknown> | null | undefined): string {
  if (!item) return ABSENT
  const keys = Object.keys(item)
  if (keys.length === 0) return ABSENT
  return keys.join(', ')
}
