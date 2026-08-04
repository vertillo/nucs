import type { ReactNode } from 'react'

import type { ReleaseDetail } from '../api/releases'

function PlayIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86a1 1 0 0 0-1.5.86z" />
    </svg>
  )
}

function YoutubeIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M21.6 7.2a2.5 2.5 0 0 0-1.76-1.77C18.25 5 12 5 12 5s-6.25 0-7.84.43A2.5 2.5 0 0 0 2.4 7.2 26.2 26.2 0 0 0 2 12c0 1.62.13 3.22.4 4.8a2.5 2.5 0 0 0 1.76 1.77C5.75 19 12 19 12 19s6.25 0 7.84-.43a2.5 2.5 0 0 0 1.76-1.77c.27-1.58.4-3.18.4-4.8s-.13-3.22-.4-4.8zM10 15V9l5.2 3L10 15z" />
    </svg>
  )
}

function DeezerIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <rect x="3" y="5" width="4" height="2" />
      <rect x="9.5" y="5" width="4" height="2" />
      <rect x="16" y="5" width="5" height="2" />
      <rect x="3" y="11" width="4" height="2" />
      <rect x="9.5" y="11" width="4" height="2" />
      <rect x="16" y="11" width="5" height="2" />
      <rect x="3" y="17" width="4" height="2" />
      <rect x="9.5" y="17" width="4" height="2" />
    </svg>
  )
}

function SearchIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
      <circle cx="11" cy="11" r="7" />
      <path strokeLinecap="round" d="m20 20-3.5-3.5" />
    </svg>
  )
}

interface LinkSpec {
  key: 'spotify' | 'ytm' | 'deezer' | 'google'
  label: string
  icon: ReactNode
  className: string
}

const LINKS: LinkSpec[] = [
  {
    key: 'spotify',
    label: 'Spotify',
    icon: <PlayIcon />,
    className: 'bg-accent text-black',
  },
  {
    key: 'ytm',
    label: 'YouTube Music',
    icon: <YoutubeIcon />,
    className: 'bg-yt text-light-bg',
  },
  {
    key: 'deezer',
    label: 'Deezer',
    icon: <DeezerIcon />,
    className: 'bg-deezer text-light-bg',
  },
  {
    key: 'google',
    label: 'Search on Google',
    icon: <SearchIcon />,
    className:
      'border border-light-border bg-light-surface2 text-light-text dark:border-dark-border dark:bg-dark-surface2 dark:text-dark-text',
  },
]

export default function LinkButtons({ release }: { release: ReleaseDetail }) {
  const urls: Record<(typeof LINKS)[number]['key'], string | null> = {
    spotify: release.spotify_url,
    ytm: release.ytm_url,
    deezer: release.deezer_url,
    google: release.google_url,
  }

  return (
    <div className="flex flex-wrap gap-2">
      {LINKS.map(({ key, label, icon, className }) => {
        const url = urls[key]
        const base =
          'inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-accent'
        if (!url) {
          return (
            <span
              key={key}
              aria-disabled="true"
              className={`${base} cursor-not-allowed opacity-50 ${className}`}
            >
              {icon}
              {label}
            </span>
          )
        }
        return (
          <a
            key={key}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className={`${base} transition-opacity hover:opacity-90 ${className}`}
          >
            {icon}
            {label}
          </a>
        )
      })}
    </div>
  )
}
