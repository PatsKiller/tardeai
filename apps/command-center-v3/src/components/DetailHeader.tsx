import type { CSSProperties, ReactNode, Ref } from 'react'
import { Link } from 'react-router-dom'
import { currentListLabel } from '../lib/navLocate'
import './DetailHeader.css'

/** The one detail header (design nav/v001 §5, operator-approved 2026-11-06).
 *
 *  Every full-screen detail on a phone gets the same 52 px bar: "‹ {list it came from}" on the left (never a bare
 *  "Back"), the title in the middle, ✕ on the right. A desktop side drawer leaves the list visible, so it has ✕ only
 *  (variant "drawer"). It replaces the per-team "← Back", "Back to list", "Back to jobs" buttons; the phone's back
 *  gesture still closes a sheet through the history entry its owner pushed (useMobilePageDetail). */
export default function DetailHeader({
  title, onClose, onBack, back, backTo, variant = 'sheet', titleAs = 'h2', titleId, titleRef, backRef, backTestId = 'detail-back', close = true, style, autoFocus,
}: {
  title: ReactNode
  /** ✕ (and Back, unless onBack is given). */
  onClose?: () => void
  onBack?: () => void
  /** The list this detail returns to. Defaults to the current menu page ("Watch", "Jobs & health", …). */
  back?: string
  /** Back (and ✕) as a link instead of a button, for detail pages with their own route. */
  backTo?: string
  /** sheet: full-screen phone detail (back + ✕). drawer: desktop side panel beside its list (✕ only).
   *  auto: one component that is a drawer and becomes a full-screen sheet on a phone (back appears ≤ 820 px). */
  variant?: 'sheet' | 'drawer' | 'auto'
  titleAs?: 'h1' | 'h2' | 'span'
  titleId?: string
  titleRef?: Ref<HTMLHeadingElement>
  backRef?: Ref<HTMLButtonElement>
  backTestId?: string
  /** Show ✕. A detail page whose only exit is its list may turn it off. */
  close?: boolean
  /** Layout only, e.g. negative margins so the bar spans a padded sheet edge to edge. */
  style?: CSSProperties
  /** Focus ✕ on mount (dialogs that used to autofocus their Back button). */
  autoFocus?: boolean
}) {
  const list = back || currentListLabel()
  const goBack = onBack ?? onClose
  const Title = titleAs
  const titleNode = <Title id={titleId} ref={titleRef as Ref<HTMLHeadingElement>} tabIndex={titleRef ? -1 : undefined} className="detail-header__title">{title}</Title>
  const backLabel = `Back to ${list.toLowerCase()}`
  const backNode = variant === 'drawer' ? null : backTo
    ? <Link className="detail-header__back" to={backTo} aria-label={backLabel} data-testid={backTestId}>‹ {list}</Link>
    : <button ref={backRef} type="button" className="detail-header__back" onClick={goBack} aria-label={backLabel} data-testid={backTestId}>‹ {list}</button>
  const closeNode = !close ? <span aria-hidden="true" /> : backTo && !onClose
    ? <Link className="detail-header__close" to={backTo} aria-label="Close" data-testid="detail-close">✕</Link>
    : <button type="button" className="detail-header__close" onClick={onClose ?? goBack} aria-label="Close" data-testid="detail-close" autoFocus={autoFocus}>✕</button>
  return <header className={`detail-header detail-header--${variant}`} data-testid="detail-header" style={style}>
    {backNode}{titleNode}{closeNode}
  </header>
}
