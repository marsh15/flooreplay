import { useSyncExternalStore } from 'react'

/** The public synthetic demo workspace. Anyone may read it; nobody may write to it. */
export const DEMO_WORKSPACE = 'public-demo'

let selected = DEMO_WORKSPACE
const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * Which workspace the order decision screens read. It lives in memory only: a reload or a
 * sign-out returns to the public demo, so a private workspace id is never kept around.
 */
export const decisionWorkspace = {
  get: () => selected,
  set: (id: string) => {
    if (id === selected) return
    selected = id
    listeners.forEach((listener) => listener())
  },
  reset: () => decisionWorkspace.set(DEMO_WORKSPACE),
}

export function useDecisionWorkspace(): string {
  return useSyncExternalStore(subscribe, decisionWorkspace.get, () => DEMO_WORKSPACE)
}
