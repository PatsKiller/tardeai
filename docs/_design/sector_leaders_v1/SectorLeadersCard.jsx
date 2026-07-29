/*
 * SectorLeadersCard.jsx  —  REFERENCE IMPLEMENTATION v1
 * Trade AI v12 · Defense Desk (/v3/defense)
 *
 * PURPOSE
 *   Replaces the "RESEARCH WATCH" sector tile. The existing tile terminates at
 *   the ETF. This one descends the same chain the short side already descends:
 *     sector -> confirming industry -> named constituents -> account routing
 *
 * STATUS: reference implementation. Adapt to live schema; do not paste blind.
 *   Every point marked ADAPT: must be reconciled against the running system.
 *
 * DESIGN CONTRACT (do not violate when adapting)
 *   1. Renders nothing that places, stages, or approves an order.
 *   2. Every displayed number is nullable. A missing value renders as an
 *      explicit "unknown" with a reason. It must NEVER render as an em-dash
 *      inside an otherwise-confident sentence. This is the fix for the live
 *      `breadth 55% (56/-- covered)` defect.
 *   3. Ranking and sizing policy are computed server-side. This component
 *      displays a judgment and its inputs; it does not decide what is good.
 *   4. Relative strength shown per name is against its OWN INDUSTRY, not SPY.
 *      Inside a leading sector every name looks strong against SPY; that is
 *      just sector beta arriving. The intra-group measure is the signal.
 */

import React, { useMemo, useState } from 'react';

/* ------------------------------------------------------------------ tokens */
/* ADAPT: confirm these CSS vars exist on /v3/defense. Fallbacks are the
 * observed values from the 2026-07-29 page save. */
const S = {
  panel: 'var(--at-panel, #171b20)',
  panel2: 'var(--at-panel2, #11151a)',
  line: 'var(--at-line, #303740)',
  text: 'var(--at-text, #f3f4f6)',
  muted: 'var(--at-muted, #91a0b4)',
  green: 'var(--at-green, #55d18c)',
  red: 'var(--at-red, #ff746c)',
  blue: 'var(--at-blue, #4b89d8)',
  amber: 'var(--at-amber, #f2bd37)',
  mono: 'var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace)',
};

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const signColor = (v) => (!isNum(v) ? S.muted : v > 0 ? S.green : v < 0 ? S.red : S.muted);
const pct = (v, d = 1) => `${v > 0 ? '+' : ''}${v.toFixed(d)}%`;
const compact = (v) =>
  !isNum(v) ? null
    : v >= 1e9 ? `${(v / 1e9).toFixed(1)}B`
    : v >= 1e6 ? `${Math.round(v / 1e6)}M`
    : v >= 1e3 ? `${Math.round(v / 1e3)}K`
    : String(v);

/* ---------------------------------------------------------------- <Val /> */
/* The null-honesty primitive. Use for EVERY numeric render. */
export function Val({ value, fmt = (v) => v.toFixed(1), suffix = '', reason }) {
  if (!isNum(value)) {
    return (
      <span
        title={reason || 'no source for this value'}
        style={{ color: S.muted, fontStyle: 'italic', fontSize: 12 }}
      >
        unknown
      </span>
    );
  }
  return <>{fmt(value)}{suffix}</>;
}

/* --------------------------------------------------------- derived reads */

export function exposureGap(sector) {
  const held = sector.book_weight_pct;
  const lo = sector.rank_implied_weight_pct?.[0];
  const hi = sector.rank_implied_weight_pct?.[1];
  if (!isNum(held) || !isNum(lo) || !isNum(hi)) return null;
  if (held < lo) return { pp: held - lo, state: 'underweight' };
  if (held > hi) return { pp: held - hi, state: 'overweight' };
  return { pp: 0, state: 'in band' };
}

/* Decides ETF-versus-names, which is the operator's actual question.
 * Low dispersion  -> the ETF captures the move; single-name risk is unpaid.
 * High dispersion -> the ETF dilutes the leaders; names carry the edge.
 * ADAPT: thresholds (12 / 4 / 6) are priors. Move to config once measured. */
export function dispersionVerdict(d) {
  if (!isNum(d?.spread_pp) || !isNum(d?.top_quartile_excess_pp)) return null;
  if (d.spread_pp >= 12 && d.top_quartile_excess_pp >= 4) {
    return {
      tone: 'names',
      text: `Dispersion ${d.spread_pp.toFixed(1)}pp - top names are beating the ETF by `
          + `${d.top_quartile_excess_pp.toFixed(1)}pp. Buy names, not the ETF.`,
    };
  }
  if (d.spread_pp <= 6) {
    return {
      tone: 'etf',
      text: `Dispersion ${d.spread_pp.toFixed(1)}pp - the group moves together. `
          + `The ETF captures it; single-name risk is unpaid here.`,
    };
  }
  return {
    tone: 'mixed',
    text: `Dispersion ${d.spread_pp.toFixed(1)}pp - mixed. Names offer some edge `
        + `over the ETF but not decisively.`,
  };
}

/* ----------------------------------------------------------- subcomponents */

