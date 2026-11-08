/* Ops › Jobs & n8n › n8n catalog: the operator-APPROVED design (artifact "n8n Lane Configuration",
   https://claude.ai/artifact/3YEqk8nVTHM85JHnx6Gukg), rendered verbatim: same markup, same CSS, same tooltips.
   Generated from the approved HTML; only the data source changed: live GET /api/v2/ops/n8n-catalog. Read-only.
   LQ-20261107-180: the page is split into deep-linkable subtabs (?tab=catalog&sub=overview|lanes|audit). Every number
   and time comes from the live GET (refreshed each minute) and the page states its own "as of" time in ET. */
export const APPROVED_CSS = "\n:host{--bg:#f6f7f5;--fg:#1c2320;--muted:#5c6862;--line:#d7dcd8;--card:#fff;--live:#1f7a4d;--shadow:#a5650b;--dry:#4f6f8f;--chip:#eef1ee;--bad:#b3261e}\n@media (prefers-color-scheme:dark){:host(:not([data-theme=\"light\"])){--bg:#131715;--fg:#e3e8e4;--muted:#98a49d;--line:#2b332f;--card:#1a1f1c;--live:#5cc28d;--shadow:#e0a84a;--dry:#8fb3d6;--chip:#232a26;--bad:#f2867c;color-scheme:dark}}\n:host([data-theme=\"dark\"]){--bg:#131715;--fg:#e3e8e4;--muted:#98a49d;--line:#2b332f;--card:#1a1f1c;--live:#5cc28d;--shadow:#e0a84a;--dry:#8fb3d6;--chip:#232a26;--bad:#f2867c;color-scheme:dark}\n.page{background:var(--bg);color:var(--fg);font:15px/1.5 \"IBM Plex Sans\",system-ui,sans-serif;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}\nmain{max-width:800px;margin:0 auto;display:flex;flex-direction:column;gap:16px}\nh1{font-size:1.5rem;margin:0;text-wrap:balance}.sub{color:var(--muted);font-size:.85rem}\n.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}\n.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}\n.stat b{display:block;font:500 1.5rem \"IBM Plex Mono\",monospace}.stat span{font-size:.78rem;color:var(--muted)}\n.key{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;font-size:.88rem;display:flex;flex-direction:column;gap:4px}\ndetails{background:var(--card);border:1px solid var(--line);border-radius:8px}\nsummary{cursor:pointer;padding:12px 14px;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;list-style:none}\nsummary::-webkit-details-marker{display:none}\nsummary h2{font-size:1.02rem;margin:0;flex:1 1 200px}\n.bar{display:flex;gap:6px;flex-wrap:wrap;font:500 .78rem \"IBM Plex Mono\",monospace}\n.pill{padding:2px 8px;border-radius:99px;background:var(--chip)}\n.live{color:var(--live)}.shadow{color:var(--shadow)}.dry{color:var(--dry)}.none{color:var(--muted)}\n.body{padding:0 14px 12px;display:flex;flex-direction:column;gap:12px}\n.blurb{color:var(--muted);font-size:.86rem;margin:0}\nh3{font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;margin:0 0 4px}\nul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}\nli{padding:7px 0;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:1px;min-width:0}\n.row{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}\n.t{font-weight:600}.c{font:.76rem \"IBM Plex Mono\",monospace;color:var(--muted);overflow-wrap:anywhere}\n.d{font-size:.86rem;color:var(--muted)}\n.flag{font-size:.72rem;color:var(--shadow)}\n.bad{color:var(--bad)}.vb{font:600 .7rem \"IBM Plex Mono\",monospace;padding:1px 6px;border-radius:4px;background:var(--chip)}.def{font-size:.8rem;color:var(--fg);border-left:3px solid var(--bad);padding-left:8px;margin-top:2px;overflow-wrap:anywhere}\n[data-tip]{cursor:help}.tipbox{position:fixed;left:max(12px,env(safe-area-inset-left,0px));right:max(12px,env(safe-area-inset-right,0px));bottom:calc(76px + env(safe-area-inset-bottom,0px));max-width:640px;margin:0 auto;background:var(--fg);color:var(--bg);border-radius:10px;padding:12px 40px 12px 14px;font-size:.9rem;line-height:1.45;box-shadow:0 6px 24px rgba(0,0,0,.3);z-index:20}.tipbox button{position:absolute;top:6px;right:8px;background:none;border:0;color:inherit;font-size:1.2rem;cursor:pointer}"
/** Additions for the subtab layout (LQ-20261107-180), in the approved palette and type only. */
export const SUBTAB_CSS = `
.tabs{display:flex;gap:6px;overflow-x:auto;padding:2px 0 4px;margin:0;scrollbar-width:thin;-webkit-overflow-scrolling:touch}
.tabs button{flex:0 0 auto;min-height:44px;padding:0 16px;border-radius:99px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:600 .88rem "IBM Plex Sans",system-ui,sans-serif;cursor:pointer}
.tabs button[aria-selected="true"]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.asof{color:var(--muted);font-size:.78rem;margin:0}
.counts{display:flex;flex-wrap:wrap;gap:6px}
.counts button,.fchips button{min-height:44px;padding:0 12px;border-radius:99px;border:1px solid var(--line);background:var(--chip);font:500 .8rem "IBM Plex Mono",monospace;cursor:pointer;color:var(--fg)}
.counts button b{font-weight:600}
.fchips{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px}
.fchips button{flex:0 0 auto}.fchips button[aria-pressed="true"]{border-color:var(--fg);background:var(--card)}
.search{width:100%;box-sizing:border-box;min-height:44px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit}
.health{display:flex;gap:6px;flex-wrap:wrap;font:500 .74rem "IBM Plex Mono",monospace}
.health span{padding:1px 7px;border-radius:4px;background:var(--chip)}
.tally{color:var(--muted);font-size:.8rem;margin:0}
a.lane{color:inherit;text-decoration:none;display:flex;flex-direction:column;gap:1px;min-height:44px;justify-content:center}
button.stat{font:inherit;color:inherit;text-align:left;cursor:pointer;width:100%;display:flex;flex-direction:column;gap:2px;min-height:44px}
button.stat:active{border-color:var(--fg)}
.stat .ib{font-style:normal;padding:0 4px;cursor:help}
.stat .hint{font-style:normal;font-size:.72rem;color:var(--muted)}
.empty{color:var(--muted);font-size:.9rem;padding:12px 14px;background:var(--card);border:1px solid var(--line);border-radius:8px;margin:0}
.lanes{display:flex;flex-direction:column;gap:2px;margin-top:2px}
.banner{margin:0;padding:8px 10px;border-left:4px solid var(--shadow);background:var(--card);font-size:.88rem}
.acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.rerun,.acts a{min-height:44px;display:inline-flex;align-items:center;padding:0 14px;border-radius:8px;font:600 .8rem "IBM Plex Sans",system-ui,sans-serif}
.rerun{border:1px dashed var(--line);background:var(--chip);color:var(--muted)}
.acts a{border:1px solid var(--line);background:var(--card);color:var(--fg);text-decoration:none}
`
export const SUBTABS = [['overview', 'Overview'], ['lanes', 'Lanes'], ['audit', 'Audit'], ['llm', 'LLM use'], ['fixes', 'Fixes']] as const
export type SubKey = typeof SUBTABS[number][0]
export const resolveSub = (s: string | null | undefined): SubKey => (SUBTABS.some(([k]) => k === s) ? s as SubKey : 'overview')

