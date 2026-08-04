import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import {
  useAddArtist,
  useArtists,
  useRematchArtist,
  useSetArtistIgnored,
  type ArtistSource,
} from '../api/artists'
import Toast, { useToast } from '../components/Toast'

const SOURCE_LABEL: Record<ArtistSource, string> = {
  tag_artist: 'Artist',
  tag_albumartist: 'Album artist',
  tag_feat: 'Featuring',
  tag_contrib: 'Contributor',
  manual: 'Manual',
}

const IGNORED_OPTIONS: { value: 'all' | 'yes' | 'no'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'no', label: 'Active' },
  { value: 'yes', label: 'Ignored' },
]

const inputClass =
  'w-full rounded-xl border border-light-border bg-light-bg px-3 py-2 text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-bg dark:text-dark-text'

function SkeletonRows() {
  return (
    <>
      {Array.from({ length: 6 }, (_, i) => (
        <tr key={i} className="border-b border-light-border dark:border-dark-border">
          {Array.from({ length: 5 }, (_, j) => (
            <td key={j} className="px-4 py-3">
              <div className="h-4 w-2/3 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

export default function Artists() {
  const [ignored, setIgnored] = useState<'all' | 'yes' | 'no'>('all')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [addError, setAddError] = useState<string | null>(null)
  const [rematchMessage, setRematchMessage] = useState<{ id: number; text: string; ok: boolean } | null>(null)
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
    q: debouncedSearch.trim(),
  })
  const setIgnore = useSetArtistIgnored()
  const rematch = useRematchArtist()
  const addArtist = useAddArtist()

  const items = data?.pages.flatMap((page) => page.items) ?? []
  const total = data?.pages[0]?.total ?? 0

  function openModal() {
    setNewName('')
    setAddError(null)
    setModalOpen(true)
  }

  function handleAdd(event: React.FormEvent) {
    event.preventDefault()
    const name = newName.trim()
    if (!name) {
      setAddError('Enter an artist name.')
      return
    }
    setAddError(null)
    addArtist.mutate(name, {
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
    })
  }

  function handleRematch(id: number) {
    rematch.mutate(id, {
      onSuccess: (result) => {
        setRematchMessage({
          id,
          text: result.matched ? 'Matched' : 'No match found',
          ok: result.matched,
        })
        show(result.matched ? 'Matched on MusicBrainz' : 'No match found', result.matched ? 'success' : 'error')
      },
      onError: (error) => {
        setRematchMessage({ id, text: error.message, ok: false })
        show(error.message, 'error')
      },
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
              </tr>
            </thead>
            <tbody>
              {items.map((artist) => (
                <tr key={artist.id} className="border-b border-light-border dark:border-dark-border">
                  <td className="px-4 py-3 font-medium text-light-text dark:text-dark-text">{artist.name}</td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-xs font-medium text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
                      {SOURCE_LABEL[artist.source]}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {artist.mbid ? (
                      <span className="inline-flex items-center gap-1.5">
                        <span aria-hidden="true">✅</span>
                        <span className="font-semibold text-accent">{artist.mb_match_score ?? ''}</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-2">
                        <span aria-hidden="true">⚠️</span>
                        <span className="text-light-textDim dark:text-dark-textDim">Unmatched</span>
                        <button
                          type="button"
                          disabled={rematch.isPending}
                          onClick={() => handleRematch(artist.id)}
                          className="rounded-full px-3 py-1 text-sm font-medium text-accent transition-colors hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:hover:bg-dark-surface2"
                        >
                          {rematch.isPending ? 'Retrying…' : 'Retry'}
                        </button>
                        {rematchMessage?.id === artist.id && (
                          <span
                            role="status"
                            className={`text-sm ${rematchMessage.ok ? 'text-accent' : 'text-danger'}`}
                          >
                            {rematchMessage.text}
                          </span>
                        )}
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
                          <span className="font-semibold text-accent">{artist.mb_match_score ?? ''}</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5">
                          <span aria-hidden="true">⚠️</span>
                          <span className="text-light-textDim dark:text-dark-textDim">Unmatched</span>
                          <button
                            type="button"
                            disabled={rematch.isPending}
                            onClick={() => handleRematch(artist.id)}
                            className="rounded-full px-2.5 py-0.5 text-sm font-medium text-accent transition-colors hover:bg-light-surface2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:hover:bg-dark-surface2"
                          >
                            {rematch.isPending ? 'Retrying…' : 'Retry'}
                          </button>
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
                      {artist.releases_count} release{artist.releases_count === 1 ? '' : 's'}
                    </p>
                    {rematchMessage?.id === artist.id && (
                      <p role="status" className={`mt-1 text-sm ${rematchMessage.ok ? 'text-accent' : 'text-danger'}`}>
                        {rematchMessage.text}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={!!artist.ignored}
                    aria-label={`Ignore ${artist.name}`}
                    onClick={() => setIgnore.mutate({ id: artist.id, ignored: !artist.ignored })}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                      artist.ignored ? 'bg-accent' : 'bg-light-border dark:bg-dark-border'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-light-bg transition-all dark:bg-dark-bg ${
                        artist.ignored ? 'left-[18px]' : 'left-0.5'
                      }`}
                    />
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-8 text-center text-sm text-light-textDim dark:text-dark-textDim">
            {hasNextPage ? (
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="rounded-full bg-light-surface2 px-5 py-2 font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
              >
                {isFetchingNextPage ? 'Loading…' : 'Load more'}
              </button>
            ) : (
              <span>
                {items.length} of {total}
              </span>
            )}
          </div>
        </>
      )}

      {modalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Add artist"
          onClick={() => setModalOpen(false)}
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-2xl bg-light-surface p-6 shadow-xl shadow-black/40 dark:bg-dark-surface"
          >
            <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">Add artist</h2>
            <form onSubmit={handleAdd} className="mt-4 space-y-4">
              <div>
                <label
                  htmlFor="add-artist-name"
                  className="mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim"
                >
                  Name
                </label>
                <input
                  ref={nameInput}
                  id="add-artist-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className={inputClass}
                />
                {addError && (
                  <p role="alert" className="mt-1 text-sm text-danger">
                    {addError}
                  </p>
                )}
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
                  type="submit"
                  disabled={addArtist.isPending}
                  className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
                >
                  {addArtist.isPending ? 'Adding…' : 'Add'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <Toast toast={toast} />
    </div>
  )
}
