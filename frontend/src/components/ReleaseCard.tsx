import { useState, type ReactNode } from 'react'
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

function CardCover({ rgid, hasCover }: { rgid: string; hasCover: boolean }) {
  const [broken, setBroken] = useState(false)
  if (!hasCover || broken) {
    return (
      <div className="flex aspect-square items-center justify-center rounded-xl bg-light-surface2 text-light-textDim dark:bg-dark-surface2 dark:text-dark-textDim">
        <NoteIcon />
      </div>
    )
  }
  return (
    <img
      src={`/api/v1/covers/${rgid}`}
      alt=""
      loading="lazy"
      onError={() => setBroken(true)}
      className="aspect-square w-full rounded-xl object-cover"
    />
  )
}

/** primary_artist with the tracked (primary/featured) names highlighted in accent. */
function ArtistLine({ primaryArtist, tracked }: { primaryArtist: string; tracked: MatchedArtist[] }) {
  if (tracked.length === 0) return <>{primaryArtist}</>
  const parts: ReactNode[] = []
  let rest = primaryArtist
  for (const t of tracked) {
    const idx = rest.indexOf(t.name)
    if (idx >= 0) {
      if (idx > 0) parts.push(rest.slice(0, idx))
      parts.push(
        <span key={t.id} className="font-medium text-accent">
          {t.name}
        </span>,
      )
      rest = rest.slice(idx + t.name.length)
    }
  }
  parts.push(rest)
  return <>{parts}</>
}

export default function ReleaseCard({ release }: { release: ReleaseListItem }) {
  const tracked = release.matched_artists.filter((a) => a.role === 'primary' || a.role === 'featured')
  const featured = release.matched_artists.filter((a) => a.role === 'featured')
  const featuredExtra = featured.filter((f) => !release.primary_artist.includes(f.name))
  const isNew = !release.seen

  return (
    <Link
      to={`/releases/${release.id}`}
      className="group relative flex flex-col gap-2 rounded-2xl bg-light-surface p-2 transition-transform hover:scale-[1.02] hover:shadow-lg hover:shadow-black/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-surface dark:hover:shadow-black/40"
    >
      {isNew && (
        <span
          aria-label="New"
          className="absolute right-3.5 top-3.5 z-10 h-2.5 w-2.5 rounded-full bg-accent shadow-sm shadow-black/30"
        />
      )}
      <CardCover rgid={release.rgid} hasCover={!!release.cover_path} />
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