const MODE: Record<string, string> = { live: 'live', both: 'shadow', dry: 'dry' }
export const etFmt = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) + ' ET'
}
export const esc = (s: unknown): string => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))

export const TIP: Record<string, string> = {
  live: 'Live on n8n: n8n is the only scheduler and the cron line is retired. Being live does not prove the data is right; check the audit verdict.',
  shadow: 'n8n + cron (both): both schedulers are set. They share a lock, so whichever fires first runs and the other skips. The cron line is retired only after a verified live n8n run.',
  dry: 'Dry run on n8n: n8n runs it in report-only mode and writes nothing. It shows what the lane would do before the cutover.',
  none: 'Not on n8n: stays on cron or systemd. That covers broker reads and writes, the send class, always-on services, and anything not migrated yet.',
}
export const VTIP: Record<string, string> = {
  PASS: 'PASS: all six checks proven (config, runs, output, data accurate against an independent source, AI claims sourced, consumer page matches).',
  PASS_IDLE: 'PASS, weekend idle: correctly idle on the weekend, and its last weekday run passed the output and data checks.',
  FAIL_DATA: 'FAIL, data: the output exists but values are wrong, stale, null or duplicated when checked against an independent source.',
  FAIL_RUN: 'FAIL, run: the recent live runs failed, timed out or missed their slots.',
  FAIL_CONFIG: 'FAIL, config: a cron or systemd twin is still running it, or it is missing from the relay live list.',
  FAIL_NO_OUTPUT: 'FAIL, no output: the run says done, but no matching output row or file was written.',
  FAIL_CONSUMER: 'FAIL, consumer: the data is fine, but the page you look at shows different or stale values.',
  HALLUCINATION: 'Hallucination: an AI-written claim had no source or contradicted its source.',
  UNVERIFIABLE: 'Not provable yet: evidence is missing (no live run since the cutover, or no independent source). It gets re-audited at its next run.',
}
const MODE_KEYS = ['live', 'shadow', 'dry']
const NAMES: Record<string, string> = { live: 'Live on n8n', shadow: 'n8n + cron (both) · cutover pending', dry: 'Dry run on n8n' }
/** The per-verdict counts row, in the operator's order. */
export const VERDICT_ORDER = ['PASS', 'PASS_IDLE', 'FAIL_DATA', 'FAIL_RUN', 'FAIL_CONFIG', 'FAIL_NO_OUTPUT', 'FAIL_CONSUMER', 'HALLUCINATION', 'UNVERIFIABLE'] as const
export const vc = (v: string): string => (v.startsWith('PASS') ? 'live' : v === 'UNVERIFIABLE' ? 'dry' : 'bad')
export const vmatch = (v: string, f: string): boolean => !f || (f === 'PASS_ALL' ? String(v).startsWith('PASS') : f === 'FAIL_ALL' ? String(v).startsWith('FAIL') : v === f)
export const vl = (v: string): string => ({ PASS: 'PASS', PASS_IDLE: 'PASS · weekend idle', UNVERIFIABLE: 'NOT PROVABLE YET', PASS_ALL: 'PASS · all', FAIL_ALL: 'FAIL · all' } as Record<string, string>)[v] || v.replace(/_/g, ' ')
/** Job-catalog health, same keys and order as GET /api/v2/jobs-catalog status_mix. */
export const HEALTH: Array<[string, string, string, string]> = [
  ['failed', 'failed', 'bad', 'The last run failed.'], ['missed', 'missed', 'bad', 'A scheduled slot passed with no run.'],
  ['late', 'late', 'shadow', 'Ran later than its schedule allows.'], ['running', 'running', 'dry', 'Running now.'],
  ['ok', 'ok', 'live', 'The last run succeeded and its output was checked.'],
  ['ok_unverified', 'ok unproven', 'dry', 'The last run exited cleanly, but nothing checked its output.'],
  ['not_measured', 'not measured', 'none', 'No run record to judge it by.'],
  ['inactive', 'paused/retired', 'none', 'Paused, retired or never scheduled: not counted as active.'],
]

