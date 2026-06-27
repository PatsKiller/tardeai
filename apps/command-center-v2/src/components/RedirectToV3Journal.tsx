import { useEffect } from 'react'

/** v2 journal routes → TradeInView on v3 */
export default function RedirectToV3Journal() {
  useEffect(() => {
    const q = window.location.search || ''
    window.location.replace(`/v3/trade-in-view${q}`)
  }, [])
  return <div style={{ padding: 24, color: 'var(--text2)', fontSize: 12 }}>Redirecting to TradeInView…</div>
}