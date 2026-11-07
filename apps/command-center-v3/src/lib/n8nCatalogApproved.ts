/* Ops › Jobs & n8n › n8n catalog: the operator-APPROVED design (artifact "n8n Lane Configuration",
   https://claude.ai/artifact/3YEqk8nVTHM85JHnx6Gukg), rendered verbatim: same markup, same CSS, same tooltips.
   Generated from the approved HTML; only the data source changed: live GET /api/v2/ops/n8n-catalog. Read-only.
   LQ-20261107-180: the page is split into deep-linkable subtabs (?tab=catalog&sub=overview|lanes|audit). Every number
   and time comes from the live GET (refreshed each minute) and the page states its own "as of" time in ET. */
export const APPROVED_CSS = "\n:host{--bg:#f6f7f5;--fg:#1c2320;--muted:#5c6862;--line:#d7dcd8;--card:#fff;--live:#1f7a4d;--shadow:#a5650b;--dry:#4f6f8f;--chip:#eef1ee;--bad:#b3261e}\n@media (prefers-color-scheme:dark){:host(:not([data-theme=\"light\"])){--bg:#131715;--fg:#e3e8e4;--muted:#98a49d;--line:#2b332f;--card:#1a1f1c;--live:#5cc28d;--shadow:#e0a84a;--dry:#8fb3d6;--chip:#232a26;--bad:#f2867c;color-scheme:dark}}\n:host([data-theme=\"dark\"]){--bg:#131715;--fg:#e3e8e4;--muted:#98a49d;--line:#2b332f;--card:#1a1f1c;--live:#5cc28d;--shadow:#e0a84a;--dry:#8fb3d6;--chip:#232a26;--bad:#f2867c;color-scheme:dark}\n.page{background:var(--bg);color:var(--fg);font:15px/1.5 \"IBM Plex Sans\",system-ui,sans-serif;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}\nmain{max-width:800px;margin:0 auto;display:flex;flex-direction:column;gap:16px}\nh1{font-size:1.5rem;margin:0;text-wrap:balance}.sub{color:var(--muted);font-size:.85rem}\n.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}\n.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}\n.stat b{display:block;font:500 1.5rem \"IBM Plex Mono\",monospace}.stat span{font-size:.78rem;color:var(--muted)}\n.key{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;font-size:.88rem;display:flex;flex-direction:column;gap:4px}\ndetails{background:var(--card);border:1px solid var(--line);border-radius:8px}\nsummary{cursor:pointer;padding:12px 14px;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline;list-style:none}\nsummary::-webkit-details-marker{display:none}\nsummary h2{font-size:1.02rem;margin:0;flex:1 1 200px}\n.bar{display:flex;gap:6px;flex-wrap:wrap;font:500 .78rem \"IBM Plex Mono\",monospace}\n.pill{padding:2px 8px;border-radius:99px;background:var(--chip)}\n.live{color:var(--live)}.shadow{color:var(--shadow)}.dry{color:var(--dry)}.none{color:var(--muted)}\n.body{padding:0 14px 12px;display:flex;flex-direction:column;gap:12px}\n.blurb{color:var(--muted);font-size:.86rem;margin:0}\nh3{font-size:.74rem;text-transform:uppercase;letter-spacing:.06em;margin:0 0 4px}\nul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}\nli{padding:7px 0;border-top:1px solid var(--line);display:flex;flex-direction:column;gap:1px;min-width:0}\n.row{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}\n.t{font-weight:600}.c{font:.76rem \"IBM Plex Mono\",monospace;color:var(--muted);overflow-wrap:anywhere}\n.d{font-size:.86rem;color:var(--muted)}\n.flag{font-size:.72rem;color:var(--shadow)}\n.bad{color:var(--bad)}.vb{font:600 .7rem \"IBM Plex Mono\",monospace;padding:1px 6px;border-radius:4px;background:var(--chip)}.def{font-size:.8rem;color:var(--fg);border-left:3px solid var(--bad);padding-left:8px;margin-top:2px;overflow-wrap:anywhere}\n[data-tip]{cursor:help}.tipbox{position:fixed;left:max(12px,env(safe-area-inset-left,0px));right:max(12px,env(safe-area-inset-right,0px));bottom:calc(12px + env(safe-area-inset-bottom,0px));max-width:640px;margin:0 auto;background:var(--fg);color:var(--bg);border-radius:10px;padding:12px 40px 12px 14px;font-size:.9rem;line-height:1.45;box-shadow:0 6px 24px rgba(0,0,0,.3);z-index:20}.tipbox button{position:absolute;top:6px;right:8px;background:none;border:0;color:inherit;font-size:1.2rem;cursor:pointer}"
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
.empty{color:var(--muted);font-size:.9rem;padding:12px 14px;background:var(--card);border:1px solid var(--line);border-radius:8px;margin:0}
`
export const SUBTABS = [['overview', 'Overview'], ['lanes', 'Lanes'], ['audit', 'Audit']] as const
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
const NAMES: Record<string, string> = { live: 'Live on n8n', shadow: 'n8n + cron (both) · cutover pending', dry: 'Dry run on n8n' }
/** The per-verdict counts row, in the operator's order. */
export const VERDICT_ORDER = ['PASS', 'PASS_IDLE', 'FAIL_DATA', 'FAIL_RUN', 'FAIL_CONFIG', 'FAIL_NO_OUTPUT', 'FAIL_CONSUMER', 'HALLUCINATION', 'UNVERIFIABLE'] as const
export const vc = (v: string): string => (v.startsWith('PASS') ? 'live' : v === 'UNVERIFIABLE' ? 'dry' : 'bad')
export const vl = (v: string): string => ({ PASS: 'PASS', PASS_IDLE: 'PASS · weekend idle', UNVERIFIABLE: 'NOT PROVABLE YET' } as Record<string, string>)[v] || v.replace(/_/g, ' ')
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

export function overviewHtml(w: Wire): string {
  const st = w.stats || {}, a = st.audit || {}, m = st.modes || {}, v = st.verdicts || {}
  const n = (x: unknown) => (typeof x === 'number' ? String(x) : '—')
  const idle = v.PASS_IDLE ?? 0
  const when = w.audit && w.audit.written_at ? `Audited ${esc(etFmt(w.audit.written_at))}.` : 'Not audited yet.'
  const counts = VERDICT_ORDER.filter(k => k !== 'HALLUCINATION' || v[k]).map(k =>
    `<button type="button" data-sub="audit" data-filter="${k}" class="${vc(k)}" title="${esc(VTIP[k])} Tap to list them.">${esc(vl(k))} <b>${n(v[k] ?? 0)}</b></button>`).join('')
  return `<header><h1>What n8n is configured to handle</h1><p style="margin:6px 0 0;padding:8px 10px;border-left:4px solid var(--shadow);background:var(--card)"><b>${when}</b> Each of the ${n(a.audited)} n8n-only lanes was checked on six points: config, runs, output, data accuracy against an independent source, AI claims against sources, and what the page shows. Only <b>PASS</b> means working. Every failure has a fix assigned (LQ id).</p>
