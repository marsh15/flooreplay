// Session credentials deliberately live only in this module's memory.
let token: string | null = null
const expiryListeners = new Set<() => void>()
export const session = {
  token: () => token,
  set: (value: string | null) => {
    token = value
  },
  headers: (): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {}),
  expire: () => {
    token = null
    expiryListeners.forEach((listener) => listener())
  },
  onExpire: (listener: () => void) => {
    expiryListeners.add(listener)
    return () => {
      expiryListeners.delete(listener)
    }
  },
}
