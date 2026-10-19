import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router'

function pageTitle(pathname: string) {
  if (pathname === '/') return 'Incidents'
  if (pathname === '/demo') return 'Practice investigation'
  if (pathname.startsWith('/incidents/imports')) return 'Import evidence'
  if (pathname.startsWith('/incidents/')) return 'Investigation'
  if (pathname === '/workspaces') return 'Workspaces'
  if (pathname === '/operations') return 'Operational evidence'
  if (pathname === '/evaluation') return 'Evaluation lab'
  if (pathname === '/coverage' || pathname.startsWith('/coverage/')) return 'Coverage archive'
  return 'Page not found'
}

/** On each route change: name the page, return to the top, and move focus to the content. */
export function NavigationEffects() {
  const { pathname } = useLocation()
  const previous = useRef<string | null>(null)
  useEffect(() => {
    document.title = `${pageTitle(pathname)} · FloorReplay`
    // The first load keeps the browser's own focus and scroll position.
    if (previous.current !== null && previous.current !== pathname) {
      window.scrollTo({ top: 0, behavior: 'instant' })
      document.getElementById('main-content')?.focus({ preventScroll: true })
    }
    previous.current = pathname
  }, [pathname])
  return null
}