<p class="sub">Configuration plus audit verdicts · jobs as of ${esc(etFmt(w.computed_at))} · relay live-lane list: ${n(w.relay && w.relay.lanes)} lanes · refreshes every minute</p></header>
<section class="stats">
<div class="stat" ${tipAttr(`Scheduled on n8n alone and passed all six audit checks (${idle} of these are correctly idle for the weekend; their last weekday run passed).`)}><span>n8n alone · audit PASS (incl. ${idle} weekend-idle) ⓘ</span><b class="live">${n(a.pass)} / ${n(a.audited)}</b></div><div class="stat" ${tipAttr('Scheduled on n8n alone but failed at least one audit check. Each has a fix work item assigned. Open the Audit tab to see the defect.')}><span>n8n alone · FAIL (fix assigned) ⓘ</span><b class="bad">${n(a.fail)}</b></div><div class="stat" ${tipAttr('Scheduled on n8n alone, but there is no evidence yet (no live run since the cutover, or no independent source to check against). Re-audited at the next run.')}><span>n8n alone · not provable yet ⓘ</span><b class="dry">${n(a.not_provable)}</b></div>
<div class="stat" ${tipAttr(TIP.shadow)}><span>n8n + cron both (cutover pending) ⓘ</span><b class="shadow">${n(m.both)}</b></div>
<div class="stat" ${tipAttr(TIP.dry)}><span>Dry run on n8n ⓘ</span><b class="dry">${n(m.dry)}</b></div>
<div class="stat" ${tipAttr(TIP.none)}><span>Not on n8n ⓘ</span><b class="none">${n(m.none)}</b></div>
</section>
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
  const inactive = mix.inactive ?? 0
  const chips = HEALTH.filter(([k]) => mix[k]).map(([k, label, cls, tip]) => `<span class="${cls}" ${tipAttr(`${label}: ${tip} Same count as the Job catalog page.`)}>${mix[k]} ${label} ⓘ</span>`).join('')
  const tally = jobs === null ? '' : `<p class="tally">${jobs - inactive} active + ${inactive} paused/retired = ${jobs} jobs in this category (the Job catalog counts all ${jobs})</p>`
  return `<div class="health" aria-label="Job health">${chips}</div>${tally}`
}

