import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { NavLink, useNavigate } from 'react-router-dom'

import { post, put } from '../api/client'
import { useErrors } from '../api/errors'
import { applyTheme, getStoredTheme, type Theme } from '../theme'

interface NavbarProps {
  username: string
  theme: Theme
}

function SunIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
      <circle cx="12" cy="12" r="4" />
      <path
        strokeLinecap="round"
        d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41m11.32-11.32 1.41-1.41"
      />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

function HomeIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 sm:hidden">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 12l9-9 9 9M5 10v10a1 1 0 0 0 1 1h3v-6h6v6h3a1 1 0 0 0 1-1V10"
      />
    </svg>
  )
}

function ArtistsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 sm:hidden">
      <circle cx="9" cy="8" r="3.5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.5 20c.8-3.2 3.3-5 6.5-5s5.7 1.8 6.5 5M16 5.2a3.5 3.5 0 0 1 0 5.6M18.5 14.5c1.6.8 2.8 2 3.5 3.5" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 sm:hidden">
      <circle cx="12" cy="12" r="3" />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.56-1.11 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.09a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56h.09a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.09a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.56 1.03z"
      />
    </svg>
  )
}

function BugIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 sm:hidden">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M8 8h8a4 4 0 0 1 4 4v1a4 4 0 0 1-2 3.5V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-3.5A4 4 0 0 1 4 13v-1a4 4 0 0 1 4-4zM6 8l-2-3M18 8l2-3M8 3l2 3m6-3-2 3M5 13H2m20 0h-3M5 17H2.5M21.5 17H19"
      />
    </svg>
  )
}

function LogoutIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4 sm:hidden">
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12H3m0 0 4-4m-4 4 4 4M10 4h8a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-8" />
    </svg>
  )
}

function navLinkClass({ isActive }: { isActive: boolean }): string {
  const base =
    'flex items-center gap-2 rounded-full px-2.5 py-1.5 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent sm:px-3'
  return isActive
    ? `${base} text-accentText dark:text-accent`
    : `${base} text-light-textDim hover:text-light-text dark:text-dark-textDim dark:hover:text-dark-text`
}

export default function Navbar({ username, theme }: NavbarProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [current, setCurrent] = useState<Theme>(() => getStoredTheme() ?? theme)
  const { data: errorsData } = useErrors()
  const errorCount = errorsData?.total ?? 0

  const logout = useMutation({
    mutationFn: () => post('/api/v1/auth/logout', {}),
    onSuccess: () => {
      queryClient.clear()
      navigate('/login', { replace: true })
    },
  })

  const saveTheme = useMutation({
    mutationFn: (next: Theme) => put('/api/v1/settings', { theme: next }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })

  useEffect(() => {
    setCurrent(theme)
  }, [theme])

  function toggleTheme() {
    const next: Theme = current === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setCurrent(next)
    saveTheme.mutate(next)
  }

  return (
    <header className="border-b border-light-border bg-light-surface dark:border-dark-border dark:bg-dark-surface">
      <nav className="mx-auto flex max-w-6xl items-center justify-between gap-1 px-3 py-3 sm:gap-2 sm:px-4" aria-label="Main">
        <span className="text-lg font-bold text-light-text dark:text-dark-text">nucs</span>
        <div className="flex items-center gap-0.5 sm:gap-1">
          <NavLink to="/" end className={navLinkClass} aria-label="Feed">
            <HomeIcon />
            <span className="hidden sm:inline">Feed</span>
          </NavLink>
          <NavLink to="/artists" className={navLinkClass} aria-label="Artists">
            <ArtistsIcon />
            <span className="hidden sm:inline">Artists</span>
          </NavLink>
          <NavLink to="/settings" className={navLinkClass} aria-label="Settings">
            <SettingsIcon />
            <span className="hidden sm:inline">Settings</span>
          </NavLink>
          <NavLink to="/errors" className={navLinkClass} aria-label="Errors">
            <BugIcon />
            <span className="hidden sm:inline">Errors</span>
            {errorCount > 0 && (
              <span className="rounded-full bg-danger px-1.5 py-0.5 text-[10px] font-bold leading-none text-light-bg">
                {errorCount}
              </span>
            )}
          </NavLink>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="rounded-full p-2 text-light-textDim transition-colors hover:text-light-text focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:text-dark-textDim dark:hover:text-dark-text"
          >
            {current === 'dark' ? <SunIcon /> : <MoonIcon />}
          </button>
          <span className="hidden max-w-[10rem] truncate text-sm text-light-textDim md:inline dark:text-dark-textDim">
            {username}
          </span>
          <button
            type="button"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            aria-label="Log out"
            title="Log out"
            className="inline-flex items-center gap-1.5 rounded-full border border-light-border px-3 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:border-dark-border dark:text-dark-text dark:hover:bg-dark-bg"
          >
            <LogoutIcon />
            <span className="hidden sm:inline">Log out</span>
          </button>
        </div>
      </nav>
    </header>
  )
}
