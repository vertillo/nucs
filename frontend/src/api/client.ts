export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body && typeof (body as { detail: unknown }).detail === 'string') {
    return (body as { detail: string }).detail
  }
  return fallback
}

/** Abort any request that hangs past this (offline/black-hole networks):
 *  the UI must never be stuck on "Saving…" forever (phase 13b finding 13B-03). */
const FETCH_TIMEOUT_MS = 30000

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  opts?: { redirectOn401?: boolean },
): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  let response: Response
  try {
    response = await fetch(path, {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
      signal: controller.signal,
      ...options,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'The request timed out.')
    }
    throw error
  } finally {
    clearTimeout(timer)
  }

  if (response.status === 401) {
    if (opts?.redirectOn401 !== false) {
      window.location.assign('/login')
    }
    throw new ApiError(401, 'Not authenticated')
  }

  if (response.status === 204) {
    return undefined as T
  }

  const body = await parseBody(response)

  if (!response.ok) {
    throw new ApiError(response.status, detailOf(body, 'Request failed'))
  }

  return body as T
}

export function post(path: string, body: unknown): Promise<void> {
  return apiFetch<void>(path, { method: 'POST', body: JSON.stringify(body) })
}

export function put(path: string, body: unknown): Promise<void> {
  return apiFetch<void>(path, { method: 'PUT', body: JSON.stringify(body) })
}

export function get<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'GET' })
}

/** Fetch raw text response (for non-JSON endpoints like diagnostic reports). */
export async function fetchText(path: string, options: RequestInit = {}): Promise<string> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      ...options.headers,
    },
    ...options,
  })
  if (response.status === 401) {
    window.location.assign('/login')
    throw new ApiError(401, 'Not authenticated')
  }
  if (!response.ok) {
    const body = await parseBody(response)
    throw new ApiError(response.status, detailOf(body, 'Request failed'))
  }
  return response.text()
}
