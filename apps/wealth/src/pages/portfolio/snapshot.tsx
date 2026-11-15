// One read, one snapshot, two consumers: the page that owns the read publishes it here, and the shell's top
// bar renders the same book — same scope, same clock — instead of a second fetch.
//
// Why the provider holds no fetch: `/api/v2/portfolio/holdings` is a HEAVY reader (api/readers.ts), and the
// shell refuses a heavy read (`HeavyReaderFromShell`). So the page (`HoldingsLive`) still performs the one
// read and publishes its props; this module only carries them. On any other route the bar says the book is not
// read here — it does not fetch, and it does not invent. That is enforced twice: this module withdraws the
// snapshot when the owning page unmounts (`usePublishBook`), and the bar itself refuses a snapshot published on
// another route (`bookView.barStatus`). Measured failure that made both necessary: cc-deepseek-3's verdict
// 2026-11-15T04:48Z §8 — after a client-side navigation from Holdings to Home the bar kept the book and its clock.
//
// The scope lives here too, because it is one selection: the top bar changes it, the page filters on it.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { HoldingsProps } from './liveProps'
import type { Scope } from './scope'
import { PerformanceScopeProvider } from './performanceScope'

export interface SnapshotApi {
  /** What the owning page has published; null before its first answer (or on a route that does not read). */
  props: HoldingsProps | null
  publish: (p: HoldingsProps) => void
  /** Withdraw the snapshot: called when the owning page unmounts, so no other route can render its numbers. */
  clear: () => void
  scope: Scope
  setScope: (s: Scope) => void
}

const Ctx = createContext<SnapshotApi | null>(null)

export function BookSnapshotProvider({ children }: { children: ReactNode }) {
  const [props, setProps] = useState<HoldingsProps | null>(null)
  const [scope, setScope] = useState<Scope>('ALL')
  // Republishing the same answer must not re-render the tree (a publish that always set a fresh object would
  // loop: provider state changes → the page re-renders → it publishes again). Same four values ⇒ same state.
  const publish = useCallback(
    (p: HoldingsProps) =>
      setProps(prev =>
        prev !== null && prev.book === p.book && prev.loading === p.loading && prev.error === p.error && prev.notice === p.notice ? prev : p,
      ),
    [],
  )
  // Stable identity: `usePublishBook`'s unmount effect depends on it, so a new function per render would run the
  // cleanup and withdraw the book on every render.
  const clear = useCallback(() => setProps(null), [])

  // A scope that the current book does not contain falls back to ALL: the selector never names an account the
  // read did not serve, and a stale selection must not filter every row out silently.
  const book = props?.book ?? null
  useEffect(() => {
    if (book === null || scope === 'ALL') return
    if (!book.rows.some(r => r.accountKey === scope)) setScope('ALL')
  }, [book, scope])

  const value = useMemo<SnapshotApi>(() => ({ props, publish, clear, scope, setScope }), [props, publish, clear, scope])
  return <PerformanceScopeProvider><Ctx.Provider value={value}>{children}</Ctx.Provider></PerformanceScopeProvider>
}

/** For the shell's top bar: always inside the provider. */
export function useBookSnapshot(): SnapshotApi {
  const api = useContext(Ctx)
  if (api === null) throw new Error('useBookSnapshot outside BookSnapshotProvider')
  return api
}

/**
 * For a page that may render with or without the shell's provider (a unit render, a fixture demo). Outside the
 * provider the scope is local state, so the page still filters — it simply has no top bar to share it with.
 */
export function useBookScope(): { scope: Scope; setScope: (s: Scope) => void } {
  const api = useContext(Ctx)
  const [local, setLocal] = useState<Scope>('ALL')
  return api === null ? { scope: local, setScope: setLocal } : { scope: api.scope, setScope: api.setScope }
}

/** For the page that owns the read: publish what it just computed, exactly once per changed answer. */
export function usePublishBook(p: HoldingsProps): void {
  const api = useContext(Ctx)
  const publish = api?.publish ?? null
  const clear = api?.clear ?? null
  useEffect(() => {
    if (publish !== null) publish(p)
  }, [publish, p])
  // Withdraw on unmount — and ONLY on unmount: `clear` is stable, so this cleanup does not run when `p` changes
  // (a republish would otherwise clear the bar for a render). After a client-side navigation the bar therefore
  // says the book is not read here instead of keeping the previous page's numbers.
  useEffect(() => {
    return () => {
      if (clear !== null) clear()
    }
  }, [clear])
}