type Lane = Record<string, any>
type Wire = Record<string, any>
const tipAttr = (t: string) => `data-tip="${esc(t)}"`
const verdictTipText = (l: Lane, w: Wire): string => {
  const wi = l.work_item ? (w.work_items || {})[l.work_item] : null
  return (VTIP[l.verdict] || l.verdict) + (l.defect ? ' Defect: ' + l.defect : '') + (l.work_item ? ' Fix: ' + l.work_item : '')
    + (wi && wi.status ? ` (${wi.status}${wi.owner ? ', ' + wi.owner : ''})` : '')
}
export const laneLink = (id: string): string => `/ops/jobs-n8n?tab=n8n&lane=${encodeURIComponent(id)}`
const auditedLanes = (w: Wire): Lane[] => (Object.values(w.lanes || {}) as Lane[]).filter(l => !!l.verdict)

export function tabsHtml(sub: SubKey): string {
  return `<nav class="tabs" role="tablist" aria-label="n8n catalog views">${SUBTABS.map(([k, label]) =>
    `<button type="button" role="tab" data-sub="${k}" aria-selected="${k === sub}">${label}</button>`).join('')}</nav>`
}

/** The audit header and the six stat tiles. Shared verbatim by Jobs & n8n > n8n audit (Overview) and the Job catalog
 *  page (LQ-20261107-506), so the two pages cannot disagree: both render this one string from the same GET. */
export function auditHeaderHtml(w: Wire): string {
  const st = w.stats || {}, a = st.audit || {}, m = st.modes || {}, v = st.verdicts || {}
  const n = (x: unknown) => (typeof x === 'number' ? String(x) : '—')
  // A verdict absent from a reported tally has zero lanes; with no tally at all every count is unknown ("—").
  const vcount = (k: string): number | null => (st.verdicts ? (typeof v[k] === 'number' ? v[k] : 0) : null)
  const idle = n(vcount('PASS_IDLE'))
  const when = w.audit && w.audit.written_at ? `Audited ${esc(etFmt(w.audit.written_at))}.` : 'Not audited yet.'
  return `<header><h1>What n8n is configured to handle</h1><p style="margin:6px 0 0;padding:8px 10px;border-left:4px solid var(--shadow);background:var(--card)"><b>${when}</b> Each of the ${n(a.audited)} n8n-only lanes was checked on six points: config, runs, output, data accuracy against an independent source, AI claims against sources, and what the page shows. Only <b>PASS</b> means working. Every failure has a fix assigned (LQ id).</p>
<p class="sub">Configuration plus audit verdicts · jobs as of ${esc(etFmt(w.computed_at))} · relay live-lane list: ${n(w.relay && w.relay.lanes)} lanes · refreshes every minute</p></header>
<section class="stats">
<button type="button" class="stat go" data-sub="audit" data-filter="PASS_ALL"><span>n8n alone · audit PASS (incl. ${idle} weekend-idle) <i class="ib" role="button" aria-label="What this means" ${tipAttr(`Scheduled on n8n alone and passed all six audit checks (${idle} of these are correctly idle for the weekend; their last weekday run passed).`)}>ⓘ</i></span><b class="live">${n(a.pass)} / ${n(a.audited)}</b><em class="hint">List them ›</em></button><button type="button" class="stat go" data-sub="audit" data-filter="FAIL_ALL"><span>n8n alone · FAIL (fix assigned) <i class="ib" role="button" aria-label="What this means" ${tipAttr('Scheduled on n8n alone but failed at least one audit check. Each has a fix work item assigned. Open the Audit tab to see the defect.')}>ⓘ</i></span><b class="bad">${n(a.fail)}</b><em class="hint">List them ›</em></button><button type="button" class="stat go" data-sub="audit" data-filter="UNVERIFIABLE"><span>n8n alone · not provable yet <i class="ib" role="button" aria-label="What this means" ${tipAttr('Scheduled on n8n alone, but there is no evidence yet (no live run since the cutover, or no independent source to check against). Re-audited at the next run.')}>ⓘ</i></span><b class="dry">${n(a.not_provable)}</b><em class="hint">List them ›</em></button>
<button type="button" class="stat go" data-sub="lanes" data-mode="shadow"><span>n8n + cron both (cutover pending) <i class="ib" role="button" aria-label="What this means" ${tipAttr(TIP.shadow)}>ⓘ</i></span><b class="shadow">${n(m.both)}</b><em class="hint">List them ›</em></button>
<button type="button" class="stat go" data-sub="lanes" data-mode="dry"><span>Dry run on n8n <i class="ib" role="button" aria-label="What this means" ${tipAttr(TIP.dry)}>ⓘ</i></span><b class="dry">${n(m.dry)}</b><em class="hint">List them ›</em></button>
<button type="button" class="stat go" data-path="/ops/jobs-catalog"><span>Not on n8n <i class="ib" role="button" aria-label="What this means" ${tipAttr(TIP.none)}>ⓘ</i></span><b class="none">${n(m.none)}</b><em class="hint">Open the Job catalog ›</em></button>
</section>`
}

