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

/** Tracked artist name highlighted in accent, with accessible "Tracked artist" text (spec 8.4 / spec:1595). */
function TrackedName({ artist }: { artist: MatchedArtist }) {
  return (
    <span
      title="Tracked artist"
      aria-label="Tracked artist"
      className="font-medium text-accentText dark:text-accent"
    >
      {artist.name}
    </span>
  )
}

/**
 * Credits line rendered ONLY from the authoritative ReleaseArtist payload
 * (`release.matched_artists`, task 18 / spec 8.4 / spec:1584-1597): every
 * name is the exact Artist row joined by discovery, and the role decides the
 * presentation (primary inline, featured in a feat. clause, remixer in a
 * remix clause). No case-sensitive `.indexOf()`/substring splice against the
 * provider credit phrase — a PiKi-style homonym that merely appears in the
 * phrase is never highlighted without the release<->artist relation
 * (spec:1597). The raw credit phrase renders only when no tracked artist is
 * linked to the release (nothing to highlight).
 */
function CreditsLine({ release }: { release: ReleaseListItem }) {
  const { matched_artists: artists, primary_artist } = release
  if (artists.length === 0) return <>{primary_artist}</>
  const primary = artists.filter((a) => a.role === 'primary')
  const featured = artists.filter((a) => a.role === 'featured')
  const remixers = artists.filter((a) => a.role === 'remixer')
  const joinNames = (list: MatchedArtist[]) => (
    <>
      {list.map((artist, i) => (
        <span key={artist.id}>
          {i > 0 && ', '}
          <TrackedName artist={artist} />
        </span>
      ))}
    </>
  )
  return (
    <>
      {joinNames(primary)}
      {featured.length > 0 && <span> (feat. {joinNames(featured)})</span>}
      {remixers.length > 0 && <span> (remix by {joinNames(remixers)})</span>}
    </>
  )
}

export default function ReleaseCard({
  release,
  onToggleSeen,
}: {
  release: ReleaseListItem
  onToggleSeen?: (release: ReleaseListItem) => void
}) {
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
          <CreditsLine release={release} />
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
