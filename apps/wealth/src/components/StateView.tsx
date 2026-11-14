// Renders a RenderState: LOADING / UNKNOWN / ERROR (+ last good, labelled with its age) / EMPTY / OK.
// UNKNOWN is never green and never blank: it says UNKNOWN and why. OK and EMPTY hand control to the page.
import type { ReactNode } from 'react'
import type { RenderState } from './renderState'
import { healthCue, statusCue } from './renderState'
import { CueBadge } from './primitives'

export function ageText(seconds: number): string {
  if (seconds < 90) return `${seconds} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} h`
  return `${(seconds / 86400).toFixed(1)} d`
}

/** "as of <stamp> · <age> old". Never "now", never "live": it is the source's own clock. */
export function AsOf({ asOf, ageHours }: { asOf: string | null; ageHours: number | null }) {
  if (!asOf) return <span className="source-qualifier">no as-of from the source</span>
  return <span className="source-qualifier" title={asOf}>as of {asOf}{ageHours !== null ? ` · ${ageText(Math.round(ageHours * 3600))} old` : ''}</span>
}

export function StateView<T>({ state, children, empty, renderLastGood }: {
  state: RenderState<T>
  children: (data: T) => ReactNode
  empty?: ReactNode
  /** How to show the last good body on ERROR. Omitted → only the error and its age are shown. */
  renderLastGood?: (data: T) => ReactNode
}) {
  const cue = statusCue(state as RenderState<unknown>)
  const hc = healthCue(state as RenderState<unknown>)
  const health = hc ? <div className="source-qualifier" data-health="UNKNOWN"><CueBadge cue={hc} /></div> : null
  switch (state.status) {
    case 'LOADING':
      return <div className="empty-state" aria-busy="true">{cue && <CueBadge cue={cue} />}</div>
    case 'UNKNOWN':
      return <div className="empty-state" data-state="UNKNOWN">{cue && <CueBadge cue={cue} />}<p>{state.reason}</p></div>
    case 'ERROR':
      return (
        <div data-state="ERROR">
          <div className="note bad">{cue && <CueBadge cue={cue} />} {state.reason}
            {state.lastGood !== null && state.lastGoodAgeSeconds !== null ? <> · showing the last good read, {ageText(state.lastGoodAgeSeconds)} old</> : null}
          </div>
          {state.lastGood !== null && renderLastGood ? renderLastGood(state.lastGood) : null}
        </div>
      )
    case 'EMPTY':
      return <div className="empty-state" data-state="EMPTY">{health}{empty ?? <p>None.</p>}<AsOf asOf={state.asOf} ageHours={state.ageHours} /></div>
    case 'OK':
      return <>{health}{children(state.data as T)}</>
  }
}
