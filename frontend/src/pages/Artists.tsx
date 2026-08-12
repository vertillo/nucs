import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  useAddArtist,
  useArtistLookup,
  useArtistSearch,
  useArtists,
  useDeleteArtist,
  useLinkArtist,
  useSetArtistIgnored,
  useUnlinkAllIdentities,
  useUnlinkIdentity,
  useUpsertIdentity,
  type AddArtistPayload,
  type ArtistCandidate,
  type ArtistIdentity,
  type ArtistItem,
  type ArtistStatus,
} from '../api/artists'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import Toast, { useToast } from '../components/Toast'

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
          {Array.from({ length: 4 }, (_, j) => (
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

/** Canonical provider page for a (provider, provider_id) pair. */
function providerPageUrl(provider: string, providerId: string | null): string | null {
  if (!providerId) return null
  switch (provider) {
    case 'mb':
      return `https://musicbrainz.org/artist/${providerId}`
    case 'deezer':
      return `https://www.deezer.com/artist/${providerId}`
    case 'itunes':
      return `https://music.apple.com/artist/${providerId}`
    case 'discogs':
      return `https://www.discogs.com/artist/${providerId}`
    case 'soundcloud':
      return `https://soundcloud.com/${providerId}`
    case 'beatport':
      return `https://www.beatport.com/artist/${providerId}`
    default:
      return null
  }
}

/** External page of one stored identity (identity table is authoritative, spec 1.3). */
function identityUrl(identity: ArtistIdentity): string | null {
  return identity.external_url ?? providerPageUrl(identity.provider, identity.provider_id)
}

const STATUS_BADGE: Record<ArtistStatus, string> = {
  Linked: 'bg-accent/15 text-accentText dark:bg-accent/20 dark:text-accent',
  'Needs match': 'bg-light-surface2 text-dangerText dark:bg-dark-surface2 dark:text-danger',
  Ignored: 'bg-light-surface2 text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim',
}

/** Primary artist state pill (spec 2.3); text label keeps it accessible. */
function StatusBadge({ status }: { status: ArtistStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[status]}`}>{status}</span>
  )
}

/** Artist name, linked to its first identity's provider page when it has
 * identities; plain text otherwise (spec 8.6 — no single-provider assumption). */
function ArtistName({ artist }: { artist: ArtistItem }) {
  const url = artist.identities.length > 0 ? identityUrl(artist.identities[0]) : null
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
  const [manageArtist, setManageArtist] = useState<ArtistItem | null>(null)
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
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Releases</th>
                <th className="px-4 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((artist) => (
                <tr key={artist.id} className="border-b border-light-border dark:border-dark-border">
                  <td className="px-4 py-3">
                    <ArtistName artist={artist} />
                    {artist.status === 'Needs match' && artist.source_files.length > 0 && (
                      <p className="mt-0.5 text-xs text-light-textDim dark:text-dark-textDim">
                        {artist.source_files.map(shortPath).join(' · ')}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={artist.status} />
                  </td>
                  <td className="px-4 py-3 text-light-textDim dark:text-dark-textDim">{artist.releases_count}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={!!artist.ignored}
                        aria-label={`Ignore ${artist.name}`}
                        onClick={() => setIgnore.mutate({ id: artist.id, ignored: !artist.ignored })}
                        className={`relative mr-1 h-5 w-9 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
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
                        aria-label={`Manage ${artist.name}`}
                        title="Manage identities"
                        onClick={() => setManageArtist(artist)}
                        className="rounded-full px-2 py-1 text-sm font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-dark-surface2"
                      >
                        Manage
                      </button>
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
                    </div>
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
                      <StatusBadge status={artist.status} />
                    </div>
                    <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
                      {artist.releases_count} release{artist.releases_count === 1 ? '' : 's'}
                    </p>
                    {artist.status === 'Needs match' && artist.source_files.length > 0 && (
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
                      onClick={() => setManageArtist(artist)}
                      className="rounded-full px-2 py-0.5 text-xs font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:hover:bg-dark-surface2"
                    >
                      Manage
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

      {manageArtist && (
        <ManageArtistModal
          artist={items.find((item) => item.id === manageArtist.id) ?? manageArtist}
          onClose={() => setManageArtist(null)}
          show={show}
        />
      )}

      <Toast toast={toast} />
    </div>
  )
}

/** One candidate row: the name picks, the provider-page link inspects (spec 2.4). */
function CandidateRow({
  candidate,
  onClick,
  disabled,
}: {
  candidate: ArtistCandidate
  onClick: () => void
  disabled: boolean
}) {
  const label = PROVIDER_LABEL[candidate.provider] ?? candidate.provider
  return (
    <div className="flex w-full items-center gap-2 rounded-xl bg-light-bg px-3 py-2 text-sm transition-colors hover:bg-light-surface2 dark:bg-dark-bg dark:hover:bg-dark-surface2">
      <button
        type="button"
        disabled={disabled}
        onClick={onClick}
        className="min-w-0 flex-1 truncate text-left font-medium text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:text-dark-text"
      >
        {candidate.name}
      </button>
      <span className="shrink-0 text-xs text-light-textDim dark:text-dark-textDim">
        {label}
        {candidate.score != null ? ` · ${candidate.score}` : ''}
      </span>
      {candidate.url && (
        <a
          href={candidate.url}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${candidate.name} on ${label}`}
          className="shrink-0 whitespace-nowrap text-xs font-medium text-accentText underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-accent"
        >
          Open on {label} ↗
        </a>
      )}
    </div>
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

/** Identity management view (spec 2.3): identities, replace, unlink, candidates. */
function ManageArtistModal({
  artist,
  onClose,
  show,
}: {
  artist: ArtistItem
  onClose: () => void
  show: (message: string, kind?: 'success' | 'error') => void
}) {
  const [url, setUrl] = useState('')
  const [linkError, setLinkError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<ArtistCandidate | null>(null)
  const [replaceProvider, setReplaceProvider] = useState<string | null>(null)
  const upsertIdentity = useUpsertIdentity()
  const unlinkIdentity = useUnlinkIdentity()
  const unlinkAll = useUnlinkAllIdentities()
  const link = useLinkArtist()
  const searchInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 400)
    return () => clearTimeout(timer)
  }, [searchQuery])

  useEffect(() => {
    searchInput.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const freeSearch = useArtistSearch(debouncedQuery)
  const freeCandidates = freeSearch.data?.items ?? []
  const busy = upsertIdentity.isPending || unlinkIdentity.isPending || unlinkAll.isPending || link.isPending

  function handleReplace(provider: string) {
    setSelected(null)
    setReplaceProvider(provider)
    setSearchQuery(artist.name)
    searchInput.current?.focus()
  }

  function handleUnlink(identity: ArtistIdentity) {
    const label = PROVIDER_LABEL[identity.provider] ?? identity.provider
    if (!window.confirm(`Unlink the ${label} identity of "${artist.name}"?`)) return
    unlinkIdentity.mutate(
      { id: artist.id, provider: identity.provider },
      {
        onSuccess: () => show(`${label} identity unlinked`),
        onError: (error) => show(error.message, 'error'),
      },
    )
  }

  function handleUnlinkAll() {
    if (!window.confirm(`Unlink all identities of "${artist.name}"? It returns to Needs match.`)) return
    unlinkAll.mutate(artist.id, {
      onSuccess: () => show('All identities unlinked'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  function handlePickCandidate(candidate: ArtistCandidate) {
    if (!candidate.provider_id) {
      show('This candidate has no provider id — link it by URL instead.', 'error')
      return
    }
    upsertIdentity.mutate(
      {
        id: artist.id,
        provider: candidate.provider,
        provider_id: candidate.provider_id,
        external_url: candidate.url,
      },
      {
        onSuccess: () => {
          show(`Linked ${PROVIDER_LABEL[candidate.provider] ?? candidate.provider}`)
          setSelected(null)
          setReplaceProvider(null)
        },
        onError: (error) => show(error.message, 'error'),
      },
    )
  }

  function handleLink() {
    setLinkError(null)
    link.mutate(
      { id: artist.id, url },
      {
        onSuccess: () => {
          show('Artist linked')
          setUrl('')
        },
        onError: (error) => setLinkError(error.message),
      },
    )
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Manage ${artist.name}`}
      onClick={onClose}
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-light-surface p-6 shadow-xl shadow-black/40 dark:bg-dark-surface"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">Manage artist</h2>
            <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
              {artist.name} — link, replace or unlink its external identities; no delete + re-add needed.
            </p>
          </div>
          <StatusBadge status={artist.status} />
        </div>

        <div className="mt-4 space-y-4">
          <section>
            <h3 className="text-sm font-medium text-light-textDim dark:text-dark-textDim">Current identities</h3>
            {artist.identities.length === 0 ? (
              <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
                No external identities yet — pick a candidate below or link by URL.
              </p>
            ) : (
              <ul className="mt-2 space-y-1">
                {artist.identities.map((identity) => {
                  const label = PROVIDER_LABEL[identity.provider] ?? identity.provider
                  const pageUrl = identityUrl(identity)
                  return (
                    <li
                      key={identity.provider}
                      className="flex items-center justify-between gap-2 rounded-xl bg-light-bg px-3 py-2 dark:bg-dark-bg"
                    >
                      <div className="min-w-0 text-sm">
                        <span className="font-medium text-light-text dark:text-dark-text">{label}</span>
                        {identity.match_score != null && (
                          <span className="text-xs text-light-textDim dark:text-dark-textDim">
                            {' '}
                            · score {identity.match_score}
                          </span>
                        )}
                        {identity.link_method && (
                          <span className="text-xs text-light-textDim dark:text-dark-textDim">
                            {' '}
                            · {identity.link_method}
                          </span>
                        )}
                        {pageUrl && (
                          <a
                            href={pageUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="ml-2 whitespace-nowrap text-xs font-medium text-accentText underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-accent"
                          >
                            Open on {label} ↗
                          </a>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleReplace(identity.provider)}
                          className="rounded-full px-2 py-1 text-xs font-medium text-accentText transition-colors dark:text-accent hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:hover:bg-dark-surface2"
                        >
                          Replace
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => handleUnlink(identity)}
                          className="rounded-full px-2 py-1 text-xs font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
                        >
                          Unlink
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
            {artist.identities.length > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={handleUnlinkAll}
                className="mt-2 rounded-full px-3 py-1 text-xs font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
              >
                Unlink all
              </button>
            )}
          </section>

          {selected ? (
            <CandidateDetailsPanel
              candidate={selected}
              onBack={() => setSelected(null)}
              onPick={() => handlePickCandidate(selected)}
              pickLabel="Link artist"
              picking={upsertIdentity.isPending}
            />
          ) : (
            <>
              <section>
                <label
                  htmlFor="manage-artist-search"
                  className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
                >
                  {replaceProvider
                    ? `Replace ${PROVIDER_LABEL[replaceProvider] ?? replaceProvider} — pick a candidate (any name)`
                    : 'Search candidates (any name)'}
                </label>
                <input
                  ref={searchInput}
                  id="manage-artist-search"
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
                        disabled={busy}
                        onClick={() => setSelected(candidate)}
                      />
                    ))}
                  </div>
                )}
                {debouncedQuery.trim().length >= 2 && !freeSearch.isPending && freeCandidates.length === 0 && (
                  <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">No matches found.</p>
                )}
              </section>

              <section>
                <label
                  htmlFor="link-artist-url"
                  className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
                >
                  Track by URL (MusicBrainz, Deezer, Apple Music, Discogs, SoundCloud, Beatport)
                </label>
                <input
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
              </section>
            </>
          )}
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
