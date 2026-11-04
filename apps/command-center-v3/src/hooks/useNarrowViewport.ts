import { useEffect, useState } from 'react'

/**
 * True while the viewport is at or below `maxWidth` (default 760px — a phone held upright, and the
 * width below which the desk tables cannot show their columns without sideways scrolling).
 *
 * Read at first render, then followed with matchMedia so a rotation or a window resize re-renders.
 * Client-only app (Vite SPA): there is no server render to disagree with.
 */
export function useNarrowViewport(maxWidth = 760): boolean {
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
