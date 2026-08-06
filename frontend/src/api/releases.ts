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
  rgid: string | null
  cover_key: string
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

export interface ReleaseTrack {
  position: number
  title: string
  duration_s: number | null
}

export interface ReleaseDetail extends ReleaseListItem {
  secondary_types: string
  cover_url: string | null
  source: string
  spotify_url: string | null
  deezer_url: string | null
  ytm_url: string | null
  apple_music_url: string | null
  tidal_url: string | null
  qobuz_url: string | null
  discogs_url: string | null
  beatport_url: string | null
  google_url: string | null
  tracks: ReleaseTrack[]
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

/** Per-card "seen" toggle from the feed list (phase 12b), optimistic. */
function patchReleaseSeen(old: unknown, id: number, seen: boolean): unknown {
  if (!old || typeof old !== 'object') return old
  const isInfinite = 'pages' in old && Array.isArray((old as { pages: unknown }).pages)
  if (isInfinite) {
    const infinite = old as { pages: ReleasesResponse[]; pageParams: unknown[] }
    return {
      ...infinite,
      pages: infinite.pages.map((page) => ({
        ...page,
        items: page.items.map((release) =>
          release.id === id ? { ...release, seen: seen ? 1 : 0 } : release,
        ),
      })),
    }
  }
  return old
}

export function useSetReleaseSeen() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, seen }: { id: number; seen: boolean }) =>
      post(`/api/v1/releases/${id}/state`, { seen }),
    onMutate: async ({ id, seen }) => {
      await queryClient.cancelQueries({ queryKey: ['releases'] })
      const previous = queryClient.getQueriesData({ queryKey: ['releases'] })
      queryClient.setQueriesData({ queryKey: ['releases'] }, (old) => patchReleaseSeen(old, id, seen))
      return { previous }
    },
    onError: (_error, _patch, context) => {
      if (context?.previous) {
        for (const [key, data] of context.previous) queryClient.setQueryData(key, data)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['releases'] })
    },
  })
}
