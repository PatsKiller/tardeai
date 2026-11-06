import { useContext, useEffect, useState } from 'react'
import { compareServedBuild, LOADED_BUILD } from '../lib/buildIdentity'
import { SurfaceReportContext } from './SurfaceGap'
import { footerQualifier } from '../lib/surfaceState'

/**
 * The build-identity footer. It is the consumer of the shell's surface report: a page publishes its data state
 * through `useReportSurfaceState`, and this line says whether the artifact matches what the server serves AND whether
 * the active page's data actually rendered. Extracted from App.tsx (finding P1, 2026-11-05) so a mounted test can
 * observe the real consumer rather than reading the shell source as text.
 */
export function BuildMarker() {
  const [served, setServed] = useState<unknown>(null)
  useEffect(() => {
    let cancelled = false
    let inFlight = false
    let controller: AbortController | null = null
    const check = async () => {
      if (inFlight) return
      inFlight = true
      controller = new AbortController()
      const timer = window.setTimeout(() => controller?.abort(), 5000)
      try {
        const response = await fetch('/v3/build-meta.json', { cache: 'no-store', signal: controller.signal })
        if (!response.ok) throw new Error('build metadata unavailable')
        const metadata: unknown = await response.json()
        if (!cancelled) setServed(metadata)
      } catch {
        if (!cancelled) setServed(null)
      } finally {
        window.clearTimeout(timer)
        inFlight = false
      }
    }
    const visible = () => { if (document.visibilityState === 'visible') void check() }
    void check()
    const interval = window.setInterval(() => { if (document.visibilityState === 'visible') void check() }, 60_000)
    document.addEventListener('visibilitychange', visible)
    return () => {
      cancelled = true
      controller?.abort()
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [])
  const comparison = compareServedBuild(LOADED_BUILD, served)
  // BOARD row 36, rule 7: this line is a fact about the BUNDLE, never about the page's data. A page whose data did
  // not load must not sit under a bare "Running the artifact the server serves" — that reads as "everything is
  // fine", so the active page's data state is appended as a qualifier and exposed as data-surface-loaded.
  const surface = useContext(SurfaceReportContext)
  const qualifier = footerQualifier(surface)
  // FQ-081: the bundle id, build date and source revision are technical identifiers, not something an operator reads
  // in the footer. The one operator-facing fact stays visible — whether this tab is running the artifact the server is
  // serving — and the identifiers move one tap away. data-source-sha stays on the element: it is machine-read.
  return <span data-testid="cc-loaded-build" data-source-sha={LOADED_BUILD.sourceSha ?? 'UNAVAILABLE'} data-surface-loaded={surface ? String(surface.dataLoaded) : 'unknown'}>
    {comparison === 'SAME' ? `Running the artifact the server serves${qualifier}` : comparison === 'UNAVAILABLE' ? 'Served build comparison UNAVAILABLE' : <>
      newer or different artifact available · <button type="button" onClick={() => window.location.reload()}>Reload Command Center</button>
    </>}
    {' · '}<details data-testid="build-diagnostics" style={{ display: 'inline-block' }}>
      <summary style={{ cursor: 'pointer', display: 'inline' }}>Diagnostics</summary>
      <span style={{ display: 'block' }}>
        Loaded bundle: {LOADED_BUILD.uiVersion ?? 'UNAVAILABLE'} · built {LOADED_BUILD.builtAt ?? 'UNAVAILABLE'} · source {LOADED_BUILD.sourceSha?.slice(0, 12) ?? 'UNAVAILABLE'}
      </span>
    </details>
  </span>
}
