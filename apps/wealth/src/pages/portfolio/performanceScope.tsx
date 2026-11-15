// Page-published scope choices only. The shell never originates a Performance or holdings read.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
export interface PerformanceScopeChoice { key: string; label: string }
interface ScopeApi { accounts: readonly PerformanceScopeChoice[] | null; reason: string | null; publish: (accounts: readonly PerformanceScopeChoice[] | null, reason: string | null) => void }
const Ctx = createContext<ScopeApi | null>(null)
export function PerformanceScopeProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<readonly PerformanceScopeChoice[] | null>(null)
  const [reason, setReason] = useState<string | null>(null)
  const publish = useCallback((value: readonly PerformanceScopeChoice[] | null, why: string | null) => { setAccounts(value); setReason(why) }, [])
  const value = useMemo(() => ({ accounts, reason, publish }), [accounts, reason, publish])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
export function usePublishPerformanceAccounts(accounts: readonly PerformanceScopeChoice[] | null, reason: string | null) {
  const publish = useContext(Ctx)?.publish
  useEffect(() => { publish?.(accounts, reason) }, [publish, accounts, reason])
  useEffect(() => () => publish?.(null, 'Performance source is not read on this page.'), [publish])
}
export function PerformanceAccountSelect() {
  const publication = useContext(Ctx)
  const accounts = publication?.accounts ?? null
  const reason = publication?.reason ?? null
  const [params, setParams] = useSearchParams()
  const selected = params.get('account') ?? 'ALL'
  const missing = selected !== 'ALL' && !accounts?.some(a => a.key === selected)
  return <select id="account" aria-label="Portfolio account scope" value={selected}
    disabled={accounts === null} title={reason ?? 'Performance source account scope; eligibility is reported separately.'}
    onChange={e => { const next = new URLSearchParams(params); if (e.target.value === 'ALL') next.delete('account'); else next.set('account', e.target.value); setParams(next) }}>
    <option value="ALL">All source accounts{accounts === null ? reason ? ' · unavailable' : ' · reading source' : ''}</option>
    {missing && <option value={selected}>Account not served</option>}
    {accounts?.map(account => <option key={account.key} value={account.key}>{account.label}</option>)}
  </select>
}
