import { useState, type CSSProperties } from 'react'
import { WL, numStyle } from '../lib/watchlistCardTokens'
import {
  acctLabel,
  computeRiskSizedShares,
  deployCapFor,
  resolveEquity,
  resolveSizingBase,
  volatilityRiskSuggestion,
  type ProposalAccount,
  type RiskPct,
} from '../lib/watchlistProposeSizing'

// Sizing & Account Risk module (Security Card v3) — presentation layer over the Propose modal's
// sizing math. Risk basis is ALWAYS available cash / buying power, never total equity (retirement
// hard guard lives in resolveSizingBase). Advisory-only: "size ▸" only opens the Propose modal
// pre-filled; the card never submits an order.

type Held = { account: string; shares: number; market_value: number }

type Props = {
  accounts?: ProposalAccount[]
  heldPositions?: Held[]
  entry: number | null
  stop: number | null
  target: number | null
  /** Only READY / near-entry states offer the size ▸ route into the Propose modal. */
  canPropose: boolean
  /** Desk concentration policy: max % of available cash deployed per position (from proposal-accounts). */
  maxDeployPctOfCash?: number
  onSize?: (accountKey: string, riskPct: RiskPct) => void
}

const label: CSSProperties = {
  fontSize: 10, fontWeight: 700, letterSpacing: '.09em', textTransform: 'uppercase',
  color: WL.text.dim, marginBottom: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
}
const th: CSSProperties = {
  textAlign: 'right', fontSize: 9, textTransform: 'uppercase', letterSpacing: '.06em',
  color: WL.text.dim, fontWeight: 700, padding: '2px 6px', borderBottom: `1px solid ${WL.surface.divider}`,
}
const td: CSSProperties = {
  ...numStyle, padding: '4px 6px', textAlign: 'right', fontSize: 11, color: WL.text.secondary,
  borderBottom: `1px solid ${WL.surface.divider}`,
}

