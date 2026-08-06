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

function AppleIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M16.7 12.9c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.4-.1-2.8.8-3.5.8s-1.9-.8-3.1-.8c-1.6 0-3.1.9-3.9 2.4-1.7 2.9-.4 7.2 1.2 9.6.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.1-.8s1.9.8 3.1.8c1.3 0 2.1-1.2 2.9-2.4.9-1.3 1.3-2.6 1.3-2.7 0 0-2.5-1-2.5-3.4zM14.3 5.7c.7-.8 1.1-1.9 1-3-1 .1-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.5z" />
    </svg>
  )
}

function TidalIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12 3 3.5 11.5 12 20l3.2-3.2-4.8-4.8 4.8-4.8L12 3zm6.5 3.2L17.3 7.4l1.2 1.2 3.2-3.2-3.2-3.2-1.2 1.2 1.2 1.2z" />
    </svg>
  )
}

function QobuzIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <path d="M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9zm0 2.4a6.6 6.6 0 1 1-6.6 6.6A6.6 6.6 0 0 1 12 5.4zm0 2.8a3.8 3.8 0 1 0 3.8 3.8A3.8 3.8 0 0 0 12 8.2z" />
    </svg>
  )
}

function DiscogsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="12" r="2.4" />
      <circle cx="12" cy="12" r="0.8" fill="none" stroke="currentColor" strokeWidth="1.4" />
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
  key:
    | 'spotify'
    | 'ytm'
    | 'deezer'
    | 'apple_music'
    | 'tidal'
    | 'qobuz'
    | 'discogs'
    | 'beatport'
    | 'google'
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
    key: 'apple_music',
    label: 'Apple Music',
    icon: <AppleIcon />,
    className: 'bg-[#fa243c] text-white',
  },
  {
    key: 'tidal',
    label: 'Tidal',
    icon: <TidalIcon />,
    className: 'bg-black text-white dark:bg-white dark:text-black',
  },
  {
    key: 'qobuz',
    label: 'Qobuz',
    icon: <QobuzIcon />,
    className: 'bg-[#0a4f9e] text-white',
  },
  {
    key: 'discogs',
    label: 'Discogs',
    icon: <DiscogsIcon />,
    className: 'bg-[#333] text-white',
  },
  {
    key: 'beatport',
    label: 'Beatport',
    icon: <SearchIcon />,
    className: 'bg-[#00ff95] text-black',
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
    apple_music: release.apple_music_url,
    tidal: release.tidal_url,
    qobuz: release.qobuz_url,
    discogs: release.discogs_url,
    beatport: release.beatport_url,
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