export function overviewHtml(w: Wire): string {
  const st = w.stats || {}, v = st.verdicts || {}
  const n = (x: unknown) => (typeof x === 'number' ? String(x) : '—')
  const vcount = (k: string): number | null => (st.verdicts ? (typeof v[k] === 'number' ? v[k] : 0) : null)
  const counts = VERDICT_ORDER.filter(k => k !== 'HALLUCINATION' || v[k]).map(k =>
    `<button type="button" data-sub="audit" data-filter="${k}" class="${vc(k)}" title="${esc(VTIP[k])} Tap to list them.">${esc(vl(k))} <b>${n(vcount(k))}</b></button>`).join('')
  return auditHeaderHtml(w) + `
<section aria-label="Audit verdicts"><h3>Audit verdicts · tap one to list its lanes</h3><div class="counts">${counts}</div></section>
<div class="key">
<div><b class="live">Live</b>: n8n is the only scheduler. Being on n8n does not prove the data is correct. Each live lane shows its audit verdict.</div>
<div><b class="shadow">Both</b>: n8n is configured, but the cron line is still active. That line is retired only after a verified live n8n run.</div>
<div><b class="dry">Dry run</b>: n8n runs it in report-only mode, so it writes nothing yet.</div><div style="color:var(--muted)">Tap any chip or count marked ⓘ for details.</div>
<div><b class="none">Not on n8n</b>: stays on cron or systemd. This covers broker reads and writes, the send class, always-on services and anything not yet migrated.</div>
</div>`
}

function laneLi(l: Lane, w: Wire): string {
  const m = MODE[l.mode] || 'none'
  const sched = (l.schedule || []).join(' · ') || 'event / no schedule'
  const v = l.verdict || ''
  const hay = esc(`${l.title || ''} ${l.lane_id} ${l.does || ''} ${v} ${l.defect || ''} ${l.work_item || ''}`.toLowerCase())
  return `<li data-lane="${esc(l.lane_id)}" data-hay="${hay}"><a class="lane" href="${esc(laneLink(l.lane_id))}" data-lane-link="${esc(l.lane_id)}"><div class="row"><span class="t">${esc(l.title || l.lane_id)}</span><span class="c">${esc(l.lane_id)} · ${esc(sched)}</span></div><div class="d">${esc(l.does || '')}</div></a><div class="row">${m !== 'dry' && m !== 'none' && !l.in_relay ? '<span class="flag">not in relay live list</span>' : ''}${l.paused_on_n8n ? '<span class="flag">paused on n8n</span>' : ''}${v ? `<span class="vb ${vc(v)}" ${tipAttr(verdictTipText(l, w))}>${esc(vl(v))} ⓘ</span>` : `<span class="vb none" ${tipAttr('Not audited: this lane has not been through the six-check audit, so nothing is claimed about whether it works.')}>NOT AUDITED ⓘ</span>`}${l.work_item ? `<span class="c">fix ${esc(l.work_item)}</span>` : ''}</div>${v && !v.startsWith('PASS') && l.defect ? `<div class="def">${esc(l.defect)}</div>` : ''}</li>`
}

export function healthHtml(c: Wire): string {
  const mix = c.status_mix
  if (!mix) return ''
  const jobs = typeof c.jobs === 'number' ? c.jobs : null
  const inactive = typeof mix.inactive === 'number' ? mix.inactive : null
  const chips = HEALTH.filter(([k]) => mix[k]).map(([k, label, cls, tip]) => `<span class="${cls}" ${tipAttr(`${label}: ${tip} Same count as the Job catalog page.`)}>${mix[k]} ${label} ⓘ</span>`).join('')
  const tally = jobs === null || inactive === null ? '' : `<p class="tally">${jobs - inactive} active + ${inactive} paused/retired = ${jobs} jobs in this category (the Job catalog counts all ${jobs})</p>`
  return `<div class="health" aria-label="Job health">${chips}</div>${tally}`
}

