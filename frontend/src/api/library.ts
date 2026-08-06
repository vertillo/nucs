import { useMutation } from '@tanstack/react-query'
import { apiFetch } from './client'

/** Wipe the whole library: artists, releases, states, caches, covers on disk. */
export function useResetLibrary() {
  return useMutation({
    mutationFn: () => apiFetch<void>('/api/v1/library', { method: 'DELETE' }),
  })
}