function Chip({ children, tone = 'neutral', title }) {
  const map = {
    neutral: { bg: S.panel2, fg: '#9db0c8' },
    pass: { bg: '#103521', fg: S.green },
    warn: { bg: '#3a2b0d', fg: S.amber },
    bad: { bg: '#3a1a19', fg: S.red },
    info: { bg: '#12233a', fg: S.blue },
  }[tone];
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', minHeight: 24,
      padding: '3px 9px', borderRadius: 6, fontSize: 12,
      background: map.bg, color: map.fg, whiteSpace: 'nowrap',
    }}>{children}</span>
  );
}

function GapStrip({ sector }) {
  const gap = exposureGap(sector);
  const warn = gap && gap.state !== 'in band';
  const bg = warn ? '#3a2b0d' : S.panel2;
  const fg = warn ? S.amber : S.text;

  const cell = (label, node) => (
    <div style={{ flex: 1, background: S.panel, padding: '10px 16px' }}>
      <div style={{ fontSize: 11, color: S.muted }}>{label}</div>
      <div style={{ fontSize: 20, fontFamily: S.mono, marginTop: 4 }}>{node}</div>
    </div>
  );

  return (
    <div style={{ display: 'flex', gap: 1, background: S.line, borderBottom: `1px solid ${S.line}` }}>
      {cell('Your weight', <Val value={sector.book_weight_pct} suffix="%" />)}
      {cell('Rank-implied', isNum(sector.rank_implied_weight_pct?.[0])
        ? `${sector.rank_implied_weight_pct[0]}-${sector.rank_implied_weight_pct[1]}%`
        : <Val value={null} reason="no sizing policy configured for this rank" />)}
      <div style={{ flex: 1.4, background: bg, padding: '10px 16px' }}>
        <div style={{ fontSize: 11, color: fg }}>Exposure gap</div>
        <div style={{ fontSize: 20, fontFamily: S.mono, color: fg, marginTop: 4 }}>
          {gap ? `${gap.pp > 0 ? '+' : ''}${gap.pp.toFixed(1)}pp` : <Val value={null} />}
        </div>
        {warn && (
          <div style={{ fontSize: 11, color: fg, marginTop: 2 }}>
            {gap.state} the #{sector.rank} sector
          </div>
        )}
      </div>
    </div>
  );
}

