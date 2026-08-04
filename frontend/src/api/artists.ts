import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, get } from './client'

export type ArtistSource = 'tag_artist' | 'tag_albumartist' | 'tag_feat' | 'tag_contrib' | 'manual'

export interface ArtistItem {
  id: number
  name: string
  source: ArtistSource
  mbid: string | null
  mb_match_score: number | null
  ignored: 0 | 1
  releases_count: number
}

export interface ArtistsResponse {
  items: ArtistItem[]
  total: number
  page: number
  page_size: number
}

export interface ArtistFilters {
  ignored: 'all' | 'yes' | 'no'
  q: string
}

function buildUrl(filters: ArtistFilters, page: number): string {
  const params = new URLSearchParams()
  params.set('page', String(page))
  if (filters.ignored !== 'all') params.set('ignored', filters.ignored)
  if (filters.q) params.set('q', filters.q)
  return `/api/v1/artists?${params.toString()}`
}

export function useArtists(filters: ArtistFilters) {
  return useInfiniteQuery<ArtistsResponse>({
    queryKey: ['artists', filters],
    queryFn: ({ pageParam }) => get<ArtistsResponse>(buildUrl(filters, pageParam as number)),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
  })
}

/** Total number of non-ignored artists (used by the About section). */
export function useTrackedArtistsCount() {
  return useQuery<number>({
    queryKey: ['artists-count'],
    queryFn: async () => {
      const body = await get<ArtistsResponse>('/api/v1/artists?ignored=no&page_size=1')
      return body.total
    },
  })
}

export function useAddArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<ArtistItem>('/api/v1/artists', { method: 'POST', body: JSON.stringify({ name }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}

/** Optimistic ignored toggle with rollback on error (spec 11.2.4). */
function patchArtistIgnored(old: unknown, id: number, ignored: boolean): unknown {
  if (!old || typeof old !== 'object') return old
  const isInfinite = 'pages' in old && Array.isArray((old as { pages: unknown }).pages)
  if (isInfinite) {
    const infinite = old as { pages: ArtistsResponse[]; pageParams: unknown[] }
    return {
      ...infinite,
      pages: infinite.pages.map((page) => ({
        ...page,
        items: page.items.map((artist) =>
          artist.id === id ? { ...artist, ignored: ignored ? 1 : 0 } : artist,
        ),
      })),
    }
  }
  const response = old as ArtistsResponse
  if (!Array.isArray(response.items)) return old
  return {
    ...response,
    items: response.items.map((artist) =>
      artist.id === id ? { ...artist, ignored: ignored ? 1 : 0 } : artist,
    ),
  }
}

export function useSetArtistIgnored() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ignored }: { id: number; ignored: boolean }) =>
      apiFetch<ArtistItem>(`/api/v1/artists/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ ignored: ignored ? 1 : 0 }),
      }),
    onMutate: async ({ id, ignored }) => {
      await queryClient.cancelQueries({ queryKey: ['artists'] })
      const previous = queryClient.getQueriesData({ queryKey: ['artists'] })
      queryClient.setQueriesData({ queryKey: ['artists'] }, (old) =>
        patchArtistIgnored(old, id, ignored),
      )
      return { previous }
    },
    onError: (_error, _patch, context) => {
      if (context?.previous) {
        for (const [key, data] of context.previous) queryClient.setQueryData(key, data)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}

/** Retry the MusicBrainz match for one artist (POST /artists/{id}/rematch). */
export function useRematchArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<{ matched: boolean; mbid: string | null }>(`/api/v1/artists/${id}/rematch`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}
