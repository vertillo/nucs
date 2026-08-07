import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  useAddArtist,
  useArtistSearch,
  useArtists,
  useDeleteArtist,
  useLinkArtist,
  useRematchArtist,
  useSetArtistIgnored,
  type ArtistCandidate,
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

export default function Artists() {
  const [ignored, setIgnored] = useState<'all' | 'yes' | 'no'>('all')
  const [matched, setMatched] = useState<'all' | 'no'>('all')
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
  })
  const setIgnore = useSetArtistIgnored()
  const addArtist = useAddArtist()
  const linkArtist = useLinkArtist()
  const deleteArtist = useDeleteArtist()

  const items = data?.pages.flatMap((page) => page.items) ?? []
  const total = data?.pages[0]?.total ?? 0

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

  function handleAddFallback() {
    const name = addQuery.trim()
    if (!name) {
      setAddError('Enter an artist name.')
      return
    }
    setAddError(null)
    addArtist.mutate(
      { name },
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

  function handlePickCandidate(candidate: ArtistCandidate) {
    if (!retryArtist) return
    linkArtist.mutate(
      { id: retryArtist.id, provider: candidate.provider, provider_id: candidate.provider_id ?? undefined },
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
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Source</th>
                <th className="px-4 py-2 font-medium">MB match</th>
                <th className="px-4 py-2 font-medium">Releases</th>
                <th className="px-4 py-2 font-medium">Ignore</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {items.map((artist) => (
                <tr key={artist.id} className="border-b border-light-border dark:border-dark-border">
                  <td className="px-4 py-3">
                    <p className="font-medium text-light-text dark:text-dark-text">{artist.name}</p>
                    {artist.mbid == null && artist.source_files.length > 0 && (
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
                    {artist.mbid ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span aria-hidden="true">✅</span>
                        <span className="font-semibold text-accentText dark:text-accent">{artist.mb_match_score ?? ''}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        <span aria-hidden="true">⚠️</span>
                        <span className="text-light-textDim dark:text-dark-textDim">Unmatched</span>
                        <button
                          type="button"
                          disabled={false}
                          onClick={() => setRetryArtist({ id: artist.id, name: artist.name })}
                          className="rounded-full px-3 py-1 text-sm font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:hover:bg-dark-surface2"
                        >
                          Retry
                        </button>
                      </span>
                    )}
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
                    <p className="truncate font-medium text-light-text dark:text-dark-text">{artist.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                      <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-xs font-medium text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
                        {SOURCE_LABEL[artist.source]}
                      </span>
                      {artist.mbid ? (
                        <span className="inline-flex items-center gap-1">
                          <span aria-hidden="true">✅</span>
                          <span className="font-semibold text-accentText dark:text-accent">{artist.mb_match_score ?? ''}</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5">
                          <span aria-hidden="true">⚠️</span>
                          <span className="text-light-textDim dark:text-dark-textDim">Unmatched</span>
                          <button
                            type="button"
                            disabled={false}
                            onClick={() => setRetryArtist({ id: artist.id, name: artist.name })}
                            className="rounded-full px-2.5 py-0.5 text-sm font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:hover:bg-dark-surface2"
                          >
                            Retry
                          </button>
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
                      {artist.releases_count} release{artist.releases_count === 1 ? '' : 's'}
                    </p>
                    {artist.mbid == null && artist.source_files.length > 0 && (
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

      {modalOpen && <AddArtistModal {...{ addQuery, setAddQuery, addError, nameInput, handleAddCandidate, handleAddFallback, addArtist, setModalOpen }} />}

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

function AddArtistModal({
  addQuery,
  setAddQuery,
  addError,
  nameInput,
  handleAddCandidate,
  handleAddFallback,
  addArtist,
  setModalOpen,
}: {
  addQuery: string
  setAddQuery: (value: string) => void
  addError: string | null
  nameInput: React.RefObject<HTMLInputElement | null>
  handleAddCandidate: (candidate: ArtistCandidate) => void
  handleAddFallback: () => void
  addArtist: ReturnType<typeof useAddArtist>
  setModalOpen: (open: boolean) => void
}) {
  const [debounced, setDebounced] = useState('')
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
          Search across MusicBrainz, Deezer, Apple Music and Discogs, then pick the right artist.
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
              onChange={(e) => setAddQuery(e.target.value)}
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
          {debounced.trim().length >= 2 && !search.isPending && candidates.length > 0 && (
            <div className="max-h-64 space-y-1 overflow-y-auto">
              {candidates.map((candidate, index) => (
                <button
                  key={`${candidate.provider}-${candidate.provider_id ?? index}`}
                  type="button"
                  disabled={addArtist.isPending}
                  onClick={() => handleAddCandidate(candidate)}
                  className="flex w-full items-center justify-between gap-3 rounded-xl bg-light-bg px-3 py-2 text-left text-sm transition-colors hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-bg dark:hover:bg-dark-surface2"
                >
                  <span className="min-w-0 truncate font-medium text-light-text dark:text-dark-text">
                    {candidate.name}
                  </span>
                  <span className="shrink-0 text-xs text-light-textDim dark:text-dark-textDim">
                    {PROVIDER_LABEL[candidate.provider] ?? candidate.provider}
                    {candidate.score != null ? ` · ${candidate.score}` : ''}
                  </span>
                </button>
              ))}
            </div>
          )}
          {debounced.trim().length >= 2 && !search.isPending && candidates.length === 0 && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">
              No matches found — you can add the name anyway (it will be matched later or tracked by URL).
            </p>
          )}

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
              onClick={handleAddFallback}
              className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
            >
              {addArtist.isPending ? 'Adding…' : 'Add by name'}
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
  const rematch = useRematchArtist()
  const link = useLinkArtist()
  const urlInput = useRef<HTMLInputElement>(null)

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

  function handleRetry() {
    rematch.mutate(artistId, {
      onSuccess: (res) => {
        if (res.matched) {
          show('Matched on MusicBrainz')
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
          Candidates found by name across providers, or track the artist by URL.
        </p>

        <div className="mt-4 space-y-3">
          <button
            type="button"
            disabled={false}
            onClick={handleRetry}
            className="rounded-full bg-light-surface2 px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            {rematch.isPending ? 'Searching…' : 'Search again by name'}
          </button>

          {rematch.data?.split && rematch.data.split.length > 0 && (
            <p className="text-sm text-light-textDim dark:text-dark-textDim">
              Possible split: {rematch.data.split.join(' + ')}
            </p>
          )}

          {candidates.length > 0 ? (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {candidates.map((candidate, index) => (
                <button
                  key={`${candidate.provider}-${candidate.provider_id ?? index}`}
                  type="button"
                  disabled={link.isPending}
                  onClick={() => onPickCandidate(candidate)}
                  className="flex w-full items-center justify-between gap-3 rounded-xl bg-light-bg px-3 py-2 text-left text-sm transition-colors hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-bg dark:hover:bg-dark-surface2"
                >
                  <span className="min-w-0 truncate font-medium text-light-text dark:text-dark-text">
                    {candidate.name}
                  </span>
                  <span className="shrink-0 text-xs text-light-textDim dark:text-dark-textDim">
                    {PROVIDER_LABEL[candidate.provider] ?? candidate.provider}
                    {candidate.score != null ? ` · ${candidate.score}` : ''}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            !rematch.isPending && (
              <p className="text-sm text-light-textDim dark:text-dark-textDim">
                No candidates yet — run a search or link an artist URL below.
              </p>
            )
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
