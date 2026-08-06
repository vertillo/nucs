import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, get, post } from './client'

export interface AppErrorItem {
  id: number
  ts: string
  source: string
  level: string
  message: string
  stack: string | null
  context: Record<string, unknown> | string | null
}

export interface ErrorsResponse {
  items: AppErrorItem[]
  total: number
  page: number
  page_size: number
}

export function useErrors() {
  return useQuery<ErrorsResponse>({
    queryKey: ['errors'],
    queryFn: () => get<ErrorsResponse>('/api/v1/errors?page_size=50'),
    refetchInterval: 15000,
  })
}

/** Client-side failure report shown on the /errors page (scrubbed server-side). */
export function useReportError() {
  return useMutation({
    mutationFn: ({ message, context }: { message: string; context?: string }) =>
      apiFetch<void>('/api/v1/errors', {
        method: 'POST',
        body: JSON.stringify({ message, context }),
      }),
  })
}

export function useClearErrors() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>('/api/v1/errors', { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['errors'] })
    },
  })
}

export function postError(message: string, context?: unknown): void {
  try {
    post('/api/v1/errors', {
      message,
      context: context === undefined ? undefined : JSON.stringify(context),
    }).catch(() => undefined)
  } catch {
    // never let error reporting break the UI
  }
}
