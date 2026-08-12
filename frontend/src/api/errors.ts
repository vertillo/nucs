import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, fetchText, get, post } from './client'

export interface AppErrorItem {
  id: number
  ts: string
  source: string
  level: string
  message: string
  stack: string | null
  context: Record<string, unknown> | string | null
  read: boolean
}

export interface ErrorsResponse {
  items: AppErrorItem[]
  total: number
  unread_total: number
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

// phase 7 (spec 7.2): read-state mutations. Optimistic so the shared ['errors']
// cache (and therefore the navbar unread_total badge) updates instantly; the
// 15s poll + invalidation reconcile with the server.

function patchItemRead(
  data: ErrorsResponse | undefined,
  id: number,
  read: boolean,
): ErrorsResponse | undefined {
  if (!data) return data
  let delta = 0
  const items = data.items.map((item) => {
    if (item.id !== id || item.read === read) return item
    delta += read ? -1 : 1
    return { ...item, read }
  })
  if (delta === 0) return data
  return { ...data, items, unread_total: Math.max(0, data.unread_total + delta) }
}

function useOptimisticReadState(mutationFn: (id: number) => Promise<void>, read: boolean) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['errors'] })
      const previous = queryClient.getQueryData<ErrorsResponse>(['errors'])
      queryClient.setQueryData<ErrorsResponse>(['errors'], (old) => patchItemRead(old, id, read))
      return { previous }
    },
    onError: (_error, _id, context) => {
      if (context?.previous !== undefined) queryClient.setQueryData(['errors'], context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['errors'] })
    },
  })
}

/** Mark one error read (idempotent server-side; reading never deletes). */
export function useMarkErrorRead() {
  return useOptimisticReadState((id) => post(`/api/v1/errors/${id}/read`, {}), true)
}

/** Mark one error unread (spec:1434). */
export function useMarkErrorUnread() {
  return useOptimisticReadState((id) => post(`/api/v1/errors/${id}/unread`, {}), false)
}

/** Mark every unread error read (spec:1435). */
export function useMarkAllErrorsRead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => post('/api/v1/errors/read-all', {}),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['errors'] })
      const previous = queryClient.getQueryData<ErrorsResponse>(['errors'])
      queryClient.setQueryData<ErrorsResponse>(['errors'], (old) =>
        old ? { ...old, items: old.items.map((item) => ({ ...item, read: true })), unread_total: 0 } : old,
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous !== undefined) queryClient.setQueryData(['errors'], context.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['errors'] })
    },
  })
}

/** Fetch scrubbed Markdown diagnostic report (phase 7 spec 7.3). */
export function useDiagnosticReport() {
  return useMutation({
    mutationFn: (ids: number[]) =>
      fetchText('/api/v1/errors/diagnostic', {
        method: 'POST',
        body: JSON.stringify({ ids: ids.length > 0 ? ids : null }),
      }),
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