export function lanesHtml(w: Wire, q = ''): string {
  const cats = (w.categories || []).map((c: Wire, i: number) => {
    const jobs: Lane[] = (c.lanes || []).map((id: string) => (w.lanes || {})[id]).filter((l: Lane) => l && MODE[l.mode])
    const n = (m: string) => jobs.filter(j => MODE[j.mode] === m).length
    const other = (c.modes && c.modes.none) || 0
    let h = `<details data-cat="${esc(c.key)}"${jobs.length && i < 3 ? ' open' : ''}><summary><h2>${esc(c.label)}</h2><span class="bar"><span class="pill live" ${tipAttr(TIP.live)}>${n('live')} live ⓘ</span><span class="pill shadow" ${tipAttr(TIP.shadow)}>${n('shadow')} both ⓘ</span><span class="pill dry" ${tipAttr(TIP.dry)}>${n('dry')} dry run ⓘ</span><span class="pill none" ${tipAttr(TIP.none)}>${other} not on n8n ⓘ</span></span></summary><div class="body">${c.blurb ? `<p class="blurb">${esc(c.blurb)}</p>` : ''}${healthHtml(c)}`
    if (!jobs.length) h += `<p class="blurb">Nothing in this bucket is on n8n. All ${other} jobs run on cron or systemd.</p>`
    for (const m of ['live', 'shadow', 'dry']) {
      const js = jobs.filter(j => MODE[j.mode] === m)
      if (js.length) h += `<div><h3 class="${m}" ${tipAttr(TIP[m])}>${NAMES[m]} · ${js.length} ⓘ</h3><ul>${js.map(j => laneLi(j, w)).join('')}</ul></div>`
    }
    return h + '</div></details>'
  }).join('')
  return `<input class="search" type="search" placeholder="Search lanes, defects, fix ids" aria-label="Search lanes" value="${esc(q)}" data-search>
<div id="cats" style="display:flex;flex-direction:column;gap:10px">${cats || '<p class="empty">No categories are reported.</p>'}</div><p class="empty" data-noresult hidden>No lane matches the search.</p>`
}

/** FAIL first, then hallucination, not provable, then pass; within a group, newest audit first. */
export function auditRows(w: Wire, filter = ''): Lane[] {
  const rank = (v: string) => (v.startsWith('FAIL') ? 0 : v === 'HALLUCINATION' ? 1 : v === 'UNVERIFIABLE' ? 2 : 3)
  return auditedLanes(w).filter(l => !filter || l.verdict === filter)
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

export function notesHtml(w: Wire): string {
  return (w.notes || []).map((n: string) => `<p class="empty" role="status" style="color:var(--shadow)">${esc(n)}</p>`).join('')
}

export function pageHtml(w: Wire, sub: SubKey, opts: { filter?: string; q?: string } = {}): string {
  const body = sub === 'lanes' ? lanesHtml(w, opts.q) : sub === 'audit' ? auditHtml(w, opts.filter) : overviewHtml(w)
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

export type Nav = { sub?: SubKey; filter?: string; lane?: string }
/** Render into a shadow root. Navigation (subtab, verdict filter, lane tap) goes back to React through onNav. */
export function mountApproved(S: ShadowRoot, w: Wire, sub: SubKey = 'overview', opts: { filter?: string; q?: string } = {}, onNav: (n: Nav) => void = () => {}): void {
  S.innerHTML = '<style>' + APPROVED_CSS + SUBTAB_CSS + '</style><div class="page">' + pageHtml(w, sub, opts) + '</div>'
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
    const nav = ev.target.closest('[data-sub],[data-filter]')
    if (nav) { ev.preventDefault(); onNav({ sub: (nav.dataset.sub || sub) as SubKey, filter: nav.dataset.filter ?? '' }) }
  }, true)
  S.addEventListener('keydown', (ev: any) => {
    const e = ev.target.closest && ev.target.closest('[data-tip]')
    if (e && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); showTip(e.dataset.tip) }
  })
}
