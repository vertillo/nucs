import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

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

const SOURCE_LABEL: Record<string, string> = {
  mb: 'MusicBrainz',
  deezer: 'Deezer',
  itunes: 'Apple Music',
  discogs: 'Discogs',
  soundcloud: 'SoundCloud',
  beatport: 'Beatport',
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

function formatDuration(seconds: number | null): string {
  if (seconds == null) return ''
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === '' || value === false) return null
  return (
    <div className="flex justify-between gap-6 py-1.5">
      <dt className="text-sm text-light-textDim dark:text-dark-textDim">{label}</dt>
      <dd className="text-right text-sm font-medium text-light-text dark:text-dark-text">{value}</dd>
    </div>
  )
}

export default function ReleaseDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { data: release, isPending, isError, error, refetch } = useRelease(id)
  const setState = useSetReleaseState(release?.id)

  const [coverBroken, setCoverBroken] = useState(false)
  useEffect(() => {
    setCoverBroken(false)
  }, [id])

  // "Back to feed" behaves like the browser back button (scroll position is
  // preserved by the feed cache); "/" is the fallback when there is no history.
  function backToFeed() {
    if (window.history.length > 1) {
      navigate(-1)
    } else {
      navigate('/')
    }
  }

  if (isPending) {
    return (
      <div>
        <button
          type="button"
          onClick={backToFeed}
          className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
        >
          ← Back to feed
        </button>
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
          <button
            type="button"
            onClick={backToFeed}
            className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
          >
            ← Back to feed
          </button>
          <div className="mt-16 flex flex-col items-center gap-3 text-center">
            <p className="text-lg font-semibold text-light-text dark:text-dark-text">Release not found</p>
            <button
              type="button"
              onClick={backToFeed}
              className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Back to feed
            </button>
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
      <button
        type="button"
        onClick={backToFeed}
        className="inline-flex items-center gap-1 rounded text-sm text-light-textDim transition-colors hover:text-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim"
      >
        ← Back to feed
      </button>

      <div className="mt-6 grid gap-8 md:grid-cols-[384px,1fr]">
        {showPlaceholder ? (
          <div className="flex aspect-square w-full max-w-[384px] items-center justify-center rounded-xl bg-light-surface2 text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
            <NoteIcon />
          </div>
        ) : (
          <img
            src={
              /^[0-9]+$/.test(release.cover_key)
                ? `/api/v1/covers/release/${release.cover_key}`
                : `/api/v1/covers/${release.cover_key}`
            }
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
          <p className="mt-1 text-light-textDim dark:text-dark-textDim">{release.primary_artist}</p>

          <dl className="mt-4 max-w-md">
            <InfoRow label="Release date" value={release.first_release_date} />
            <InfoRow label="Type" value={TYPE_LABEL[release.type]} />
            {secondary.length > 0 && <InfoRow label="Secondary types" value={secondary.join(', ')} />}
            <InfoRow label="Source" value={SOURCE_LABEL[release.source] ?? release.source} />
            <InfoRow
              label="Discovered"
              value={release.discovered_at ? new Date(release.discovered_at).toLocaleString() : null}
            />
          </dl>

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

          {release.tracks.length > 0 && (
            <section className="mt-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-light-textDim dark:text-dark-textDim">
                Tracklist
              </h2>
              <ol className="mt-2 max-w-md divide-y divide-light-border dark:divide-dark-border">
                {release.tracks.map((track) => (
                  <li key={track.position} className="flex items-baseline gap-3 py-1.5 text-sm">
                    <span className="w-6 shrink-0 text-right tabular-nums text-light-textDim dark:text-dark-textDim">
                      {track.position}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-light-text dark:text-dark-text">{track.title}</span>
                    {track.duration_s != null && (
                      <span className="shrink-0 tabular-nums text-light-textDim dark:text-dark-textDim">
                        {formatDuration(track.duration_s)}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}

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
