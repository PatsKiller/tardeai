/**
 * Stub hook so Watch-only builds don't fail when re-entry desk is not wired.
 * Full implementation lives on re-entry feature branches.
 */
export function useReentryDecisionDesk(_opts?: unknown): {
  data: null
  loading: boolean
  error: null
  refresh: () => void
} {
  return {
    data: null,
    loading: false,
    error: null,
    refresh: () => {},
  }
}

export default useReentryDecisionDesk
