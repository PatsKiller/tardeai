import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { DeskGap } from './DeskPage'
import { refreshMarker, rendersData, surfaceGap, type SurfaceShape, type SurfaceState } from '../lib/surfaceState'

/**
 * The one banner every damaged surface renders, plus the shell's view of the active surface's state.
 *
 * `SurfaceGap` takes the state object — never `!data` — so a page cannot render a failure banner while its data is
 * still arriving. `useReportSurfaceState` publishes the same state to the build-identity footer, which is a fact about
 * the bundle, not about the data (BOARD row 36, rule 7).
 */
export function SurfaceGap<T>({ state, shape, onRetry }: { state: SurfaceState<T>; shape: SurfaceShape<T>; onRetry?: () => void }) {
  const gap = surfaceGap(state, shape)
  const mark = refreshMarker(state, shape)
  if (!gap) return mark ? <p role="status" style={{ margin: 0, opacity: 0.8 }}>{mark.title}</p> : null
  return <DeskGap title={gap.title} reason={gap.reason}>
    {gap.action === 'retry' && onRetry && <button type="button" onClick={onRetry} style={{ minHeight: 44, width: '100%', marginTop: 8 }}>Try again</button>}
  </DeskGap>
}

/** The shell footer reads this: true only when the active surface's data actually rendered. */
export type SurfaceStateReport = { name: string; dataLoaded: boolean }
export type SurfaceStateChannel = { report: SurfaceStateReport | null; publish: (r: SurfaceStateReport | null, clearingFrom?: string) => void }
export const SurfaceStateContext = createContext<SurfaceStateChannel>({ report: null, publish: () => {} })

/**
 * Publish a surface's state to the footer. `dataLoaded` comes from `rendersData`, the SAME predicate the page uses, so
 * the shell and the page cannot hold different opinions about one render (F2 review, 2026-11-04). Unmount clears the
 * slot only if this surface still owns it — a route change must not let the outgoing page erase the incoming one.
 */
export function useReportSurfaceState(name: string, state: SurfaceState<unknown> | null): void {
  const { publish } = useContext(SurfaceStateContext)
  const loaded = rendersData(state)
  const key = `${name}:${state?.state ?? 'none'}:${loaded}`
  useEffect(() => { publish({ name, dataLoaded: loaded }) }, [publish, key, name, loaded])
  // Clearing names the surface doing the clearing, so the provider can ignore a stale unmount from a page that no
  // longer owns the slot (F2 review, 2026-11-04).
  useEffect(() => () => publish(null, name), [publish, name])
}

/** Rendered by DeskPage-adjacent surfaces that do not own a full page frame. */
export function SurfaceNote({ children }: { children: ReactNode }) { return <div role="note">{children}</div> }
