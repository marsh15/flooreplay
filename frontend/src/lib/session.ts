// Session credentials deliberately live only in this module's memory.
let token: string | null = null
export const session = {
  token: () => token,
  set: (value: string | null) => { token = value },
  headers: (): Record<string, string> => token ? { Authorization: `Bearer ${token}` } : {},
}