export function lanesHtml(w: Wire, q = '', mode = ''): string {
  const only = MODE_KEYS.includes(mode) ? mode : ''
  const cats = (w.categories || []).map((c: Wire, i: number) => {
    const jobs: Lane[] = (c.lanes || []).map((id: string) => (w.lanes || {})[id]).filter((l: Lane) => l && MODE[l.mode] && (!only || MODE[l.mode] === only))
    if (only && !jobs.length) return ''
    const n = (m: string) => jobs.filter(j => MODE[j.mode] === m).length
    const other: number | string = c.modes && typeof c.modes.none === 'number' ? c.modes.none : '—'
    let h = `<details data-cat="${esc(c.key)}"${jobs.length && (only || i < 3) ? ' open' : ''}><summary><h2>${esc(c.label)}</h2><span class="bar"><span class="pill live" ${tipAttr(TIP.live)}>${n('live')} live ⓘ</span><span class="pill shadow" ${tipAttr(TIP.shadow)}>${n('shadow')} both ⓘ</span><span class="pill dry" ${tipAttr(TIP.dry)}>${n('dry')} dry run ⓘ</span><span class="pill none" ${tipAttr(TIP.none)}>${other} not on n8n ⓘ</span></span></summary><div class="body">${c.blurb ? `<p class="blurb">${esc(c.blurb)}</p>` : ''}${healthHtml(c)}`
    if (!jobs.length) h += `<p class="blurb">Nothing in this bucket is on n8n. All ${other} jobs run on cron or systemd.</p>`
    for (const m of ['live', 'shadow', 'dry']) {
      const js = jobs.filter(j => MODE[j.mode] === m)
      if (js.length) h += `<div><h3 class="${m}" ${tipAttr(TIP[m])}>${NAMES[m]} · ${js.length} ⓘ</h3><ul>${js.map(j => laneLi(j, w)).join('')}</ul></div>`
    }
    return h + '</div></details>'
  }).join('')
  const total = only ? (Object.values(w.lanes || {}) as Lane[]).filter(l => MODE[l.mode] === only).length : 0
  const banner = only ? `<p class="banner">Showing only ${esc(NAMES[only])} · ${total} lanes. <button type="button" class="rerun" data-sub="lanes" data-filter="">Show all lanes</button></p>` : ''
  return `${banner}<input class="search" type="search" placeholder="Search lanes, defects, fix ids" aria-label="Search lanes" value="${esc(q)}" data-search>
<div id="cats" style="display:flex;flex-direction:column;gap:10px">${cats || '<p class="empty">No categories are reported.</p>'}</div><p class="empty" data-noresult hidden>No lane matches the search.</p>`
}

/** FAIL first, then hallucination, not provable, then pass; within a group, newest audit first. */
export function auditRows(w: Wire, filter = ''): Lane[] {
  const rank = (v: string) => (v.startsWith('FAIL') ? 0 : v === 'HALLUCINATION' ? 1 : v === 'UNVERIFIABLE' ? 2 : 3)
  return auditedLanes(w).filter(l => vmatch(l.verdict, filter))
    .sort((a, b) => rank(a.verdict) - rank(b.verdict) || String(a.verdict).localeCompare(String(b.verdict)) || String(b.audited_at || '').localeCompare(String(a.audited_at || '')) || String(a.lane_id).localeCompare(String(b.lane_id)))
}

export function auditHtml(w: Wire, filter = ''): string {
  const all = auditedLanes(w)
  const present = VERDICT_ORDER.filter(k => all.some(l => l.verdict === k)).concat(
    [...new Set(all.map(l => l.verdict))].filter(k => !(VERDICT_ORDER as readonly string[]).includes(k)).sort() as any)
  const chips = [`<button type="button" data-filter="" aria-pressed="${!filter}">All ${all.length}</button>`].concat(present.map(k =>
    `<button type="button" data-filter="${esc(k)}" aria-pressed="${filter === k}" class="${vc(k)}">${esc(vl(k))} ${all.filter(l => l.verdict === k).length}</button>`)).join('')
  const rows = auditRows(w, filter).map(l => {
    const wi = l.work_item ? (w.work_items || {})[l.work_item] : null
    const fix = l.work_item ? `<span class="c">fix ${esc(wi && wi.id || l.work_item)}${wi && wi.status ? ' · ' + esc(wi.status) : ' · status unknown'}${wi && wi.owner ? ' · ' + esc(wi.owner) : ''}</span>` : ''
    return `<li data-lane="${esc(l.lane_id)}"><a class="lane" href="${esc(laneLink(l.lane_id))}" data-lane-link="${esc(l.lane_id)}"><div class="row"><span class="t">${esc(l.title || l.lane_id)}</span><span class="c">${esc(l.lane_id)}</span></div></a><div class="row"><span class="vb ${vc(l.verdict)}" ${tipAttr(verdictTipText(l, w))}>${esc(vl(l.verdict))} ⓘ</span>${fix}<span class="c">audited ${esc(etFmt(l.audited_at))}</span></div>${l.defect ? `<div class="def">${esc(l.defect)}</div>` : ''}${l.fix_suggestion ? `<div class="d">Suggested fix: ${esc(l.fix_suggestion)}</div>` : ''}</li>`
  }).join('')
  const when = w.audit && w.audit.written_at ? `Audit written ${esc(etFmt(w.audit.written_at))}${w.audit.by ? ' by ' + esc(w.audit.by) : ''}` : 'No audit written yet'
  return `<p class="asof">${when} · fix status from the lead work ledger · as of ${esc(etFmt(w.computed_at))}</p>
<div class="fchips" role="group" aria-label="Filter by verdict">${chips}</div>
<details open><summary><h2>${filter ? esc(vl(filter)) : 'All audited lanes'} · ${auditRows(w, filter).length}</h2></summary><div class="body"><ul>${rows || '<li class="d">No lane has this verdict.</li>'}</ul></div></details>`
}

