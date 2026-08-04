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

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    },
    ...options,
  })

  if (response.status === 401) {
    window.location.assign('/login')
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
