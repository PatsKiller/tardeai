/** Metric guide store (PR2, 2026-09-27) — the content behind every tooltip.
 *
 * A guide entry answers four questions about a metric: what it is, why it matters, how to
 * read it, and what a benchmark looks like; optional watch/warning lines. Content is
 * SERVER-SUPPLIED (assets/ui_metric_guide.yaml served at GET /api/v2/ui/metric-guide,
 * PR3); until the endpoint exists, entries can be registered locally by the migration of the
 * options dictionaries. The frontend never composes guide text (AGENTS §13) — it only fills
 * `{placeholder}`s from values already in the payload.
 */
import { useEffect, useState } from 'react'

export type MetricGuideEntry = {
  label: string
  short: string
  definition: string
  why_it_matters: string
  interpretation: string
  benchmark?: string
  watch?: string
  warning?: string
  unit?: string
  sources?: string[]
}
/** Widened to string until PR3 generates the key union from the YAML. */
export type MetricGuideKey = string

const REGISTRY: Record<string, MetricGuideEntry> = {}
let VERSION = 'local'
let FETCHED = false
const LISTENERS = new Set<() => void>()
const EVENT = 'cc-metric-guide'

export function registerGuide(entries: Record<string, MetricGuideEntry>) {
  Object.assign(REGISTRY, entries)
  LISTENERS.forEach(fn => fn())
}

export function getGuide(key: MetricGuideKey | undefined | null): MetricGuideEntry | null {
  if (!key) return null
  return REGISTRY[key] || null
}

export function guideVersion(): string { return VERSION }

/** Fill `{name}` placeholders from a values object; unknown placeholders are left as-is. */
export function fillGuide(text: string | undefined, values?: Record<string, unknown>): string {
  if (!text) return ''
  if (!values) return text
  return text.replace(/\{([a-zA-Z0-9_]+)\}/g, (m, k) => (values[k] === undefined || values[k] === null ? m : String(values[k])))
}

/** Fetch once per session (idempotent). Cached in localStorage by version. */
export function loadGuideOnce(): Promise<void> {
  if (FETCHED) return Promise.resolve()
  FETCHED = true
  try {
    const cached = localStorage.getItem('cc.metricGuide')
    if (cached) {
      const j = JSON.parse(cached)
      if (j && j.entries) { registerGuide(j.entries); VERSION = String(j.version || 'cached') }
    }
  } catch { /* ignore */ }
  return fetch('/api/v2/ui/metric-guide')
    .then(r => (r.ok ? r.json() : null))
    .then(j => {
      const entries = j && (j.entries || j.guide || j.metrics)
      if (entries && typeof entries === 'object') {
        registerGuide(entries)
        VERSION = String(j.version || 'server')
        try { localStorage.setItem('cc.metricGuide', JSON.stringify({ version: VERSION, entries })) } catch { /* ignore */ }
        window.dispatchEvent(new CustomEvent(EVENT))
      }
    })
    .catch(() => { /* endpoint absent (pre-PR3): local registry stands */ })
}

/** Subscribe to the registry; re-renders when server content lands. */
export function useMetricGuide(key: MetricGuideKey | undefined | null): MetricGuideEntry | null {
  const [, tick] = useState(0)
  useEffect(() => {
    const fn = () => tick(t => t + 1)
    LISTENERS.add(fn)
    window.addEventListener(EVENT, fn)
    loadGuideOnce()
    return () => { LISTENERS.delete(fn); window.removeEventListener(EVENT, fn) }
  }, [])
  return getGuide(key)
}

/** For tests and the coverage gate: keys registered right now. */
export function registeredGuideKeys(): string[] { return Object.keys(REGISTRY).sort() }
