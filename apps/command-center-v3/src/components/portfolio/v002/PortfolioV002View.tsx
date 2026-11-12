// Portfolio v002 (design/pages/portfolio/v002, operator-approved with amendments 2026-11-11) — main view.
// Phone order (390/412): header -> Action·Protection -> Validation gates -> Since last visit -> Portfolio status
// -> Holdings -> Details. Every block shows its age; UNKNOWN is never drawn as NO STOP; NEEDS BACKEND marks
// blocks with no production source in this build.
import { Link } from 'react-router-dom'
import {
  fmtAge, fmtET, fmtPct, fmtShares, fmtUsd, filterPositions, STOP_OWNER,
  type HoldingsFilter, type P0Item, type PositionModel, type ProtectionModel, type Read, type HoldingsWire, type StatusRow,
} from '../../../lib/portfolioV002'
import './PortfolioV002.css'

export const NB = ({ short }: { short?: boolean }) => (
  <span className="pv2-nb" title="Backend support not yet available">{short ? 'NB' : 'NEEDS BACKEND'}</span>
)

export function stateClass(s: string): string {
  if (s === 'OK' || s === 'PROTECTED' || s === 'CLEAR') return 'ok'
  if (s === 'WARN' || s === 'STALE' || s === 'MEDIUM' || s === 'EXPIRED') return 'warn'
  if (s === 'GAP' || s === 'NO STOP' || s === 'TIMED OUT') return 'bad'
  return 'neutral'
}
const rowChipClass = (p: PositionModel) =>
  p.protection === 'PROTECTED' ? 'ok' : p.protection === 'GAP' ? 'bad' : p.protection === 'WARN' ? 'warn' : 'neutral'

export interface ViewProps {
  holdings: Read<HoldingsWire>; positions: PositionModel[]; prot: ProtectionModel; p0: P0Item[] | null; status: StatusRow[]
  nowIso: string; filter: HoldingsFilter; account: string; showAll: boolean; showAllAction: boolean
  onFilter: (f: HoldingsFilter) => void; onAccount: (a: string) => void; onShowAll: () => void; onShowAllAction: () => void
  onOpenWhy: () => void; onOpenDiag: () => void; onOpenAudit: () => void; onOpenPosition: (key: string) => void
}

const ACTION_LIMIT = 6
const HOLDINGS_LIMIT = 25

function verdictLabel(v: ProtectionModel['verdict']): string {
  return v === 'LOADING' ? 'reading…' : v
}

