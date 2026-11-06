// Where am I? — the label the navigation shows for the current URL.
//
// Site validation 2026-10-22: every route that was routed in App.tsx but not on the rail fell back to
// "Trade · Home". The menu redesign (nav/v001, 2026-11-06) puts every routed page in one table
// (lib/navConfig.ts), so "where am I" is a lookup in that table; an unknown path says so instead of
// claiming to be Home.

import { locateNav, type NavSectionId } from './navConfig.ts'

export type NavWhere = { section: string; page: string }

export function locate(pathname: string, search = '', prefer?: NavSectionId | null): NavWhere {
  const here = locateNav(pathname, search, prefer)
  return here ? { section: here.section.label, page: here.page.label } : { section: 'Command Center', page: 'Page' }
}

/** The list a detail sheet returns to, for the shared DetailHeader's "‹ {list}" (never a bare "Back"). */
export function currentListLabel(): string {
  if (typeof window === 'undefined' || !window.location) return 'List'
  const path = window.location.pathname.replace(/^\/v3(?=\/|$)/, '') || '/'
  const here = locateNav(path, window.location.search)
  return here ? here.page.label : 'List'
}
