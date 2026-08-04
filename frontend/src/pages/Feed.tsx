import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { useReleases, useSeenAll, type ReleaseFilters, type ReleaseType } from '../api/releases'
import ReleaseCard from '../components/ReleaseCard'

const TYPE_CHIPS: { value: ReleaseType | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'album', label: 'Albums' },
  { value: 'single', label: 'Singles' },
  { value: 'ep', label: 'EPs' },
]

function SkeletonCard() {
  return (
    <div className="flex flex-col gap-2 rounded-2xl bg-light-surface p-2 dark:bg-dark-surface">
      <div className="aspect-square animate-pulse rounded-xl bg-light-surface2 dark:bg-dark-surface2" />
      <div className="h-3.5 w-3/4 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center gap-3 py-16 text-center">
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="h-12 w-12 text-light-textDim dark:text-dark-textDim"
      >
        <path strokeLinecap="round" d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" />
        <circle cx="18" cy="16" r="3" />
      </svg>
      <p className="text-lg font-semibold text-light-text dark:text-dark-text">No new releases</p>
      <p className="text-sm text-light-textDim dark:text-dark-textDim">
        Try running a scan from{' '}
        <Link
          to="/settings"
          className="text-accent underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Settings
        </Link>
      </p>
    </div>
  )
}

export default function Feed() {
  const [type, setType] = useState<ReleaseType | 'all'>('all')
  const [unseenOnly, setUnseenOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  const filters: ReleaseFilters = { type, unseenOnly, q: debouncedSearch.trim() }
  const { data, isPending, isError, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } =
    useReleases(filters)
  const seenAll = useSeenAll()

  const items = data?.pages.flatMap((page) => page.items) ?? []
  const total = data?.pages[0]?.total ?? 0

  function handleMarkAllSeen() {
    if (window.confirm('Mark all releases as seen?')) {
      seenAll.mutate()
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">New releases</h1>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {TYPE_CHIPS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={type === value}
              onClick={() => setType(value)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                type === value
                  ? 'bg-accent text-black'
                  : 'bg-light-surface2 text-light-textDim hover:text-light-text dark:bg-dark-surface2 dark:text-dark-textDim dark:hover:text-dark-text'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-2">
          <span className="text-sm text-light-textDim dark:text-dark-textDim">Unseen only</span>
          <button
            type="button"
            role="switch"
            aria-checked={unseenOnly}
            aria-label="Unseen only"
            onClick={() => setUnseenOnly((v) => !v)}
            className={`relative h-5 w-9 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              unseenOnly ? 'bg-accent' : 'bg-light-border dark:bg-dark-border'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-light-bg transition-all dark:bg-dark-bg ${
                unseenOnly ? 'left-[18px]' : 'left-0.5'
              }`}
            />
          </button>
        </label>

        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search…"
          aria-label="Search"
          className="min-w-0 flex-1 rounded-full border border-light-border bg-light-surface px-4 py-1.5 text-sm text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-surface dark:text-dark-text sm:max-w-[220px]"
        />

        <button
          type="button"
          onClick={handleMarkAllSeen}
          disabled={seenAll.isPending}
          className="rounded-full px-3 py-1.5 text-sm text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:text-dark-textDim dark:hover:text-dark-text"
        >
          Mark all as seen
        </button>
      </div>

      {isPending && (
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {Array.from({ length: 12 }, (_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      )}

      {isError && (
        <div className="mt-16 flex flex-col items-center gap-3 text-center">
          <p className="text-light-textDim dark:text-dark-textDim">Something went wrong loading releases.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retry
          </button>
        </div>
      )}

      {!isPending && !isError && items.length === 0 && <EmptyState />}

      {!isPending && !isError && items.length > 0 && (
        <>
          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {items.map((release) => (
              <ReleaseCard key={release.id} release={release} />
            ))}
          </div>
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
              <span>{items.length} of {total}</span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
