/** Click any ticker → the Investment Opportunity modal (operator 2026-10-08).
 *  <OpportunityModalProvider> sits in the App shell; useOpenSymbol() opens it from anywhere; <SymbolLink> renders a
 *  clickable ticker (stops propagation so a click inside a card does not also select the card). The URL parameter
 *  ?opp=SYMBOL opens it too — Telegram opportunity lines link there. */
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { FONT } from '../../lib/designTokens'

const OpportunityModal = lazy(() => import('./OpportunityModal'))

type Ctx = { open: (symbol: string) => void }
const OpportunityCtx = createContext<Ctx>({ open: () => {} })

export function useOpenSymbol() {
  return useContext(OpportunityCtx).open
}

export function OpportunityModalProvider({ children }: { children: ReactNode }) {
  const [symbol, setSymbol] = useState<string | null>(null)
  const [sp, setSp] = useSearchParams()
  const opp = sp.get('opp')
  useEffect(() => { if (opp) setSymbol(opp.toUpperCase()) }, [opp])
  // Moving to another page always closes the modal (it must never sit over a page you navigated to).
  const { pathname } = useLocation()
  useEffect(() => { if (!opp) setSymbol(null) }, [pathname])  // eslint-disable-line react-hooks/exhaustive-deps
  const open = useCallback((s: string) => { if (s) setSymbol(String(s).toUpperCase()) }, [])
  const close = useCallback(() => {
    setSymbol(null)
    if (sp.get('opp')) { const next = new URLSearchParams(sp); next.delete('opp'); setSp(next, { replace: true }) }
  }, [sp, setSp])
  return (
    <OpportunityCtx.Provider value={{ open }}>
      {children}
      {symbol && (
        <Suspense fallback={null}>
          <OpportunityModal symbol={symbol} onClose={close} onOpenSymbol={open} />
        </Suspense>
      )}
    </OpportunityCtx.Provider>
  )
}

export function SymbolLink({ symbol, children, title }: { symbol: string; children?: ReactNode; title?: string }) {
  const open = useOpenSymbol()
  return (
    <button type="button" data-symbol-link={symbol}
      title={title || `Open ${symbol} — investment opportunity`}
      onClick={(e) => { e.stopPropagation(); e.preventDefault(); open(symbol) }}
      style={{ all: 'unset', cursor: 'pointer', fontFamily: FONT.mono, fontWeight: 800, color: 'inherit', textDecoration: 'underline dotted', textUnderlineOffset: 3 }}>
      {children ?? symbol}
    </button>
  )
}
