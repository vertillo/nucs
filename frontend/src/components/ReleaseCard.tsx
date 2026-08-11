import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { MatchedArtist, ReleaseListItem, ReleaseType } from '../api/releases'

const TYPE_LABEL: Record<ReleaseType, string> = {
  album: 'Album',
  single: 'Single',
  ep: 'EP',
  other: 'Other',
}

function NoteIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-8 w-8">
      <path strokeLinecap="round" d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  )
}

function CardCover({ coverKey, hasCover }: { coverKey: string; hasCover: boolean }) {
  const [broken, setBroken] = useState(false)
  if (!hasCover || broken) {
    return (
      <div className="flex aspect-square items-center justify-center rounded-xl bg-light-surface2 text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
        <NoteIcon />
      </div>
    )
  }
  // cover_key is the numeric release id for non-MusicBrainz releases (rgid is
  // NULL there): those covers live on the /covers/release/{id} route, since
  // /covers/{rgid} only accepts the strict MusicBrainz UUID shape.
  const coverSrc = /^[0-9]+$/.test(coverKey)
    ? `/api/v1/covers/release/${coverKey}`
    : `/api/v1/covers/${coverKey}`
  return (
    <img
      src={coverSrc}
      alt=""
      loading="lazy"
      onError={() => setBroken(true)}
      className="aspect-square w-full rounded-xl object-cover"
    />
  )
}

function EyeIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="1.8"
      className="h-3.5 w-3.5"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z" />
      <circle cx="12" cy="12" r="2.6" />
    </svg>
  )
}

/** primary_artist with the tracked (primary/featured) names highlighted in accent. */
function ArtistLine({ primaryArtist, tracked }: { primaryArtist: string; tracked: MatchedArtist[] }) {
  if (tracked.length === 0) return <>{primaryArtist}</>
  const parts: React.ReactNode[] = []
  let rest = primaryArtist
  for (const t of tracked) {
    const idx = rest.indexOf(t.name)
    if (idx >= 0) {
      if (idx > 0) parts.push(rest.slice(0, idx))
      parts.push(
        <span key={t.id} className="font-medium text-accentText dark:text-accent">
          {t.name}
        </span>,
      )
      rest = rest.slice(idx + t.name.length)
    }
  }
  parts.push(rest)
  return <>{parts}</>
}

export default function ReleaseCard({
  release,
  onToggleSeen,
}: {
  release: ReleaseListItem
  onToggleSeen?: (release: ReleaseListItem) => void
}) {
  const tracked = release.matched_artists.filter((a) => a.role === 'primary' || a.role === 'featured')
  const featured = release.matched_artists.filter((a) => a.role === 'featured')
  const featuredExtra = featured.filter((f) => !release.primary_artist.includes(f.name))
  const isNew = !release.seen

  return (
    <Link
      to={`/releases/${release.id}`}
      className="group relative flex flex-col gap-2 rounded-2xl bg-light-surface p-2 transition-transform hover:scale-[1.02] hover:shadow-lg hover:shadow-black/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-surface dark:hover:shadow-black/40"
    >
      {/* Spec 5.4 (spec:1159): without onToggleSeen (upcoming view) the card
          carries no seen semantics — neither the toggle nor the new-dot. */}
      {onToggleSeen && (
        <div className="absolute right-3.5 top-3.5 z-10 flex items-center gap-1.5">
          {isNew && (
            <span
              aria-label="New"
              className="h-2.5 w-2.5 rounded-full bg-accent shadow-sm shadow-black/30"
            />
          )}
          <button
            type="button"
            aria-label={release.seen ? 'Mark as unseen' : 'Mark as seen'}
            aria-pressed={!!release.seen}
            title={release.seen ? 'Mark as unseen' : 'Mark as seen'}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              onToggleSeen(release)
            }}
            className={`rounded-full p-1.5 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
              release.seen
                ? 'bg-accent text-black'
                : 'bg-black/40 text-white opacity-0 backdrop-blur-sm hover:opacity-100 group-hover:opacity-100'
            }`}
          >
            <EyeIcon filled={!!release.seen} />
          </button>
        </div>
      )}
      <CardCover coverKey={release.cover_key} hasCover={!!release.cover_path} />
      <div className="px-1 pb-1">
        <h3 className="line-clamp-2 text-sm font-semibold text-light-text dark:text-dark-text">
          {release.title}
        </h3>
        <p className="mt-0.5 truncate text-xs text-light-textDim dark:text-dark-textDim">
          <ArtistLine primaryArtist={release.primary_artist} tracked={tracked} />
          {featuredExtra.length > 0 && <span> (feat. {featuredExtra.map((f) => f.name).join(', ')})</span>}
        </p>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <span className="text-xs text-light-textDim dark:text-dark-textDim">
            {release.first_release_date}
          </span>
          <span className="rounded-full bg-light-surface2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
            {TYPE_LABEL[release.type]}
          </span>
        </div>
      </div>
    </Link>
  )
}
