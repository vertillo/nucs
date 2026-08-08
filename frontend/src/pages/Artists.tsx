import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  useAddArtist,
  useArtistLookup,
  useArtistSearch,
  useArtists,
  useDeleteArtist,
  useLinkArtist,
  useRematchArtist,
  useSetArtistIgnored,
  type AddArtistPayload,
  type ArtistCandidate,
  type ArtistItem,
  type ArtistSource,
} from '../api/artists'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import Toast, { useToast } from '../components/Toast'

const SOURCE_LABEL: Record<ArtistSource, string> = {
  tag_artist: 'Artist',
  tag_albumartist: 'Album artist',
  tag_feat: 'Featuring',
  tag_contrib: 'Contributor',
  tag_remix: 'Remixer',
  manual: 'Manual',
}

const PROVIDER_LABEL: Record<string, string> = {
  mb: 'MusicBrainz',
  deezer: 'Deezer',
  itunes: 'Apple Music',
  discogs: 'Discogs',
  soundcloud: 'SoundCloud',
  beatport: 'Beatport',
  manual: 'Manual',
}

const IGNORED_OPTIONS: { value: 'all' | 'yes' | 'no'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'no', label: 'Active' },
  { value: 'yes', label: 'Ignored' },
]

const MATCHED_OPTIONS: { value: 'all' | 'no'; label: string }[] = [
  { value: 'all', label: 'All matches' },
  { value: 'no', label: 'Unmatched only' },
]