/** The approved rule, verbatim from the approved artifact. */
export const LLM_RULE = '<b>The rule for every lane:</b> the LLM diagnoses, drafts, proposes and checks claims. Deterministic code makes the actual change and validates it. Nothing an LLM writes reaches data, schedules or code without a deterministic check and a receipt.'
export const RERUN_TIP = 'Re-run needs operator grant: lane re-runs are a separate, grant-gated step. Nothing on this page can start a run.'
export const usd = (v: unknown): string => (typeof v === 'number' ? '$' + v.toFixed(v >= 1 ? 2 : 4) : '—')
const LLM_STATUS: Record<string, [string, string]> = {
  all_failed: ['bad', 'Every call in the last 24 h failed.'],
  lane_all_failed: ['bad', 'At least one model lane failed on every call in the last 24 h; the other lanes carried the work.'],
  active: ['live', 'Called in the last 24 h.'],
  no_calls_24h: ['shadow', 'No call in the last 24 h. The time shown is its last call within 30 days.'],
  not_in_log: ['dry', 'Runs outside the consumption log, so its own state is shown instead.'],
}
function llmItem(i: Wire): string {
  const [cls, tip] = LLM_STATUS[i.status] || ['none', 'Status not reported.']
  const label = i.status === 'all_failed' ? `All ${i.calls} failed` : i.status === 'lane_all_failed' ? `${i.failures} of ${i.calls} failed`
    : i.status === 'active' ? `${i.calls} calls · ${i.failures} failed` : i.status === 'no_calls_24h' ? `No calls in 24 h · last ${etFmt(i.last_at)}` : 'Not in the log'
  const lanes = (i.lanes || []).map((l: Wire) => `<span class="c${l.all_failed ? ' bad' : ''}">${esc(l.lane)}${l.models && l.models.length ? ' (' + esc(l.models.join(', ')) + ')' : ''}: ${l.calls} calls · ${l.failures} failed · last ${esc(etFmt(l.last_at))} · ${usd(l.spend_usd)}</span>${l.all_failed ? `<div class="def">Every call on ${esc(l.lane)} failed in 24 h.${l.last_error ? ' Last error: ' + esc(l.last_error) : ''}</div>` : ''}`).join('')
  const fx = i.fixer
  const fixer = i.status === 'not_in_log' ? `<div class="d">${esc(i.not_in_log)}${fx ? ` Fixer: ${fx.armed === false ? 'not armed (' + esc(fx.why || 'no reason recorded') + ')' : fx.armed ? 'armed' : 'arming unknown'} · ${typeof fx.waiting === 'number' ? fx.waiting : '—'} fixes waiting${fx.oldest ? ' since ' + esc(etFmt(fx.oldest)) : ''}.` : ' Fixer state could not be read.'}</div>` : ''
  return `<li data-proc="${esc(i.process_id)}"><div class="row"><span class="t">${esc(i.label)}</span><span class="c">${esc(i.process_id)}${i.models && i.models.length ? ' · ' + esc(i.models.join(', ')) : ''}${i.spend_usd !== null && i.spend_usd !== undefined ? ' · ' + usd(i.spend_usd) : ''}</span><span class="vb ${cls}" ${tipAttr(tip)}>${esc(label)} ⓘ</span></div>${lanes ? `<div class="lanes">${lanes}</div>` : ''}${fixer}${i.next ? `<div class="d">Next: ${esc(i.next)}</div>` : ''}</li>`
}
export function llmHtml(w: Wire): string {
  const L = w.llm
  if (!L) return `<p class="empty">LLM use is not reported yet.</p>`
  const head = `<p class="asof">LLM calls in the last 24 h, from the consumption log · as of ${esc(etFmt(L.as_of))} · refreshes every minute</p>${L.note ? `<p class="empty" role="status" style="color:var(--shadow)">${esc(L.note)}</p>` : ''}`
  const groups: Wire[] = L.groups || []
  const pill = (g: Wire) => `<span class="pill ${g.red || g.active * 2 < g.total ? 'bad' : 'live'}" ${tipAttr(`${g.label}: ${g.active} of ${g.total} purposes had a successful call in 24 h; ${g.red} have a model lane where every call failed.`)}>${g.key === 'ops' ? 'operations' : 'content'}: ${g.active}/${g.total} active ⓘ</span>`
  const reds = groups.filter(g => typeof g.red === 'number').reduce((n, g) => n + g.red, 0)
  const body = groups.map(g => `<div><h3 class="${g.red ? 'bad' : 'live'}">${esc(g.label)} · ${g.calls} calls · ${g.failures} failed · ${usd(g.spend_usd)}</h3><ul>${(g.items || []).map(llmItem).join('') || '<li class="d">No calls in 24 h.</li>'}</ul></div>`).join('')
  return `${head}<details open><summary><h2>How LLMs are used</h2><span class="bar">${groups.map(pill).join('')}${reds ? `<span class="pill bad" ${tipAttr('Purposes with a model lane where every call in the last 24 h failed. They are listed first, in red.')}>${reds} failing on a lane ⓘ</span>` : ''}</span></summary><div class="body">
<p class="blurb">Every governed LLM call writes a row to the consumption log; this view groups the last 24 h by purpose and model lane. A lane where every call failed is red, with its last error.</p>
<p class="blurb">${LLM_RULE}</p>
<p class="blurb">${esc(L.spend_note || '')}</p>${groups.length ? body : '<p class="empty">LLM use could not be read.</p>'}</div></details>`
}

