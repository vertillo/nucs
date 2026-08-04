import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { get, post } from './client'

export type ReleaseType = 'album' | 'single' | 'ep' | 'other'
export type ArtistRole = 'primary' | 'featured' | 'contributor'

export interface MatchedArtist {
  id: number
  name: string
  role: ArtistRole
}

export interface ReleaseListItem {
  id: number
  rgid: string
  title: string
  primary_artist: string
  type: ReleaseType
  first_release_date: string
  cover_path: string | null
  seen: 0 | 1
  hidden: 0 | 1
  favorite: 0 | 1
  matched_artists: MatchedArtist[]
}

export interface ReleaseDetail extends ReleaseListItem {
  secondary_types: string
  cover_url: string | null
  spotify_url: string | null
  deezer_url: string | null
  ytm_url: string | null
  google_url: string | null
  discovered_at: string
  seen_at: string | null
}

export interface ReleasesResponse {
  items: ReleaseListItem[]
  total: number
  page: number
  page_size: number
}

export interface ReleaseFilters {
  type: ReleaseType | 'all'
  unseenOnly: boolean
  q: string
}

function buildUrl(filters: ReleaseFilters, page: number): string {
  const params = new URLSearchParams()
  params.set('page', String(page))
  if (filters.type !== 'all') params.set('type', filters.type)
  if (filters.unseenOnly) params.set('seen', 'no')
  if (filters.q) params.set('q', filters.q)
  return `/api/v1/releases?${params.toString()}`
}

export function useReleases(filters: ReleaseFilters) {
  return useInfiniteQuery<ReleasesResponse>({
    queryKey: ['releases', filters],
    queryFn: ({ pageParam }) => get<ReleasesResponse>(buildUrl(filters, pageParam as number)),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
  })
}

export function useRelease(id: string | undefined) {
  return useQuery<ReleaseDetail>({
    queryKey: ['release', id],
    queryFn: () => get<ReleaseDetail>(`/api/v1/releases/${id}`),
    enabled: id !== undefined,
  })
}

export interface ReleaseStatePatch {
  seen?: boolean
  hidden?: boolean
  favorite?: boolean
}

/** Optimistic state update (seen/hidden/favorite) with rollback on error. */
export function useSetReleaseState(id: number | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (patch: ReleaseStatePatch) => post(`/api/v1/releases/${id}/state`, patch),
    onMutate: async (patch) => {
      if (id === undefined) return undefined
      await queryClient.cancelQueries({ queryKey: ['release', String(id)] })
      const previous = queryClient.getQueryData<ReleaseDetail>(['release', String(id)])
      if (previous) {
        const next = { ...previous }
        if (patch.seen !== undefined) next.seen = patch.seen ? 1 : 0
        if (patch.hidden !== undefined) next.hidden = patch.hidden ? 1 : 0
        if (patch.favorite !== undefined) next.favorite = patch.favorite ? 1 : 0
        queryClient.setQueryData(['release', String(id)], next)
      }
      return { previous }
    },
    onError: (_error, _patch, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(['release', String(id)], context.previous)
      }
    },
    onSettled: () => {
      if (id !== undefined) {
        queryClient.invalidateQueries({ queryKey: ['release', String(id)] })
        queryClient.invalidateQueries({ queryKey: ['releases'] })
      }
    },
  })
}

export function useSeenAll() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => post('/api/v1/releases/seen-all', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['releases'] })
    },
  })
}
