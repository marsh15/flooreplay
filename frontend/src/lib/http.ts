import { session } from '@/lib/session'

/**
 * Shared HTTP transport for the FloorReplay backend: base URL, error shape,
 * and the JSON and download helpers. Free of domain types so every feature
 * module can depend on it without pulling in another feature's client.
 */

// Dev uses the Vite proxy; a deployed static build points at the backend
// origin via VITE_API_BASE (e.g. https://flooreplay-api.onrender.com/api/v1).
export const API_BASE: string = (import.meta.env.VITE_API_BASE || '/api/v1').replace(/\/$/, '')
interface RequestOptions {
  anonymous?: boolean
  allowSessionChange?: boolean
  timeoutMs?: number
}

async function performRequest<T>(
  path: string,
  init: RequestInit | undefined,
  read: (response: Response) => Promise<T>,
  options?: RequestOptions,
): Promise<T> {
  // The provider workflow has a 60-second server deadline. Leave room for its receipt.
  const deadline = AbortSignal.timeout(
    options?.timeoutMs ?? (init?.method === 'POST' ? 70_000 : 20_000),
  )
  const signal = init?.signal ? AbortSignal.any([init.signal, deadline]) : deadline
  const token = options?.anonymous ? null : session.token()
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type') && init?.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal,
      cache: 'no-store',
    })
    if (!response.ok) {
      let code = 'REQUEST_FAILED'
      let message =
        response.status === 401
          ? 'Your session ended. Sign in again.'
          : `Request failed (${response.status}). Please try again.`
      try {
        const body: unknown = await response.json()
        if (typeof body === 'object' && body !== null) {
          if ('code' in body && typeof body.code === 'string') code = body.code
          if ('message' in body && typeof body.message === 'string') message = body.message
          else if ('detail' in body && typeof body.detail === 'string') message = body.detail
          else if ('detail' in body && Array.isArray(body.detail)) {
            const messages = body.detail.flatMap((entry: unknown) =>
              typeof entry === 'object' &&
              entry !== null &&
              'msg' in entry &&
              typeof entry.msg === 'string'
                ? [entry.msg]
                : [],
            )
            if (messages.length) message = messages.join('; ')
          }
        }
      } catch {
        // A proxy may return an HTML error page.
      }
      if (response.status === 401 && token && session.token() === token) session.expire()
      throw new ApiError(
        code,
        message,
        response.status,
        response.headers.get('X-Request-ID') ?? undefined,
      )
    }
    const value = await read(response)
    if (!options?.allowSessionChange && token && session.token() !== token)
      throw new ApiError(
        'SESSION_CHANGED',
        'The account changed while this request was running. Please try again.',
        401,
      )
    return value
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (init?.signal?.aborted) throw error
    if (deadline.aborted)
      throw new ApiError(
        'REQUEST_TIMEOUT',
        'The request timed out. A submitted action may still finish. Check its saved result before submitting again.',
        0,
      )
    if (error instanceof SyntaxError)
      throw new ApiError(
        'INVALID_RESPONSE',
        'The server returned an unreadable response. Please try again.',
        502,
      )
    throw new ApiError(
      'NETWORK_UNAVAILABLE',
      'Cannot reach the server. Check your connection and try again.',
      0,
    )
  }
}

export function apiRequest<T>(
  path: string,
  init?: RequestInit,
  options?: RequestOptions,
): Promise<T> {
  return performRequest(path, init, (response) => response.json(), options)
}

export function apiDownload(path: string): Promise<Blob> {
  return performRequest(path, undefined, (response) => response.blob())
}

export class ApiError extends Error {
  code: string
  status: number

  requestId?: string

  constructor(code: string, message: string, status: number, requestId?: string) {
    super(requestId ? `${message} Request ${requestId}.` : message)
    this.requestId = requestId
    this.code = code
    this.status = status
  }
}