const rerunBtn = () => `<button type="button" class="rerun" aria-disabled="true" data-rerun-disabled ${tipAttr(RERUN_TIP)}>Lane re-run · needs operator grant ⓘ</button>`
function healLi(x: Wire): string {
  const where = x.kind === 'fixer' ? `fixer job ${x.key} · ${String(x.state || '').replace(/_/g, ' ')} · since ${etFmt(x.since)}` : `diagnosis escalation${x.priority ? ' · ' + x.priority : ''} · ${etFmt(x.at)}`
  return `<li data-heal="${esc(x.key)}"><div class="row"><span class="t">${esc(x.lane || '(no lane)')}</span><span class="c">${esc(where)}</span></div><div class="def">${esc(x.plain)}</div>${x.cause ? `<div class="d">Cause: ${esc(x.cause)}</div>` : ''}${x.tried ? `<div class="d">Tried: ${esc(x.tried)}</div>` : ''}<div class="d">What you can do: ${esc(x.action)}</div><div class="acts">${x.grant_href ? `<a href="${esc(x.grant_href)}">Open Grants</a>` : ''}${x.lane ? `<a href="${esc(laneLink(x.lane))}" data-lane-link="${esc(x.lane)}">Open lane</a>` : ''}${rerunBtn()}</div></li>`
}
function workLi(x: Wire): string {
  return `<li data-work="${esc(x.id)}"><div class="row"><span class="t">${esc(x.title || x.id)}</span></div><div class="row"><span class="vb ${x.priority === 'P0' ? 'bad' : x.priority === 'P1' ? 'shadow' : 'none'}">${esc(x.priority || 'no priority')}</span><span class="c">${esc(x.id)} · ${esc(x.status || 'status unknown')} · ${esc(x.owner || 'no owner')}</span>${x.audit_fix ? `<span class="c" ${tipAttr('This item is the fix assigned to a failed lane in the audit.')}>audit fix ⓘ</span>` : ''}</div>${(x.lanes || []).length ? `<div class="acts">${x.lanes.map((l: string) => `<a href="${esc(laneLink(l))}" data-lane-link="${esc(l)}">${esc(l)}</a>`).join('')}</div>` : ''}</li>`
}
export function fixesHtml(w: Wire): string {
  const F = w.fixes
  if (!F) return `<p class="empty">Fixes are not reported yet.</p>`
  const fx = F.fixer || {}
  const heal: Wire[] = F.self_heal || []
  const work: Wire[] | null = F.work
  const banner = fx.armed === false
    ? `<p class="banner"><b>Self-heal is not armed:</b> ${esc(fx.why || 'no reason recorded')}. ${typeof fx.waiting === 'number' ? fx.waiting : '—'} fixes waiting${fx.oldest ? ' since ' + esc(etFmt(fx.oldest)) : ''}. Last fixer check ${esc(etFmt(fx.receipt_at))}.${fx.grant_href ? ` <a href="${esc(fx.grant_href)}">Issue the grant in Ops Controls → Grants</a>.` : ''}</p>`
    : fx.armed ? `<p class="banner" style="border-left-color:var(--live)">Self-heal is armed. Last fixer check ${esc(etFmt(fx.receipt_at))}.</p>` : ''
  const byP = new Map<string, Wire[]>()
  for (const x of work || []) { const k = x.priority || 'no priority'; byP.set(k, [...(byP.get(k) || []), x]) }
  const workHtml = work === null ? '<p class="empty">The lead work ledger could not be read, so open items are not shown.</p>'
    : [...byP.entries()].map(([p, xs], i) => `<details${i === 0 ? ' open' : ''}><summary><h2>Open fix items · ${esc(p)} · ${xs.length}</h2></summary><div class="body"><ul>${xs.map(workLi).join('')}</ul></div></details>`).join('') || '<p class="empty">No open item touches an n8n lane.</p>'
  return `<p class="asof">Read-only · as of ${esc(etFmt(F.as_of))} · fix items from ${esc(F.ledger || 'no ledger')} · refreshes every minute</p>
${(F.notes || []).map((n: string) => `<p class="empty" role="status" style="color:var(--shadow)">${esc(n)}</p>`).join('')}${banner}
<details open><summary><h2>Self-heal couldn't fix · ${heal.length}</h2><span class="bar"><span class="pill none" ${tipAttr(RERUN_TIP)}>re-run needs operator grant ⓘ</span></span></summary><div class="body"><p class="blurb">Fixer jobs that were refused, failed, cut off, or waited more than 24 h, and diagnosis escalations that need a person. Oldest first.</p><ul>${heal.map(healLi).join('') || '<li class="d">Nothing is waiting on a person.</li>'}</ul></div></details>
<section aria-label="Open fix items" style="display:flex;flex-direction:column;gap:10px"><h3>Open lead-ledger items that touch n8n lanes${work ? ' · ' + work.length : ''}</h3>${workHtml}</section>`
}

export function notesHtml(w: Wire): string {
  return (w.notes || []).map((n: string) => `<p class="empty" role="status" style="color:var(--shadow)">${esc(n)}</p>`).join('')
}