const inputClass =
  'w-full rounded-xl border border-light-border bg-light-bg px-3 py-2 text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-bg dark:text-dark-text'

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 6 }, (_, i) => (
        <tr key={i} className="border-b border-light-border dark:border-dark-border">
          {Array.from({ length: 6 }, (_, j) => (
            <td key={j} className="px-4 py-3">
              <div className="h-4 w-2/3 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

/** Shortened display of one library file path (basename + parent). */
function shortPath(path: string): string {
  const parts = path.split('/')
  return parts.length > 2 ? `…/${parts[parts.length - 2]}/${parts[parts.length - 1]}` : path
}

/** The provider page where the artist's match was found (phase 15). */
function providerUrl(artist: ArtistItem): string | null {
  if (artist.external_url) return artist.external_url
  if (artist.mbid) return `https://musicbrainz.org/artist/${artist.mbid}`
  switch (artist.provider) {
    case 'deezer':
      return artist.provider_id ? `https://www.deezer.com/artist/${artist.provider_id}` : null
    case 'itunes':
      return artist.provider_id ? `https://music.apple.com/artist/${artist.provider_id}` : null
    case 'discogs':
      return artist.provider_id ? `https://www.discogs.com/artist/${artist.provider_id}` : null
    case 'soundcloud':
      return artist.provider_id ? `https://soundcloud.com/${artist.provider_id}` : null
    case 'beatport':
      return artist.provider_id ? `https://www.beatport.com/artist/${artist.provider_id}` : null
    default:
      return null
  }
}

/** "Match" cell: MusicBrainz, a provider link, Unmatched (+Retry) or Split. */
function MatchCell({
  artist,
  onRetry,
}: {
  artist: ArtistItem
  onRetry: (artist: { id: number; name: string }) => void
}) {
  const url = providerUrl(artist)
  if (artist.mbid) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true">✅</span>
        <span className="font-semibold text-accentText dark:text-accent">{artist.mb_match_score ?? ''}</span>
        <a
          href={`https://musicbrainz.org/artist/${artist.mbid}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs font-medium text-light-textDim underline-offset-2 hover:underline dark:text-dark-textDim"
        >
          MusicBrainz ↗
        </a>
      </span>
    )
  }
  if (artist.provider !== 'manual') {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true">✅</span>
        <span className="font-semibold text-accentText dark:text-accent">
          {PROVIDER_LABEL[artist.provider] ?? artist.provider}
        </span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-light-textDim underline-offset-2 hover:underline dark:text-dark-textDim"
          >
            open ↗
          </a>
        )}
      </span>
    )
  }
  if (artist.ignored) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true">✂️</span>
        <span className="text-light-textDim dark:text-dark-textDim">Split</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden="true">⚠️</span>
      <span className="text-light-textDim dark:text-dark-textDim">Unmatched</span>
      <button
        type="button"
        onClick={() => onRetry({ id: artist.id, name: artist.name })}
        className="rounded-full px-3 py-1 text-sm font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-dark-surface2"
      >
        Retry
      </button>
    </span>
  )
}

/** Artist name, linked to the provider page when the artist is matched. */
function ArtistName({ artist }: { artist: ArtistItem }) {
  const url = providerUrl(artist)
  const label = <span className="font-medium text-light-text dark:text-dark-text">{artist.name}</span>
  if (!url) return label
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      title={url}
      className="font-medium text-light-text underline-offset-2 hover:text-accentText hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-text dark:hover:text-accent"
    >
      {artist.name}
    </a>
  )
}

export default function Artists() {
  const [ignored, setIgnored] = useState<'all' | 'yes' | 'no'>('all')
  const [matched, setMatched] = useState<'all' | 'no'>('all')
  const [sort, setSort] = useState<'name_asc' | 'name_desc'>('name_asc')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [addQuery, setAddQuery] = useState('')
  const [addError, setAddError] = useState<string | null>(null)
  const [retryArtist, setRetryArtist] = useState<{ id: number; name: string } | null>(null)
  const nameInput = useRef<HTMLInputElement>(null)
  const { toast, show } = useToast()

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (!modalOpen) return
    nameInput.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setModalOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [modalOpen])

  const { data, isPending, isError, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } = useArtists({
    ignored,
    matched,
    q: debouncedSearch.trim(),
    sort,
  })
  const setIgnore = useSetArtistIgnored()
  const addArtist = useAddArtist()
  const linkArtist = useLinkArtist()
  const deleteArtist = useDeleteArtist()

  const items = data?.pages.flatMap((page) => page.items) ?? []
  const total = data?.pages[0]?.total ?? 0
  const unmatchedTotal = data?.pages[0]?.unmatched_total ?? 0

  const sentinelRef = useRef<HTMLDivElement>(null)
  useInfiniteScroll(sentinelRef, !!hasNextPage, isFetchingNextPage, () => {
    void fetchNextPage()
  })

  function openModal() {
    setAddQuery('')
    setAddError(null)
    setModalOpen(true)
  }

  function handleAddCandidate(candidate: ArtistCandidate) {
    setAddError(null)
    addArtist.mutate(
      {
        name: candidate.name,
        provider: candidate.provider,
        provider_id: candidate.provider_id ?? undefined,
        mbid: candidate.mbid,
        external_url: candidate.url,
      },
      {
        onSuccess: () => {
          setModalOpen(false)
          show('Artist added')
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 400) {
            setAddError(error.message)
          } else {
            setAddError('Something went wrong. Try again.')
          }
        },
      },
    )
  }

  function handleAddWithUrl(name: string, urlValue: string) {
    const payload: AddArtistPayload = {}
    if (name.trim()) payload.name = name.trim()
    if (urlValue.trim()) payload.url = urlValue.trim()
    if (!payload.name && !payload.url) {
      setAddError('Enter an artist name or a URL.')
      return
    }
    setAddError(null)
    addArtist.mutate(payload, {
      onSuccess: () => {
        setModalOpen(false)
        show('Artist added')
      },
      onError: (error) => {
        if (error instanceof ApiError && (error.status === 400 || error.status === 422)) {
          setAddError(error.message)
        } else {
          setAddError('Something went wrong. Try again.')
        }
      },
    })
  }

  function handlePickCandidate(candidate: ArtistCandidate) {
    if (!retryArtist) return
    linkArtist.mutate(
      {
        id: retryArtist.id,
        provider: candidate.provider,
        provider_id: candidate.provider_id ?? undefined,
        url: candidate.url ?? undefined,
      },
      {
        onSuccess: () => {
          setRetryArtist(null)
          show('Artist matched')
        },
        onError: (error) => show(error.message, 'error'),
      },
    )
  }

  function handleDelete(artistId: number, name: string) {
    if (!window.confirm(`Delete artist "${name}"? Releases stay but lose this artist.`)) return
    deleteArtist.mutate(artistId, {
      onSuccess: () => show('Artist deleted'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">Tracked artists</h1>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search artist…"
          aria-label="Search artist"
          className="min-w-0 flex-1 rounded-full border border-light-border bg-light-surface px-4 py-1.5 text-sm text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text sm:max-w-[240px]"
        />
        <label className="sr-only" htmlFor="artist-ignored-filter">
          Filter artists
        </label>
        <select
          id="artist-ignored-filter"
          value={ignored}
          onChange={(e) => setIgnored(e.target.value as 'all' | 'yes' | 'no')}
          className="rounded-full border border-light-border bg-light-surface px-3 py-1.5 text-sm text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text"
        >
          {IGNORED_OPTIONS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="artist-matched-filter">
          Match filter
        </label>
        <div className="flex items-center gap-2">
          <select
            id="artist-matched-filter"
            value={matched}
            onChange={(e) => setMatched(e.target.value as 'all' | 'no')}
            className="rounded-full border border-light-border bg-light-surface px-3 py-1.5 text-sm text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text"
          >
            {MATCHED_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <span
            title="Artists without a match"
            className="rounded-full bg-light-surface2 px-2.5 py-1 text-xs font-semibold text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim"
          >
            {unmatchedTotal} unmatched
          </span>
        </div>
        <button
          type="button"
          onClick={openModal}
          className="rounded-full bg-accent px-4 py-1.5 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          + Add artist
        </button>
      </div>

      {isPending && (
        <table className="mt-6 hidden w-full border-collapse md:table">
          <tbody>
            <SkeletonRows />
          </tbody>
        </table>
      )}

      {isError && (
        <div className="mt-16 flex flex-col items-center gap-3 text-center">
          <p className="text-light-textDim dark:text-dark-textDim">Something went wrong loading artists.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retry
          </button>
        </div>
      )}

      {!isPending && !isError && items.length === 0 && (
        <p className="mt-16 text-center text-light-textDim dark:text-dark-textDim">No artists found.</p>
      )}

      {!isPending && !isError && items.length > 0 && (
        <>
          <table className="mt-6 hidden w-full border-collapse md:table">
            <thead>
              <tr className="border-b border-light-border text-left text-xs uppercase tracking-wide text-light-textDim dark:border-dark-border dark:text-dark-textDim">
                <th className="px-4 py-2 font-medium">
                  <button
                    type="button"
                    aria-sort={sort === 'name_asc' ? 'ascending' : 'descending'}
                    onClick={() => setSort(sort === 'name_asc' ? 'name_desc' : 'name_asc')}
                    className="inline-flex items-center gap-1 uppercase tracking-wide text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim dark:hover:text-dark-text"
                  >
                    Name
                    <span aria-hidden="true">{sort === 'name_asc' ? '▲' : '▼'}</span>
                  </button>
                </th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">Match</th>
                <th className="px-4 py-2 font-medium">Releases</th>
                <th className="px-4 py-2 font-medium">Ignore</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {items.map((artist) => (
                <tr key={artist.id} className="border-b border-light-border dark:border-dark-border">
                  <td className="px-4 py-3">
                    <ArtistName artist={artist} />
                    {artist.mbid == null && artist.provider === 'manual' && artist.source_files.length > 0 && (
                      <p className="mt-0.5 text-xs text-light-textDim dark:text-dark-textDim">
                        {artist.source_files.map(shortPath).join(' · ')}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-xs font-medium text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
                      {SOURCE_LABEL[artist.source]}
                    </span>
                    {artist.provider !== 'manual' && artist.provider !== 'mb' && (
                      <span className="ml-1 rounded-full bg-light-surface2 px-2 py-0.5 text-xs font-medium text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
                        {PROVIDER_LABEL[artist.provider]}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <MatchCell artist={artist} onRetry={setRetryArtist} />
                  </td>
                  <td className="px-4 py-3 text-light-textDim dark:text-dark-textDim">{artist.releases_count}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={!!artist.ignored}
                      aria-label={`Ignore ${artist.name}`}
                      onClick={() => setIgnore.mutate({ id: artist.id, ignored: !artist.ignored })}
                      className={`relative h-5 w-9 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                        artist.ignored ? 'bg-accent' : 'bg-light-border dark:bg-dark-border'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-light-bg transition-all dark:bg-dark-bg ${
                          artist.ignored ? 'left-[18px]' : 'left-0.5'
                        }`}
                      />
                    </button>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      aria-label={`Delete ${artist.name}`}
                      title="Delete artist"
                      onClick={() => handleDelete(artist.id, artist.name)}
                      disabled={deleteArtist.isPending}
                      className="rounded-full px-2 py-1 text-sm font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <ul className="mt-4 space-y-3 md:hidden">
            {items.map((artist) => (
              <li key={artist.id} className="rounded-2xl bg-light-surface p-4 dark:bg-dark-surface">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <ArtistName artist={artist} />
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                      <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-xs font-medium text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
                        {SOURCE_LABEL[artist.source]}
                      </span>
                      <MatchCell artist={artist} onRetry={setRetryArtist} />
                    </div>
                    <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
                      {artist.releases_count} release{artist.releases_count === 1 ? '' : 's'}
                    </p>
                    {artist.mbid == null && artist.provider === 'manual' && artist.source_files.length > 0 && (
                      <p className="mt-1 text-xs text-light-textDim dark:text-dark-textDim">
                        {artist.source_files.map(shortPath).join(' · ')}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={!!artist.ignored}
                      aria-label={`Ignore ${artist.name}`}
                      onClick={() => setIgnore.mutate({ id: artist.id, ignored: !artist.ignored })}
                      className={`relative h-5 w-9 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                        artist.ignored ? 'bg-accent' : 'bg-light-border dark:bg-dark-border'
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 h-4 w-4 rounded-full bg-light-bg transition-all dark:bg-dark-bg ${
                          artist.ignored ? 'left-[18px]' : 'left-0.5'
                        }`}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(artist.id, artist.name)}
                      disabled={deleteArtist.isPending}
                      className="rounded-full px-2 py-0.5 text-xs font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>

          <div ref={sentinelRef} className="mt-8 text-center text-sm text-light-textDim dark:text-dark-textDim">
            {isFetchingNextPage ? (
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-light-border border-t-accent dark:border-dark-border dark:border-t-accent" />
            ) : hasNextPage ? (
              <span>Loading more…</span>
            ) : (
              <span>
                {items.length} of {total}
              </span>
            )}
          </div>
        </>
      )}

      {modalOpen && (
        <AddArtistModal
          {...{ addQuery, setAddQuery, addError, nameInput, handleAddCandidate, handleAddWithUrl, addArtist, setModalOpen }}
        />
      )}

      {retryArtist && (
        <RetryModal
          artistId={retryArtist.id}
          onClose={() => setRetryArtist(null)}
          onPickCandidate={handlePickCandidate}
          onMatched={() => setRetryArtist(null)}
          show={show}
        />
      )}

      <Toast toast={toast} />
    </div>
  )
}

/** One candidate row; clicking opens the match-details panel. */
function CandidateRow({
  candidate,
  onClick,
  disabled,
}: {
  candidate: ArtistCandidate
  onClick: () => void
  disabled: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full items-center justify-between gap-3 rounded-xl bg-light-bg px-3 py-2 text-left text-sm transition-colors hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-bg dark:hover:bg-dark-surface2"
    >
      <span className="min-w-0 truncate font-medium text-light-text dark:text-dark-text">{candidate.name}</span>
      <span className="shrink-0 text-xs text-light-textDim dark:text-dark-textDim">
        {PROVIDER_LABEL[candidate.provider] ?? candidate.provider}
        {candidate.score != null ? ` · ${candidate.score}` : ''}
      </span>
    </button>
  )
}

/** Provider-side details of one candidate with a pick/back action (phase 15). */
function CandidateDetailsPanel({
  candidate,
  onPick,
  onBack,
  pickLabel,
  picking,
}: {
  candidate: ArtistCandidate
  onPick: () => void
  onBack: () => void
  pickLabel: string
  picking: boolean
}) {
  const lookup = useArtistLookup(candidate)
  const details = lookup.data
  return (
    <div className="rounded-xl bg-light-bg p-3 dark:bg-dark-bg">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-light-text dark:text-dark-text">{details?.name ?? candidate.name}</p>
          <p className="text-xs text-light-textDim dark:text-dark-textDim">
            {PROVIDER_LABEL[candidate.provider] ?? candidate.provider}
            {candidate.score != null ? ` · score ${candidate.score}` : ''}
          </p>
        </div>
        <button
          type="button"
          onClick={onBack}
          className="shrink-0 text-sm text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim dark:hover:text-dark-text"
        >
          ← Back
        </button>
      </div>
      {lookup.isPending && (
        <p className="mt-2 text-xs text-light-textDim dark:text-dark-textDim">Loading details…</p>
      )}
      {details && (
        <div className="mt-2 space-y-1 text-xs text-light-textDim dark:text-dark-textDim">
          {details.disambiguation && <p>Disambiguation: {details.disambiguation}</p>}
          {details.type && <p>Type: {details.type}</p>}
          {details.country && <p>Country: {details.country}</p>}
          {details.begin && (
            <p>
              Active: {details.begin}
              {details.end ? ` – ${details.end}` : ' – present'}
            </p>
          )}
          {details.genre && <p>Genre: {details.genre}</p>}
          {details.nb_album != null && (
            <p>
              {details.nb_album} albums
              {details.nb_fan != null ? ` · ${details.nb_fan.toLocaleString()} fans` : ''}
            </p>
          )}
          {details.aliases && details.aliases.length > 0 && <p>Aliases: {details.aliases.join(', ')}</p>}
          {details.profile && <p className="line-clamp-3">{details.profile}</p>}
        </div>
      )}
      {lookup.isError && <p className="mt-2 text-xs text-dangerText dark:text-danger">Details unavailable.</p>}
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          disabled={picking}
          onClick={onPick}
          className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
        >
          {picking ? 'Working…' : pickLabel}
        </button>
      </div>
    </div>
  )
}

function AddArtistModal({
  addQuery,
  setAddQuery,
  addError,
  nameInput,
  handleAddCandidate,
  handleAddWithUrl,
  addArtist,
  setModalOpen,
}: {
  addQuery: string
  setAddQuery: (value: string) => void
  addError: string | null
  nameInput: React.RefObject<HTMLInputElement | null>
  handleAddCandidate: (candidate: ArtistCandidate) => void
  handleAddWithUrl: (name: string, url: string) => void
  addArtist: ReturnType<typeof useAddArtist>
  setModalOpen: (open: boolean) => void
}) {
  const [debounced, setDebounced] = useState('')
  const [url, setUrl] = useState('')
  const [selected, setSelected] = useState<ArtistCandidate | null>(null)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(addQuery), 400)
    return () => clearTimeout(timer)
  }, [addQuery])
  const search = useArtistSearch(debounced)
  const candidates = search.data?.items ?? []

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Add artist"
      onClick={() => setModalOpen(false)}
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-2xl bg-light-surface p-6 shadow-xl shadow-black/40 dark:bg-dark-surface"
      >
        <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">Add artist</h2>
        <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
          Search across MusicBrainz, Deezer, Apple Music and Discogs, then pick the right artist — or track one by URL.
        </p>
        <div className="mt-4 space-y-4">
          <div>
            <label
              htmlFor="add-artist-query"
              className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
            >
              Artist name
            </label>
            <input
              ref={nameInput as React.RefObject<HTMLInputElement>}
              id="add-artist-query"
              type="search"
              value={addQuery}
              onChange={(e) => {
                setAddQuery(e.target.value)
                setSelected(null)
              }}
              placeholder="Search…"
              className={inputClass}
            />
            {addError && (
              <p role="alert" className="mt-1 text-sm text-dangerText dark:text-danger">
                {addError}
              </p>
            )}
          </div>

          {debounced.trim().length >= 2 && search.isPending && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">Searching…</p>
          )}
          {debounced.trim().length >= 2 && !search.isPending && candidates.length > 0 && !selected && (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {candidates.map((candidate, index) => (
                <CandidateRow
                  key={`${candidate.provider}-${candidate.provider_id ?? index}`}
                  candidate={candidate}
                  disabled={addArtist.isPending}
                  onClick={() => setSelected(candidate)}
                />
              ))}
            </div>
          )}
          {debounced.trim().length >= 2 && !search.isPending && candidates.length === 0 && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">
              No matches found — you can add the name anyway (it will be matched later or tracked by URL).
            </p>
          )}
          {selected && (
            <CandidateDetailsPanel
              candidate={selected}
              onBack={() => setSelected(null)}
              onPick={() => handleAddCandidate(selected)}
              pickLabel="Track this artist"
              picking={addArtist.isPending}
            />
          )}

          <div>
            <label
              htmlFor="add-artist-url"
              className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
            >
              Track by URL (optional: MusicBrainz, Deezer, Apple Music, Discogs, SoundCloud, Beatport)
            </label>
            <input
              id="add-artist-url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.deezer.com/it/artist/265213582"
              className={inputClass}
            />
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setModalOpen(false)}
              className="rounded-full border border-light-border px-4 py-2 text-sm font-medium text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:border-dark-border dark:text-dark-textDim dark:hover:text-dark-text"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={addArtist.isPending}
              onClick={() => handleAddWithUrl(addQuery, url)}
              className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {addArtist.isPending ? 'Adding…' : 'Add artist'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function RetryModal({
  artistId,
  onClose,
  onPickCandidate,
  onMatched,
  show,
}: {
  artistId: number
  onClose: () => void
  onPickCandidate: (candidate: ArtistCandidate) => void
  onMatched: () => void
  show: (message: string, kind?: 'success' | 'error') => void
}) {
  const [url, setUrl] = useState('')
  const [linkError, setLinkError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<ArtistCandidate | null>(null)
  const rematch = useRematchArtist()
  const link = useLinkArtist()
  const urlInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 400)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    urlInput.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const result = rematch.data
  const candidates = result?.candidates ?? []
  const freeSearch = useArtistSearch(debouncedQuery)
  const freeCandidates = freeSearch.data?.items ?? []

  function handleRetry() {
    rematch.mutate(artistId, {
      onSuccess: (res) => {
        if (res.matched) {
          show('Matched on MusicBrainz')
          onMatched()
        } else if (res.resolved_split) {
          show('Artist already resolved via split')
          onMatched()
        } else if (res.split_parts.length > 0) {
          show(`Name split into ${res.split_parts.join(' + ')} (artist ignored)`)
          onMatched()
        }
      },
      onError: (error) => show(error.message, 'error'),
    })
  }

  function handleLink() {
    setLinkError(null)
    link.mutate(
      { id: artistId, url },
      {
        onSuccess: () => {
          show('Artist linked')
          onMatched()
        },
        onError: (error) => setLinkError(error.message),
      },
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Match artist"
      onClick={onClose}
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl bg-light-surface p-6 shadow-xl shadow-black/40 dark:bg-dark-surface"
      >
        <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">Match artist</h2>
        <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
          Search any name across providers, run the MusicBrainz match again, or track the artist by URL.
        </p>

        <div className="mt-4 space-y-3">
          <button
            type="button"
            onClick={handleRetry}
            className="rounded-full bg-light-surface2 px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            {rematch.isPending ? 'Searching…' : 'Search again by name'}
          </button>

          {rematch.data?.split_parts && rematch.data.split_parts.length > 0 && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">
              Possible split: {rematch.data.split_parts.join(' + ')}
            </p>
          )}
          {rematch.data?.resolved_split && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">
              This name was already resolved into parts (artist ignored).
            </p>
          )}

          {selected ? (
            <CandidateDetailsPanel
              candidate={selected}
              onBack={() => setSelected(null)}
              onPick={() => onPickCandidate(selected)}
              pickLabel="Link artist"
              picking={link.isPending}
            />
          ) : (
            <>
              <div>
                <label
                  htmlFor="retry-artist-search"
                  className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
                >
                  Search a name (not necessarily the artist's own)
                </label>
                <input
                  id="retry-artist-search"
                  type="search"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search…"
                  className={inputClass}
                />
                {debouncedQuery.trim().length >= 2 && freeSearch.isPending && (
                  <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">Searching…</p>
                )}
                {debouncedQuery.trim().length >= 2 && !freeSearch.isPending && freeCandidates.length > 0 && (
                  <div className="mt-1 max-h-44 space-y-1 overflow-y-auto">
                    {freeCandidates.map((candidate, index) => (
                      <CandidateRow
                        key={`${candidate.provider}-${candidate.provider_id ?? index}`}
                        candidate={candidate}
                        disabled={link.isPending}
                        onClick={() => setSelected(candidate)}
                      />
                    ))}
                  </div>
                )}
                {debouncedQuery.trim().length >= 2 && !freeSearch.isPending && freeCandidates.length === 0 && (
                  <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">No matches found.</p>
                )}
              </div>

              {candidates.length > 0 ? (
                <div className="max-h-44 space-y-1 overflow-y-auto">
                  {candidates.map((candidate, index) => (
                    <CandidateRow
                      key={`${candidate.provider}-${candidate.provider_id ?? index}`}
                      candidate={candidate}
                      disabled={link.isPending}
                      onClick={() => setSelected(candidate)}
                    />
                  ))}
                </div>
              ) : (
                !rematch.isPending && (
                  <p className="text-sm text-light-textDim dark:text-dark-textDim">
                    No candidates yet — run a search or link an artist URL below.
                  </p>
                )
              )}
            </>
          )}

          <div>
            <label
              htmlFor="link-artist-url"
              className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
            >
              Track by URL (MusicBrainz, Deezer, Apple Music, Discogs, SoundCloud, Beatport)
            </label>
            <input
              ref={urlInput}
              id="link-artist-url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.deezer.com/artist/1234"
              className={inputClass}
            />
            {linkError && (
              <p role="alert" className="mt-1 text-sm text-dangerText dark:text-danger">
                {linkError}
              </p>
            )}
            <button
              type="button"
              disabled={link.isPending || url.trim() === ''}
              onClick={handleLink}
              className="mt-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {link.isPending ? 'Linking…' : 'Link artist'}
            </button>
          </div>
        </div>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-light-border px-4 py-2 text-sm font-medium text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:border-dark-border dark:text-dark-textDim dark:hover:text-dark-text"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
