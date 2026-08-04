import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import {
  useRelease,
  useSetReleaseState,
  type ArtistRole,
  type ReleaseType,
} from '../api/releases'
import LinkButtons from '../components/LinkButtons'

const TYPE_LABEL: Record<ReleaseType, string> = {
  album: 'Album',
  single: 'Single',
  ep: 'EP',
  other: 'Other',
}

const ROLE_LABEL: Record<ArtistRole, string> = {
  primary: 'Main artist',
  featured: 'Featuring',
  contributor: 'Contributor',
}

function NoteIcon({ className = 'h-24 w-24' }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={className}>
      <path strokeLinecap="round" d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  )
}

function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="2"
      className="h-4 w-4"
    >
      <path
        strokeLinejoin="round"
        d="M12 21C6.5 16.5 2 12.9 2 8.7 2 5.6 4.4 3.5 7.1 3.5c1.9 0 3.6 1 4.9 2.8 1.3-1.8 3-2.8 4.9-2.8 2.7 0 5.1 2.1 5.1 5.2 0 4.2-4.5 7.8-10 12.3z"
      />
    </svg>
  )
}

function DetailSkeleton() {
  return (
    <div className="grid gap-8 md:grid-cols-[384px,1fr]">
      <div className="aspect-square max-w-[384px] animate-pulse rounded-xl bg-light-surface2 dark:bg-dark-surface2" />
      <div className="space-y-3">
        <div className="h-8 w-2/3 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
        <div className="h-4 w-1/3 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-light-surface2 dark:bg-dark-surface2" />
        <div className="h-10 w-2/3 animate-pulse rounded-full bg-light-surface2 dark:bg-dark-surface2" />
      </div>
    </div>
  )
}

export default function ReleaseDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: release, isPending, isError, error, refetch } = useRelease(id)
  const setState = useSetReleaseState(release?.id)

  const [coverBroken, setCoverBroken] = useState(false)
  useEffect(() => {
    setCoverBroken(false)
  }, [id])

  if (isPending) {
    return (
      <div>
        <Link
          to="/"
          className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
        >
          ← Back to feed
        </Link>
        <div className="mt-6">
          <DetailSkeleton />
        </div>
      </div>
    )
  }

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <div>
          <Link
            to="/"
            className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
          >
            ← Back to feed
          </Link>
          <div className="mt-16 flex flex-col items-center gap-3 text-center">
            <p className="text-lg font-semibold text-light-text dark:text-dark-text">Release not found</p>
            <Link
              to="/"
              className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Back to feed
            </Link>
          </div>
        </div>
      )
    }
    return (
      <div className="mt-16 flex flex-col items-center gap-3 text-center">
        <p className="text-light-textDim dark:text-dark-textDim">Something went wrong loading this release.</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Retry
        </button>
      </div>
    )
  }

  const showPlaceholder = !release.cover_path || coverBroken
  const secondary = release.secondary_types
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  return (
    <div>
      <Link
        to="/"
        className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
      >
        ← Back to feed
      </Link>

      <div className="mt-6 grid gap-8 md:grid-cols-[384px,1fr]">
        {showPlaceholder ? (
          <div className="flex aspect-square w-full max-w-[384px] items-center justify-center rounded-xl bg-light-surface2 text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
            <NoteIcon />
          </div>
        ) : (
          <img
            src={`/api/v1/covers/${release.rgid}`}
            alt={`Cover of ${release.title}`}
            onError={() => setCoverBroken(true)}
            className="aspect-square w-full max-w-[384px] rounded-xl object-cover"
          />
        )}

        <div>
          <div className="flex flex-wrap items-center gap-2">
            {release.hidden ? (
              <span className="rounded-full bg-danger px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-light-bg">
                Hidden
              </span>
            ) : null}
            <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
              {TYPE_LABEL[release.type]}
            </span>
            {secondary.map((s) => (
              <span
                key={s}
                className="rounded-full bg-light-surface2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim"
              >
                {s}
              </span>
            ))}
          </div>

          <h1 className="mt-3 text-3xl font-bold text-light-text dark:text-dark-text">{release.title}</h1>
          <p className="mt-1 text-light-textDim dark:text-dark-textDim">{release.first_release_date}</p>

          <section className="mt-5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-light-textDim dark:text-dark-textDim">
              Your artists
            </h2>
            {release.matched_artists.length > 0 ? (
              <ul className="mt-2 space-y-1">
                {release.matched_artists.map((artist) => (
                  <li key={artist.id} className="text-sm">
                    <span className="font-medium text-accent">{artist.name}</span>
                    <span className="text-light-textDim dark:text-dark-textDim"> — {ROLE_LABEL[artist.role]}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-light-textDim dark:text-dark-textDim">—</p>
            )}
          </section>

          <div className="mt-6">
            <LinkButtons release={release} />
          </div>

          <div className="mt-6 flex flex-wrap gap-2">
            <button
              type="button"
              aria-pressed={!!release.seen}
              onClick={() => setState.mutate({ seen: !release.seen })}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                release.seen
                  ? 'bg-accent text-black'
                  : 'border border-light-border text-light-textDim hover:text-light-text dark:border-dark-border dark:text-dark-textDim dark:hover:text-dark-text'
              }`}
            >
              Seen
            </button>
            <button
              type="button"
              aria-pressed={!!release.favorite}
              onClick={() => setState.mutate({ favorite: !release.favorite })}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                release.favorite
                  ? 'bg-accent text-black'
                  : 'border border-light-border text-light-textDim hover:text-light-text dark:border-dark-border dark:text-dark-textDim dark:hover:text-dark-text'
              }`}
            >
              <HeartIcon filled={!!release.favorite} />
              Favorite
            </button>
            <button
              type="button"
              onClick={() => setState.mutate({ hidden: !release.hidden })}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                release.hidden
                  ? 'bg-accent text-black'
                  : 'border border-light-border text-light-textDim hover:text-light-text dark:border-dark-border dark:text-dark-textDim dark:hover:text-dark-text'
              }`}
            >
              {release.hidden ? 'Restore' : 'Hide'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