export function pageHtml(w: Wire, sub: SubKey, opts: { filter?: string; q?: string; mode?: string } = {}): string {
  const body = sub === 'lanes' ? lanesHtml(w, opts.q, opts.mode) : sub === 'audit' ? auditHtml(w, opts.filter) : sub === 'llm' ? llmHtml(w) : sub === 'fixes' ? fixesHtml(w) : overviewHtml(w)
  return `<main>${tabsHtml(sub)}${notesHtml(w)}<div role="tabpanel" style="display:flex;flex-direction:column;gap:16px">${body}</div></main>`
}

/** Hide lane rows that do not match the search, in place (keeps the input's focus). */
export function applySearch(S: ParentNode, q: string): void {
  const t = q.trim().toLowerCase()
  let shown = 0
  S.querySelectorAll('#cats details').forEach((d: any) => {
    let any = 0
    d.querySelectorAll('li[data-hay]').forEach((li: any) => { const ok = !t || li.dataset.hay.includes(t); li.hidden = !ok; if (ok) any++ })
    d.querySelectorAll('ul').forEach((ul: any) => { ul.parentElement.hidden = !!t && !ul.querySelector('li:not([hidden])') })
    if (t) { d.hidden = !any; if (any) d.open = true } else d.hidden = false
    shown += any
  })
  const nr = S.querySelector('[data-noresult]') as any
  if (nr) nr.hidden = !t || shown > 0
}

export type Nav = { sub?: SubKey; filter?: string; lane?: string; mode?: string; path?: string }
/** Render into a shadow root. Navigation (subtab, verdict filter, lane tap) goes back to React through onNav. */
export function mountApproved(S: ShadowRoot, w: Wire, sub: SubKey = 'overview', opts: { filter?: string; q?: string; mode?: string } = {}, onNav: (n: Nav) => void = () => {}): void {
  S.innerHTML = '<style>' + APPROVED_CSS + SUBTAB_CSS + '</style><div class="page">' + pageHtml(w, sub, opts) + '</div>'
  wireApproved(S, sub, opts, onNav)
}

/** Where a tap on the audit header or a tile goes: always Jobs & n8n > n8n audit (the subtab, verdict filter or mode the tile names). */
export function auditNavHref(n: Nav): string {
  if (n.lane) return `/ops/jobs-n8n?tab=n8n&lane=${encodeURIComponent(n.lane)}`
  if (n.path) return n.path
  const p = new URLSearchParams({ tab: 'catalog' })
  if (n.sub && n.sub !== 'overview') p.set('sub', n.sub)
  if (n.filter) p.set('verdict', n.filter)
  if (n.mode) p.set('mode', n.mode)
  return `/ops/jobs-n8n?${p.toString()}`
}

/** LQ-20261107-506: only the audit header and the six tiles (the same string the n8n audit Overview renders), for the
 *  Job catalog page. Taps are handed to onNav exactly as on the n8n audit page. */
export function mountAuditHeader(S: ShadowRoot, w: Wire, onNav: (n: Nav) => void = () => {}): void {
  S.innerHTML = '<style>' + APPROVED_CSS + SUBTAB_CSS + '</style><div class="page" style="padding-block:0 8px"><main style="max-width:none"><div style="display:flex;flex-direction:column;gap:16px">' + auditHeaderHtml(w) + '</div></main></div>'
  wireApproved(S, 'overview', {}, onNav)
}

function wireApproved(S: ShadowRoot, sub: SubKey, opts: { filter?: string; q?: string; mode?: string }, onNav: (n: Nav) => void): void {
  S.querySelectorAll('[data-tip]').forEach((e: any) => { e.title = e.dataset.tip; e.tabIndex = 0 })
  const search = S.querySelector('[data-search]') as HTMLInputElement | null
  if (search) { search.addEventListener('input', () => applySearch(S, search.value)); if (opts.q) applySearch(S, opts.q) }
  let tb: HTMLDivElement | null = null
  const showTip = (t: string) => {
    if (!tb) { tb = document.createElement('div'); tb.className = 'tipbox'; tb.setAttribute('role', 'status'); S.appendChild(tb) }
    tb.innerHTML = ''
    const s = document.createElement('span'); s.textContent = t
    const b = document.createElement('button'); b.type = 'button'; b.setAttribute('aria-label', 'Close'); b.textContent = '×'; b.onclick = () => { if (tb) tb.hidden = true }
    tb.append(s, b); tb.hidden = false
  }
  S.addEventListener('click', (ev: any) => {
    const tip = ev.target.closest('[data-tip]')
    if (tip) { ev.preventDefault(); ev.stopPropagation(); showTip(tip.dataset.tip); return }
    if (tb && !ev.target.closest('.tipbox')) tb.hidden = true
    const link = ev.target.closest('[data-lane-link]')
    if (link && !ev.metaKey && !ev.ctrlKey && ev.button === 0) { ev.preventDefault(); onNav({ lane: link.dataset.laneLink }); return }
    const go = ev.target.closest('[data-path]')
    if (go) { ev.preventDefault(); onNav({ path: go.dataset.path }); return }
    const nav = ev.target.closest('[data-sub],[data-filter]')
    if (nav) { ev.preventDefault(); onNav({ sub: (nav.dataset.sub || sub) as SubKey, filter: nav.dataset.filter ?? '', mode: nav.dataset.mode || '' }) }
  }, true)
  S.addEventListener('keydown', (ev: any) => {
    const e = ev.target.closest && ev.target.closest('[data-tip]')
    if (e && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); showTip(e.dataset.tip) }
  })
}