function ConstituentTable({ industry, onInspect }) {
  const rows = industry.constituents || [];
  if (!rows.length) {
    return (
      <div style={{ padding: '14px 0', color: S.muted, fontSize: 13 }}>
        No constituents passed the liquidity and price filters for this industry.
        {industry.filter_summary ? ` (${industry.filter_summary})` : ''}
      </div>
    );
  }

  const th = { color: S.muted, fontSize: 11, fontWeight: 500, padding: '6px 0', textAlign: 'right' };
  const td = { padding: '9px 0', textAlign: 'right', fontFamily: S.mono, fontSize: 13 };

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
      <thead>
        <tr>
          <th style={{ ...th, textAlign: 'left', width: '17%' }}>Name</th>
          <th style={{ ...th, width: '14%' }}>Price</th>
          <th style={{ ...th, width: '14%' }}
              title="Relative strength against its own industry composite, not against SPY.">
            RS vs ind
          </th>
          <th style={{ ...th, width: '13%' }}>52w high</th>
          <th style={{ ...th, width: '12%' }}>ADV20</th>
          <th style={{ ...th, textAlign: 'left', paddingLeft: 14 }}>Position and flags</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => {
          const lagsGroup = isNum(c.rs_vs_industry) && c.rs_vs_industry < 0;
          return (
            <tr key={c.symbol}
                onClick={() => onInspect?.(c)}
                style={{
                  borderTop: `1px solid ${S.line}`,
                  opacity: lagsGroup ? 0.55 : 1,
                  cursor: onInspect ? 'pointer' : 'default',
                }}>
              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>{c.symbol}</td>
              <td style={td}><Val value={c.price} fmt={(v) => v.toFixed(2)} /></td>
              <td style={{ ...td, color: signColor(c.rs_vs_industry) }}>
                <Val value={c.rs_vs_industry} fmt={(v) => pct(v)}
                     reason="industry-relative RS not computed for this name" />
              </td>
              <td style={td}><Val value={c.pct_from_52w_high} fmt={(v) => pct(v)} /></td>
              <td style={td}>{compact(c.adv_20d) || <Val value={null} reason="no ADV source" />}</td>
              <td style={{ padding: '9px 0 9px 14px', fontSize: 12 }}>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {c.held && (
                    <Chip tone="info" title={`Held in ${c.held.accounts.join(', ')}`}>
                      held <Val value={c.held.book_weight_pct} suffix="%" />
                    </Chip>
                  )}
                  {c.is_core && (
                    <Chip tone="warn" title="Core registry: trim-ladder only, never full exit">
                      core
                    </Chip>
                  )}
                  {lagsGroup && <Chip tone="bad">lags its own group</Chip>}
                  {isNum(c.days_to_earnings) && c.days_to_earnings <= 10 && (
                    <Chip tone="warn">earnings {c.days_to_earnings}d</Chip>
                  )}
                  {c.blocked_accounts?.length > 0 && (
                    <Chip tone="bad" title={c.blocked_reason}>
                      blocked: {c.blocked_accounts.join(', ')}
                    </Chip>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* -------------------------------------------------------------------- card */

export default function SectorLeadersCard({
  sector,
  accounts = [],
  onCreateWatch,
  onOpenEvidence,
  onInspectName,
}) {
  const [openIndustry, setOpenIndustry] = useState(sector.industries?.[0]?.key ?? null);
  const verdict = useMemo(() => dispersionVerdict(sector.dispersion), [sector.dispersion]);
  const stale = isNum(sector.data_age_hours)
    && sector.data_age_hours > (sector.refresh_interval_hours ?? 24);

  const btn = {
    border: `1px solid ${S.line}`, borderRadius: 8, background: '#22272f',
    color: '#c4cedd', padding: '9px 13px', font: 'inherit', fontSize: 13, cursor: 'pointer',
  };

  return (
    <section aria-labelledby={`sector-${sector.key}`}
             style={{ background: S.panel, border: `1px solid ${S.line}`,
                      borderRadius: 16, overflow: 'hidden', color: S.text }}>

      <header style={{ padding: '16px 18px', borderBottom: `1px solid ${S.line}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h3 id={`sector-${sector.key}`} style={{ margin: 0, fontSize: 19 }}>{sector.name}</h3>
          <span style={{ fontFamily: S.mono, fontSize: 14, color: S.muted }}>{sector.etf}</span>
          <Chip tone={sector.rank <= 3 ? 'pass' : 'neutral'}>
            rank {sector.rank} of {sector.rank_total}
            {isNum(sector.rank_change) && sector.rank_change !== 0
              ? ` · ${sector.rank_change > 0 ? 'up' : 'down'} ${Math.abs(sector.rank_change)}`
              : ' · flat'}
          </Chip>
          <Chip tone="neutral">
            {sector.state?.toLowerCase()} · RS20 <Val value={sector.rs20} fmt={(v) => pct(v)} />
          </Chip>
          {stale && (
            <Chip tone="warn"
                  title={`Data is ${sector.data_age_hours}h old against a ${sector.refresh_interval_hours}h interval`}>
              stale {Math.round(sector.data_age_hours)}h
            </Chip>
          )}
        </div>
      </header>

      <GapStrip sector={sector} />

      {verdict && (
        <div style={{
          padding: '11px 18px', borderBottom: `1px solid ${S.line}`, fontSize: 13,
          background: verdict.tone === 'names' ? '#12233a' : S.panel2,
          color: verdict.tone === 'names' ? S.blue : S.muted,
        }}>{verdict.text}</div>
      )}

      {(sector.industries || []).map((ind) => {
        const open = openIndustry === ind.key;
        return (
          <div key={ind.key} style={{ borderBottom: `1px solid ${S.line}` }}>
            <button type="button"
                    onClick={() => setOpenIndustry(open ? null : ind.key)}
                    aria-expanded={open}
                    style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                             padding: '11px 18px', background: 'transparent', border: 0,
                             color: 'inherit', textAlign: 'left', cursor: 'pointer', font: 'inherit' }}>
              <span style={{ fontSize: 14 }}>{ind.name}</span>
              <span style={{ fontSize: 12, color: S.muted, fontFamily: S.mono }}>
                rank {ind.rank}
                {isNum(ind.rank_change) && ind.rank_change !== 0
                  ? ` ${ind.rank_change > 0 ? 'up' : 'dn'}${Math.abs(ind.rank_change)}` : ''}
                {' · '}
                {isNum(ind.constituent_count) ? `${ind.constituent_count} names` : 'count unknown'}
                {isNum(ind.passing_count) ? `, ${ind.passing_count} pass filters` : ''}
              </span>
              <span style={{ marginLeft: 'auto', color: S.muted, fontSize: 12 }}>
                {open ? 'hide' : 'show names'}
              </span>
            </button>
            {open && (
              <div style={{ padding: '0 18px 14px' }}>
                <ConstituentTable industry={ind} onInspect={onInspectName} />
                {ind.source_note && (
                  <div style={{ marginTop: 10, fontSize: 11, color: S.muted }}>{ind.source_note}</div>
                )}
              </div>
            )}
          </div>
        );
      })}

      <footer style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                       padding: '14px 18px', background: S.panel2 }}>
        <span style={{ fontSize: 12, color: S.muted }}>Routable:</span>
        {accounts.map((a) => (
          <Chip key={a.key} tone={a.can_route ? 'neutral' : 'bad'}
                title={a.can_route ? undefined : a.reason}>{a.label}</Chip>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button type="button" style={btn} onClick={() => onOpenEvidence?.(sector)}>Evidence</button>
          <button type="button" style={btn} onClick={() => onCreateWatch?.(sector)}>Create watch</button>
        </div>
      </footer>
    </section>
  );
}