export default function PortfolioV002View(props: ViewProps) {
  const { holdings, positions, prot, p0, status, nowIso, filter, account } = props
  const w = holdings.data
  const total = holdings.state === 'OK' ? w?.total_value ?? null : null
  const accounts = [...new Set(positions.map(p => p.account))].sort()
  const visible = filterPositions(positions, filter, account)
  const shown = props.showAll ? visible : visible.slice(0, HOLDINGS_LIMIT)
  const action = props.showAllAction ? prot.action : prot.action.slice(0, ACTION_LIMIT)
  const counts = {
    unprotected: positions.filter(p => p.counted && (p.protection === 'GAP' || p.protection === 'WARN')).length,
    unknown: positions.filter(p => p.counted && p.protection === 'UNKNOWN').length,
    under100: positions.filter(p => p.underFloor).length,
  }
  const verdictCls = prot.verdict === 'OK' ? 'ok' : prot.verdict === 'GAP' ? 'bad' : prot.verdict === 'WARN' ? 'warn' : 'neutral'

  return (
    <div className="pv2" data-testid="portfolio-v002">
      {/* Header: value · time ET · Protection chip -> why · P0 · Gates · Ask */}
      <header className="pv2-hdr">
        <div className="pv2-hdr-main">
          <div className="pv2-hdr-t">
            <h1 className="pv2-title">Portfolio</h1>
            <span className="pv2-age" data-testid="hdr-value">· {total == null ? (holdings.state === 'LOADING' ? 'reading…' : 'value UNKNOWN') : fmtUsd(total)}</span>
            <span className="pv2-age">· {fmtET(nowIso, true)} ET</span>
          </div>
          <div className="pv2-chips">
            <button type="button" className={`pv2-chip-btn ${verdictCls}`} id="chip-protection" data-testid="chip-protection"
              onClick={props.onOpenWhy} aria-label={`Protection: ${verdictLabel(prot.verdict)}. Open why`}>
              Protection: {verdictLabel(prot.verdict)} ›
            </button>
            <span className={`pv2-chip ${p0 == null ? 'neutral' : p0.length ? 'bad' : 'neutral'}`} data-testid="chip-p0">
              {p0 == null ? 'P0 ?' : `${p0.length} P0`}
            </span>
            <span className="pv2-chip neutral" data-testid="chip-gates">Gates — <NB short /></span>
          </div>
        </div>
        <Link className="pv2-ask" to="/cio" aria-label="Ask the CIO">Ask</Link>
      </header>

      <div className="pv2-grid">
        <div className="pv2-col">
          {/* Action · Protection */}
          {prot.verdict === 'OK' ? (
            <div className="pv2-collapsed" id="card-protect" data-testid="card-protect">
              <span className="pv2-chip ok">CLEAR</span>
              <span className="pv2-txt">{prot.protectedN} of {prot.counted} protected</span>
              <span className="pv2-age pv2-push">read {fmtET(prot.oldestRead)} · {prot.brokers.length} broker{prot.brokers.length === 1 ? '' : 's'} with counted positions</span>
            </div>
          ) : (
            <section className="pv2-blk" id="card-protect" data-testid="card-protect">
              <div className="pv2-blk-h">
                <h2 className="pv2-h2">Action · Protection</h2>
                <span className="pv2-age">{prot.oldestRead ? `oldest stop read ${fmtET(prot.oldestRead)} · ${fmtAge(Date.parse(nowIso) - Date.parse(prot.oldestRead))}` : holdings.state === 'OK' ? 'no resting stop read' : ''}</span>
              </div>
              {prot.verdict === 'LOADING' || prot.verdict === 'TIMED OUT' || (prot.verdict === 'UNKNOWN' && !prot.counted) ? (
                <div className={`pv2-unk ${prot.verdict === 'TIMED OUT' ? 'bad' : ''}`} data-testid="protect-unread">
                  {prot.verdict === 'LOADING' ? 'Reading holdings…' : `Protection ${prot.verdict}: ${prot.cause || 'holdings not read'}. Nothing here is drawn as NO STOP.`}
                </div>
              ) : (
                <>
                  <div className="pv2-tiles" id="prot-tiles">
                    <button type="button" className="pv2-tile ok" onClick={props.onOpenWhy}><span className="k">Protected</span><span className="n">{prot.protectedN}</span></button>
                    <button type="button" className="pv2-tile bad" onClick={() => props.onFilter('unprotected')}><span className="k">Unprotected</span><span className="n">{(prot.gap ?? 0) + (prot.warn ?? 0)}</span></button>
                    <button type="button" className="pv2-tile unk" onClick={() => props.onFilter('unknown')}><span className="k">Unknown</span><span className="n">{prot.unknown}</span></button>
                  </div>
                  <div className="pv2-pt-h" aria-hidden="true"><span>Symbol</span><span>Stop status</span><span>Last verified</span><span className="r">Action</span></div>
                  <div id="prot-rows">
                    {groupByCause(action).map(g => (
                      <div key={g.cause}>
                        {g.rows.map(p => (
                          <div className="pv2-prow" key={p.key} data-testid="prot-row">
                            <button type="button" className="pv2-prow-main" onClick={() => props.onOpenPosition(p.key)} aria-label={`${p.symbol} ${p.chip}. Open detail`}>
                              <span className="sym">{p.symbol}</span>
                              <span><span className={`pv2-chip ${rowChipClass(p)}`}>{p.chip}</span></span>
                              <span className="ver">{p.verifiedAt ? fmtET(p.verifiedAt, true) : 'never'} · {p.account}</span>
                            </button>
                            {p.protection === 'GAP' || p.protection === 'WARN'
                              ? <Link className="pv2-act" to={`/portfolio-classic?tab=Stop+Management&symbol=${encodeURIComponent(p.symbol)}`}>Place stop ›</Link>
                              : <button type="button" className="pv2-act" onClick={() => props.onOpenPosition(p.key)}>Verify ›</button>}
                          </div>
                        ))}
                        <div className="pv2-own">Cause: <b>{g.cause}</b> · Source: <b>{g.source}</b> · Owner: <b>{g.owner}</b></div>
                      </div>
                    ))}
                    {prot.action.length > ACTION_LIMIT && !props.showAllAction && (
                      <button type="button" className="pv2-more" onClick={props.onShowAllAction}>{prot.action.length - ACTION_LIMIT} more ›</button>
                    )}
                  </div>
                </>
              )}
            </section>
          )}

          {/* Validation gates — no gate store in this build */}
          <section className="pv2-blk" id="card-gates" data-testid="card-gates">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Validation gates <NB /></h2><span className="pv2-age">not available</span></div>
            <p className="pv2-muted">Gate store not served for Portfolio (scope=portfolio, LQ-2141).</p>
          </section>

          {/* Since your last visit — no portfolio.last_seen / change store in this build */}
          <section className="pv2-blk" id="card-since" data-testid="card-since">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Since your last visit <NB /></h2><span className="pv2-age">not available</span></div>
            <p className="pv2-muted">Needs portfolio.last_seen (G13) and the change store (LQ-2143).</p>
          </section>

          {/* Portfolio status */}
          <section className="pv2-blk" id="card-status" data-testid="card-status">
            <div className="pv2-blk-h">
              <h2 className="pv2-h2">Portfolio status <span className="pv2-age pv2-plain">· {holdings.at ? fmtET(holdings.at) : '—'}</span></h2>
              <button type="button" className="pv2-lnk" onClick={props.onOpenDiag} data-testid="open-diag">Diagnostics ›</button>
            </div>
            {status.map(r => (
              <div className="pv2-st" id={r.id} key={r.id} data-testid={r.id}>
                <div className="s1">
                  <span className="n">{r.name}</span>
                  <span><span className={`pv2-chip ${stateClass(r.state)}`}>{r.state === 'LOADING' ? '…' : r.state}</span></span>
                  <span className="sub">{r.text} {r.needsBackend && <NB short />}</span>
                </div>
                {r.cause && <div className="pv2-own">{r.cause}</div>}
              </div>
            ))}
          </section>
        </div>

        <div className="pv2-col">
          {/* Holdings */}
          <section className="pv2-blk" id="card-holdings" data-testid="card-holdings">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Holdings · {holdings.state === 'OK' ? positions.length : '—'}</h2><span className="pv2-age">by value</span></div>
            {holdings.state !== 'OK' ? (
              <div className="pv2-unk">{holdings.state === 'LOADING' ? 'Reading holdings…' : `Holdings ${holdings.state}: ${holdings.error || ''}`}</div>
            ) : (
              <>
                <label className="pv2-sel">
                  <span className="pv2-sr">Account</span>
                  <select value={account} onChange={e => props.onAccount(e.target.value)} data-testid="acct-select">
                    <option value="all">All accounts ({accounts.length})</option>
                    {accounts.map(a => <option key={a} value={a}>{a}</option>)}
                  </select>
                </label>
                <div className="pv2-fchips" role="group" aria-label="Filter holdings">
                  {([['all', 'All', null], ['unprotected', 'Unprotected', counts.unprotected], ['unknown', 'Unknown', counts.unknown], ['under100', 'Under $100', counts.under100]] as const).map(([k, label, n]) => (
                    <button type="button" key={k} className={`pv2-fchip ${filter === k ? 'on' : ''}`} aria-pressed={filter === k} onClick={() => props.onFilter(k)}>
                      {label}{n != null ? ` ${n}` : ''}
                    </button>
                  ))}
                </div>
                <div className="pv2-hl-h" aria-hidden="true"><span>Symbol</span><span className="r">Shares</span><span className="r">Value</span><span>Protection</span><span>Risk</span></div>
                {shown.map(p => (
                  <button type="button" className="pv2-hrow" key={p.key} onClick={() => props.onOpenPosition(p.key)} data-testid="holding-row">
                    <span className="c1"><b>{p.symbol}</b><span className="s2">{p.account} · <span className={p.dayPct == null ? '' : p.dayPct >= 0 ? 'up' : 'dn'}>{fmtPct(p.dayPct)}</span>{p.underFloor ? ' · under $100' : ''}</span></span>
                    <span className="num">{fmtShares(p.shares)}</span>
                    <span className="num">{fmtUsd(p.value)}</span>
                    <span><span className={`pv2-chip ${rowChipClass(p)}`}>{p.isCash && p.protection === 'EXEMPT' ? 'CASH' : p.chip}</span></span>
                    <span className="risk" title="Risk score: NEEDS BACKEND (G7)">—</span>
                  </button>
                ))}
                {visible.length === 0 && <p className="pv2-muted">No holdings match this filter.</p>}
                {visible.length > shown.length && (
                  <button type="button" className="pv2-more" onClick={props.onShowAll}>{visible.length - shown.length} more ›</button>
                )}
                <p className="pv2-muted">Risk column: score not defined yet <NB short /> · tap a row for its full-screen detail</p>
              </>
            )}
          </section>

          {/* Details: replaces the 8 tabs (R3); each opens a full-screen sheet or the classic desk */}
          <section className="pv2-blk" id="card-details" data-testid="card-details">
            <div className="pv2-blk-h"><h2 className="pv2-h2">Details</h2></div>
            <button type="button" className="pv2-det" onClick={props.onOpenAudit} data-testid="open-audit"><span>Audit state</span><span>›</span></button>
            <Link className="pv2-det" to="/portfolio-classic?tab=Allocation"><span>Allocation · Look-through</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Returns"><span>Returns · Dividends · Forecast</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Tax"><span>Tax lots</span><span>›</span></Link>
            <Link className="pv2-det" to="/portfolio-classic?tab=Stop+Management"><span>Stop management desk</span><span>›</span></Link>
            <Link className="pv2-det" to="/rotation"><span>Rotation review</span><span>›</span></Link>
            <Link className="pv2-det" to="/redeploy"><span>Redeploy desk</span><span>›</span></Link>
            <div className="pv2-det pv2-retired" data-testid="retired-fidelity"><span>Fidelity GTC stop sync</span><span className="pv2-chip neutral">Retired</span></div>
            <Link className="pv2-det" to="/portfolio-classic" data-testid="classic-link"><span>Classic Portfolio page (sync, export, stop audit)</span><span>›</span></Link>
          </section>
        </div>
      </div>
    </div>
  )
}

function groupByCause(rows: PositionModel[]): { cause: string; source: string; owner: string; rows: PositionModel[] }[] {
  const out: { cause: string; source: string; owner: string; rows: PositionModel[] }[] = []
  for (const p of rows) {
    const cause = p.cause || 'Protection Unknown'
    const last = out[out.length - 1]
    if (last && last.cause === cause) last.rows.push(p)
    else out.push({ cause, source: 'stop store', owner: STOP_OWNER, rows: [p] })
  }
  return out
}
