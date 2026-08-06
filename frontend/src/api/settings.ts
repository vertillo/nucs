import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, get } from './client'

export interface Settings {
  discovery_from_date: string
  scan_library_time: string
  scan_releases_time: string
  feat_scan_enabled: 'true' | 'false'
  feat_scan_weekday: string
  notify_enabled: 'true' | 'false'
  notify_urls: string
  theme: 'dark' | 'light'
  release_types: string
  mb_contact_email: string
  spotify_client_id_set: boolean
  spotify_client_secret_set: boolean
  discogs_token_set: boolean
  discovery_filter_official: 'true' | 'false'
}

export function useSettings() {
  return useQuery<Settings>({
    queryKey: ['settings'],
    queryFn: () => get<Settings>('/api/v1/settings'),
  })
}

export function useUpdateSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: Record<string, string | boolean>) =>
      apiFetch<Settings>('/api/v1/settings', { method: 'PUT', body: JSON.stringify(patch) }),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

export interface ScanRun {
  id: number
  type: 'library' | 'releases' | 'feat'
  started_at: string
  finished_at: string | null
  status: 'ok' | 'error'
  stats: Record<string, number | string> | null
}

export interface ScanProgress {
  total: number
  done: number
  phase: string
}

export interface ScanStatus {
  running: { type: string; since: string; progress: ScanProgress } | null
  last_runs: ScanRun[]
}

/** Polls /scans/status every 3s only while a scan is running (spec 11.2.5). */
export function useScanStatus() {
  return useQuery<ScanStatus>({
    queryKey: ['scan-status'],
    queryFn: () => get<ScanStatus>('/api/v1/scans/status'),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
  })
}

export function useStartScan() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (type: 'library' | 'releases' | 'feat') => apiFetch<void>(`/api/v1/scans/${type}`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scan-status'] })
    },
  })
}

export function useNotifyTest() {
  return useMutation({
    mutationFn: () =>
      apiFetch<{ sent: boolean }>('/api/v1/settings/notify-test', { method: 'POST', body: '{}' }),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: ({ current_password, new_password }: { current_password: string; new_password: string }) =>
      apiFetch<void>('/api/v1/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password, new_password }),
      }),
  })
}

export interface ActiveSession {
  id: string
  ip: string
  user_agent: string
  last_seen_at: string
  current: boolean
}

export function useSessions() {
  return useQuery<ActiveSession[]>({
    queryKey: ['sessions'],
    queryFn: () => get<ActiveSession[]>('/api/v1/auth/sessions'),
  })
}

export function useRevokeOtherSessions() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiFetch<void>('/api/v1/auth/sessions/revoke-others', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}

export interface Health {
  status: string
  version: string
}

export function useHealth() {
  return useQuery<Health>({
    queryKey: ['health'],
    queryFn: () => get<Health>('/api/health'),
  })
}