function k(v: number): string {
  return v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`
}

export default function SizingTable({ accounts, heldPositions, entry, stop, target, canPropose, maxDeployPctOfCash, onSize }: Props) {
  const [riskPct, setRiskPct] = useState<RiskPct>(1)

  const header = (
    <div style={label}>
      <span>Sizing &amp; account risk</span>
      <span style={{ display: 'inline-flex', border: '1px solid rgba(148,163,184,.25)', borderRadius: 5, overflow: 'hidden' }}>
        {([1, 2] as RiskPct[]).map(p => (
          <button
            key={p}
            onClick={e => { e.stopPropagation(); setRiskPct(p) }}
            title={p === 2 ? '2% of available cash = desk max risk per position' : '1% of available cash (default)'}
            style={{
              fontSize: 9.5, fontWeight: 800, padding: '2px 8px', border: 'none', cursor: 'pointer',
              background: riskPct === p ? 'rgba(45,212,191,.15)' : 'transparent',
              color: riskPct === p ? WL.signal.teal : WL.text.dim, letterSpacing: 'normal', textTransform: 'none',
            }}
          >{p}%</button>
        ))}
      </span>
    </div>
  )

  const hasPlan = entry != null && stop != null && entry > stop
  if (!hasPlan) {
    return (
      <div>
        {header}
        <div style={{ fontSize: 11, color: WL.text.dim, lineHeight: 1.5 }}>
          Sizing requires a validated plan (limit + stop) — build a plan first.
        </div>
      </div>
    )
  }

  const rows = (accounts ?? [])
    .map(a => ({ a, base: resolveSizingBase(a) }))
    .filter(x => x.base >= 1000)
    .sort((l, r) => r.base - l.base)
    .slice(0, 4)

  if (!rows.length) {
    return (
      <div>
        {header}
        <div style={{ fontSize: 11, color: WL.text.dim, lineHeight: 1.5 }}>
          Account balances unavailable — 1–2% of available cash sizing applies once loaded.
        </div>
      </div>
    )
  }

  const rps = entry! - stop!
  const heldFor = (key: string) => (heldPositions ?? []).find(h => h.account === key) ?? null
  const totalEquity = rows.reduce((s, x) => s + resolveEquity(x.a), 0)
  const sized = rows.map(x => {
    // Per-account cap: the account's own backend policy number (max_position_allocation_pct)
    // wins; the desk-wide fallback only fills in when no policy row exists.
    const cap = deployCapFor(x.a, maxDeployPctOfCash ?? 20)   // {dollars, label} — policy %-of-equity wins
    const pos = computeRiskSizedShares({
      sizingBase: x.base, equity: resolveEquity(x.a), entry: entry!, stop: stop!,
      target: target ?? entry!, riskPct, maxDeployDollars: cap?.dollars,
    })
    const rawBudgetShares = Math.floor((x.base * riskPct / 100) / rps)
    const deployPct = x.base > 0 ? (pos.investment / x.base) * 100 : 0
    return {
      key: x.a.account_key,
      name: x.a.display_name || acctLabel(x.a.account_key),
      base: x.base,
      cap,
      pos,
      deployPct,
      tight: !pos.exceedsCash && pos.shares > 0 && deployPct > 50,
      cashCapped: !pos.concentrationCapped && pos.shares > 0 && pos.shares < rawBudgetShares,
      eq: resolveEquity(x.a),
      held: heldFor(x.a.account_key),
    }
  })
  const topRisk = sized[0]?.pos.dollarRisk ?? 0
  const eqPct = totalEquity > 0 ? (topRisk / totalEquity) * 100 : null
  const holds = sized.filter(r => r.held)
  const anyConcCapped = sized.some(r => r.pos.concentrationCapped)
  const volNote = volatilityRiskSuggestion(entry, stop)

  return (
    <div onClick={e => e.stopPropagation()}>
      {header}
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...th, textAlign: 'left' }}>Account</th>
            <th style={th}>Shares</th>
            <th style={th} title="Capital deployed (shares × limit) — NOT the risk; risk is what you lose at the stop">Deploy</th>
            <th style={th} title="Max loss if stopped out — this is what the 1%/2% applies to">Risk $</th>
            <th style={th} title="Deployment as % of available cash">%Cash</th>
            <th style={th}></th>
          </tr>
        </thead>
        <tbody>
          {sized.map((r, i) => {
            const insufficient = r.pos.exceedsCash || r.pos.shares <= 0
            const last = i === sized.length - 1
            const cell = last ? { ...td, borderBottom: 'none' } : td
            return (
              <tr key={r.key}>
                <td style={{ ...cell, textAlign: 'left', fontFamily: 'inherit', fontVariantNumeric: 'normal', color: WL.text.primary, fontWeight: 600 }}>
                  {r.name}
                </td>
                {insufficient ? (
                  <td colSpan={4} style={{ ...cell, color: WL.signal.amber, fontFamily: 'inherit' }}>exceeds available cash ({k(r.base)}) — reduce size</td>
                ) : (
                  <>
                    <td style={cell} title={
                      r.pos.concentrationCapped ? `capped by the position limit: ${r.cap?.label} ($${((r.cap?.dollars ?? 0) / 1000).toFixed(1)}k)`
                        : r.cashCapped ? `cash-capped from the ${riskPct}% risk budget` : undefined
                    }>
                      {r.pos.shares.toLocaleString()}{r.pos.concentrationCapped || r.cashCapped ? ' ⚠' : ''}
                    </td>
                    <td style={cell}>{k(r.pos.investment)}</td>
                    <td style={cell}>{k(r.pos.dollarRisk)}</td>
                    <td style={cell} title={r.eq > 0 ? `risk ≈${((r.pos.dollarRisk / r.eq) * 100).toFixed(2)}% of this account's equity` : undefined}>
                      {r.base > 0 ? `${r.deployPct.toFixed(1)}%` : '—'}
                      {r.tight
                        ? <span style={{ color: WL.signal.amber, fontWeight: 700, fontFamily: 'inherit' }} title="deployment above 50% of this account's available cash — liquidity is tight"> tight</span>
                        : <span style={{ color: WL.text.dim, fontFamily: 'inherit' }} title="deployment at or below 50% of this account's available cash"> ok</span>}
                    </td>
                  </>
                )}
                <td style={{ ...cell, whiteSpace: 'nowrap' }}>
                  {canPropose && !insufficient ? (
                    <button
                      onClick={e => { e.stopPropagation(); onSize?.(r.key, riskPct) }}
                      title={`Open Propose Entry pre-filled: ${r.name} @ ${riskPct}% risk`}
                      style={{ fontSize: 10.5, fontWeight: 700, color: WL.signal.teal, background: 'none', border: 'none', cursor: 'pointer', padding: 0, fontFamily: 'inherit' }}
                    >size ▸</button>
                  ) : (
                    <span title={canPropose ? undefined : 'sizing is informational until the card is READY (refresh / validate first)'} style={{ color: WL.text.dim, fontSize: 10 }}>·</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: WL.text.dim, marginTop: 5, lineHeight: 1.5 }}
           title="Risk budget = riskPct × available cash (never equity) ÷ stop distance, capped by available cash and the desk deployment limit — identical math to the Propose modal.">
        {riskPct}% = max loss if stopped (${rps.toFixed(2)}/sh) — not capital deployed · sized from available cash × risk% ÷ stop distance
        {eqPct != null && Number.isFinite(eqPct) ? ` · ≈${eqPct.toFixed(2)}% of total equity` : ''}
        {riskPct === 2 ? <span style={{ color: WL.signal.amber, fontWeight: 700 }}> · 2% = desk max</span> : ''}
        {anyConcCapped ? ` · position cap ${sized.find(r => r.pos.concentrationCapped)?.cap?.label}` : ''}
        {volNote && (
          <span style={{ color: WL.signal.amber, fontWeight: 700 }} title="Stop distance is wider than the normal band — same $ risk buys fewer shares; consider reducing effective risk %">
            {' '}· wide stop ({volNote.stopPct.toFixed(1)}%) — consider {volNote.suggestPct}% risk
          </span>
        )}
        {holds.length > 0 && (
          <span style={{ color: WL.signal.amber, fontWeight: 700 }}>
            {' '}· holds: {holds.map(h => `${h.name} ${Math.round(h.held!.shares).toLocaleString()} sh (${k(h.held!.market_value)})`).join(', ')}
          </span>
        )}
      </div>
    </div>
  )
}
