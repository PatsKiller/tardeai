import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { locateNav, type NavHere, type NavSectionId } from '../lib/navConfig'

/** The section the operator last navigated through. A route that lives in two sections (/approvals, /cio/questions)
 *  stays in the one it was opened from: links carry `state.navSection`, and a reload or deep link without state
 *  falls back to the last section used in this tab, then to the table's own preference (navConfig.locateNav). */
let lastSection: NavSectionId | null = null

export const NAV_ALL_EVENT = 'cc-nav-all'

/** Open the "All ▾" grouped sheet for a section (bottom tab re-tap, or the strip's own "All ▾"). */
export function openAllSheet(section: NavSectionId) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(NAV_ALL_EVENT, { detail: section }))
}

export function useNavHere(): { here: NavHere; showPreview: boolean; pathname: string } {
  const { pathname, search, state } = useLocation()
  const fromState = (state as { navSection?: NavSectionId } | null)?.navSection ?? null
  const here = locateNav(pathname, search, fromState ?? lastSection)
  if (here) lastSection = here.section.id
  const [previewFlag, setPreviewFlag] = useState(false)
  useEffect(() => {
    try { setPreviewFlag(localStorage.getItem('CC_CONTROL_PLANE_PREVIEW') === '1') } catch { /* private mode */ }
  }, [pathname])
  return { here, showPreview: previewFlag || pathname.startsWith('/control-plane'), pathname }
}
