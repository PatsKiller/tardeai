import { useEffect, useState } from 'react'

/**
 * True while the viewport is at or below `maxWidth` (default 820px — the same breakpoint every other
 * phone switch in the app uses: MobileDetailSheet, HoldingHistory, ProspectusPage, AskCio, StreetBlocks).
 * A phone in landscape (~812-844px) and an iPad Mini in portrait (768px) must get the same layout as a
 * phone held upright, or the tables render at desktop width exactly in the band this hook exists for.
 *
 * Read at first render, then followed with matchMedia so a rotation or a window resize re-renders.
 * Client-only app (Vite SPA): there is no server render to disagree with.
 */
export function useNarrowViewport(maxWidth = 820): boolean {
  const query = `(max-width: ${maxWidth}px)`
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false,
  )
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(query)
    const onChange = () => setNarrow(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return narrow
}
