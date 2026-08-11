import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch, get } from './client'

export type ArtistSource = 'tag_artist' | 'tag_albumartist' | 'tag_feat' | 'tag_contrib' | 'tag_remix' | 'manual'
export type ArtistProvider = 'mb' | 'deezer' | 'itunes' | 'discogs' | 'soundcloud' | 'beatport' | 'manual'
export type ArtistStatus = 'Linked' | 'Needs match' | 'Ignored'

export interface ArtistIdentity {
  provider: string
  provider_id: string
  external_url: string | null
  match_score: number | null
  link_method: string | null
}

export interface ArtistItem {
  id: number
  name: string
  source: ArtistSource
  provider: ArtistProvider
  provider_id: string | null
  external_url: string | null
  mbid: string | null
  mb_match_score: number | null
  ignored: 0 | 1
  /* Phase 1 identity-model additions — additive; legacy provider/mbid fields
   * still present in the API during the contract freeze (phase 8 retires them). */
  status: ArtistStatus
  identities: ArtistIdentity[]
  split_from_artist_id: number | null
  releases_count: number
  source_files: string[]
}

export interface ArtistsResponse {
  items: ArtistItem[]
  total: number
  unmatched_total: number
  page: number
  page_size: number
}

export interface ArtistFilters {
  ignored: 'all' | 'yes' | 'no'
  matched: 'all' | 'no'
  q: string
  sort: 'name_asc' | 'name_desc'
}

export interface ArtistCandidate {
  name: string
  provider: ArtistProvider
  provider_id: string | null
  mbid: string | null
  score: number | null
  url: string | null
}

export interface RematchResult {
  matched: boolean
  mbid: string | null
  resolved_split: boolean
  split_parts: string[]
  candidates: ArtistCandidate[]
}

function buildUrl(filters: ArtistFilters, page: number): string {
  const params = new URLSearchParams()
  params.set('page', String(page))
  if (filters.ignored !== 'all') params.set('ignored', filters.ignored)
  if (filters.matched !== 'all') params.set('matched', filters.matched)
  if (filters.q) params.set('q', filters.q)
  if (filters.sort !== 'name_asc') params.set('sort', filters.sort)
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

/** Multi-provider name search for the add-artist and retry pickers. */
export function useArtistSearch(q: string) {
  return useQuery<{ items: ArtistCandidate[] }>({
    queryKey: ['artist-search', q],
    queryFn: () => get<{ items: ArtistCandidate[] }>(`/api/v1/artists/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
  })
}

export interface AddArtistPayload {
  name?: string
  provider?: ArtistProvider
  provider_id?: string
  mbid?: string | null
  external_url?: string | null
  url?: string
}

export function useAddArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: AddArtistPayload) =>
      apiFetch<ArtistItem>('/api/v1/artists', { method: 'POST', body: JSON.stringify(payload) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}

export interface ArtistDetails {
  provider: ArtistProvider
  provider_id: string
  name: string
  disambiguation?: string
  type?: string
  country?: string
  begin?: string
  end?: string
  aliases?: string[]
  nb_album?: number
  nb_fan?: number
  picture?: string
  genre?: string
  url?: string
  profile?: string
}

/** Provider-side details of one candidate (match picker panel, phase 15). */
export function useArtistLookup(candidate: ArtistCandidate | null) {
  return useQuery<ArtistDetails>({
    queryKey: ['artist-lookup', candidate?.provider, candidate?.provider_id],
    queryFn: () =>
      get<ArtistDetails>(
        `/api/v1/artists/lookup?provider=${encodeURIComponent(candidate?.provider ?? '')}&provider_id=${encodeURIComponent(
          candidate?.provider_id ?? '',
        )}`,
      ),
    enabled: !!candidate && !!candidate.provider_id,
    retry: false,
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

/** Retry the match for one artist: returns candidates for the picker. */
export function useRematchArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<RematchResult>(`/api/v1/artists/${id}/rematch`, {
        method: 'POST',
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}

export interface LinkArtistPayload {
  id: number
  url?: string
  provider?: ArtistProvider
  provider_id?: string
}

/** Track an artist by provider URL or an explicit provider pair (parsed
 * server-side; the URL is never fetched). */
export function useLinkArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, url, provider, provider_id }: LinkArtistPayload) =>
      apiFetch<ArtistItem>(`/api/v1/artists/${id}/link`, {
        method: 'POST',
        body: JSON.stringify({ url, provider, provider_id }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}

/** Delete an artist (release links cascade; releases stay). */
export function useDeleteArtist() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/api/v1/artists/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    },
  })
}
