import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, get, put } from '../api/client'
import {
  useChangePassword,
  useHealth,
  useNotifyTest,
  useRevokeOtherSessions,
  useScanStatus,
  useSessions,
  useSettings,
  useStartScan,
  useUpdateSettings,
  type ScanRun,
} from '../api/settings'
import { useTrackedArtistsCount } from '../api/artists'
import { useResetLibrary } from '../api/library'
import type { ReleasesResponse } from '../api/releases'
import Toast, { useToast } from '../components/Toast'
import { applyTheme, type Theme } from '../theme'

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const MIN_PASSWORD_LENGTH = 12

const SCAN_TYPE_LABEL: Record<string, string> = {
  library: 'Library',
  releases: 'Releases',
  feat: 'Featuring',
}

function useReleasesCount() {
  return useQuery<number>({
    queryKey: ['releases-count'],
    queryFn: async () => {
      const body = await get<ReleasesResponse>('/api/v1/releases?page_size=1')
      return body.total
    },
  })
}

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl bg-light-surface p-5 dark:bg-dark-surface">
      <h2 className="text-lg font-semibold text-light-text dark:text-dark-text">{title}</h2>
      <p className="mt-0.5 text-sm text-light-textDim dark:text-dark-textDim">{description}</p>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        checked ? 'bg-accent' : 'bg-light-border dark:bg-dark-border'
      }`}
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-light-bg transition-all dark:bg-dark-bg ${
          checked ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

function SaveButton({ pending, onClick }: { pending: boolean; onClick: () => void }) {
  // anti-double-submit (phase 13b finding 13B-02): the mutation can complete
  // faster than a human double click, so the disabled-while-pending guard alone
  // would let a second request through; keep the button disarmed briefly.
  const [cooldown, setCooldown] = useState(false)
  return (
    <button
      type="button"
      disabled={pending || cooldown}
      onClick={() => {
        setCooldown(true)
        onClick()
        setTimeout(() => setCooldown(false), 600)
      }}
      className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
    >
      {pending ? 'Saving…' : 'Save'}
    </button>
  )
}

const inputClass =
  'w-full rounded-xl border border-light-border bg-light-bg px-3 py-2 text-light-text outline-none focus:ring-2 focus:ring-accent dark:border-dark-border dark:bg-dark-bg dark:text-dark-text'

const labelClass = 'mb-1 block text-sm font-medium text-light-textDim dark:text-dark-textDim'

function FieldError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="mt-1 text-sm text-dangerText dark:text-danger">
      {message}
    </p>
  )
}

function browserOf(ua: string): string {
  if (/Edg\//.test(ua)) return 'Edge'
  if (/Chrome\//.test(ua)) return 'Chrome'
  if (/Firefox\//.test(ua)) return 'Firefox'
  if (/Safari\//.test(ua)) return 'Safari'
  const first = ua.split(' ')[0]
  return first || 'Unknown'
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(
    date.getMinutes(),
  )}`
}

function startedLabel(iso: string): string {
  return formatDateTime(iso)
}

function durationOf(run: ScanRun): string {
  const fromStats = run.stats && run.stats.duration_s !== undefined ? Number(run.stats.duration_s) : NaN
  if (!Number.isNaN(fromStats)) return `${Math.round(fromStats)}s`
  if (run.finished_at) {
    const seconds = (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000
    if (!Number.isNaN(seconds)) return `${Math.round(seconds)}s`
  }
  return '…'
}

function keyStatOf(run: ScanRun): string {
  const stats = run.stats
  if (run.type === 'library') {
    const value = stats && stats.artists_new !== undefined ? Number(stats.artists_new) : NaN
    return Number.isNaN(value) ? '—' : `${value} artist${value === 1 ? '' : 's'}`
  }
  const value = stats && stats.releases_new !== undefined ? Number(stats.releases_new) : NaN
  return Number.isNaN(value) ? '—' : `${value} release${value === 1 ? '' : 's'}`
}

interface DiscoveryForm {
  from: string
  album: boolean
  single: boolean
  ep: boolean
  feat: boolean
  filterOfficial: boolean
}

export default function Settings() {
  const queryClient = useQueryClient()
  const { data: settings, isPending } = useSettings()
  const updateSettings = useUpdateSettings()
  const { toast, show } = useToast()

  // --- Discovery -------------------------------------------------------------
  const [discovery, setDiscovery] = useState<DiscoveryForm>({
    from: '',
    album: true,
    single: true,
    ep: true,
    feat: false,
    filterOfficial: true,
  })
  const [discoveryErrors, setDiscoveryErrors] = useState<{ from?: string; types?: string }>({})

  // --- Scans -------------------------------------------------------------
  const [scanTimes, setScanTimes] = useState({ library: '03:00', releases: '04:00' })
  const [scanTimesErrors, setScanTimesErrors] = useState<{ library?: string; releases?: string }>({})
  const status = useScanStatus()
  const startScan = useStartScan()
  const running = status.data?.running?.type ?? null

  // --- Notifications -------------------------------------------------------------
  const [notify, setNotify] = useState({ enabled: false, urls: '' })
  const [notifyError, setNotifyError] = useState<string | null>(null)
  const notifyTest = useNotifyTest()

  // --- Integrations -------------------------------------------------------------
  const [integrations, setIntegrations] = useState({ clientId: '', clientSecret: '', email: '', discogsToken: '' })
  const [integrationsErrors, setIntegrationsErrors] = useState<{ email?: string }>({})

  // --- Danger zone -------------------------------------------------------------
  const resetLibrary = useResetLibrary()

  // --- Appearance -------------------------------------------------------------
  const [theme, setTheme] = useState<Theme>('dark')
  // Dedicated mutation (like the navbar's): the theme toggle must never
  // collide with an in-flight per-section settings save (parallel PUTs would
  // leave a stale settings cache depending on response order).
  const saveTheme = useMutation({
    mutationFn: (next: Theme) => put('/api/v1/settings', { theme: next }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })

  // --- Security -------------------------------------------------------------
  const [password, setPassword] = useState({ current: '', next: '', repeat: '' })
  const [passwordErrors, setPasswordErrors] = useState<{ next?: string; repeat?: string; submit?: string }>({})
  const [passwordUpdated, setPasswordUpdated] = useState(false)
  const changePassword = useChangePassword()
  const sessions = useSessions()
  const revokeOthers = useRevokeOtherSessions()

  // --- About -------------------------------------------------------------
  const health = useHealth()
  const trackedArtists = useTrackedArtistsCount()
  const releasesInDb = useReleasesCount()

  // Hydrate the section forms from the server only once: re-syncing on every
  // settings change would overwrite edits typed while a PUT is in flight
  // (the save response is written into the cache before onSuccess).
  const hydrated = useRef(false)
  useEffect(() => {
    if (!settings || hydrated.current) return
    hydrated.current = true
    const types = settings.release_types.split(',').map((t) => t.trim())
    setDiscovery({
      from: settings.discovery_from_date,
      album: types.includes('album'),
      single: types.includes('single'),
      ep: types.includes('ep'),
      feat: settings.feat_scan_enabled === 'true',
      filterOfficial: settings.discovery_filter_official === 'true',
    })
    setScanTimes({
      library: settings.scan_library_time,
      releases: settings.scan_releases_time,
    })
    setNotify({
      enabled: settings.notify_enabled === 'true',
      urls: settings.notify_urls
        .split(/[\n,]/)
        .map((line) => line.trim())
        .filter(Boolean)
        .join('\n'),
    })
    setIntegrations((prev) => ({ ...prev, email: settings.mb_contact_email }))
    setTheme(settings.theme)
  }, [settings])

  // Refresh About counts when a scan finishes.
  const wasRunning = useRef<string | null>(null)
  useEffect(() => {
    const now = status.data?.running?.type ?? null
    if (wasRunning.current && !now) {
      queryClient.invalidateQueries({ queryKey: ['releases-count'] })
      queryClient.invalidateQueries({ queryKey: ['artists-count'] })
    }
    wasRunning.current = now
  }, [status.data?.running, queryClient])

  if (isPending) {
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="h-40 animate-pulse rounded-2xl bg-light-surface dark:bg-dark-surface" />
        ))}
      </div>
    )
  }

  function saveDiscovery() {
    const errors: { from?: string; types?: string } = {}
    const fromDate = new Date(discovery.from)
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(discovery.from) ||
      Number.isNaN(fromDate.getTime()) ||
      fromDate > today
    ) {
      errors.from = 'Enter a valid date (YYYY-MM-DD).'
    }
    const selected: string[] = []
    if (discovery.album) selected.push('album')
    if (discovery.single) selected.push('single')
    if (discovery.ep) selected.push('ep')
    if (selected.length === 0) errors.types = 'Select at least one release type.'
    setDiscoveryErrors(errors)
    if (errors.from || errors.types) return
    const serverTypes = settings?.release_types.split(',').map((t) => t.trim()).filter(Boolean) ?? []
    if (serverTypes.includes('other')) selected.push('other')
    updateSettings.mutate(
      {
        discovery_from_date: discovery.from,
        release_types: selected.join(','),
        feat_scan_enabled: discovery.feat,
        discovery_filter_official: discovery.filterOfficial,
      },
      {
        onSuccess: () => show('Saved ✓'),
        onError: (error) => show(error.message, 'error'),
      },
    )
  }

  function saveScanTimes() {
    const errors: { library?: string; releases?: string } = {}
    if (!TIME_RE.test(scanTimes.library)) errors.library = 'Enter a valid time (HH:MM, 24h).'
    if (!TIME_RE.test(scanTimes.releases)) errors.releases = 'Enter a valid time (HH:MM, 24h).'
    setScanTimesErrors(errors)
    if (errors.library || errors.releases) return
    updateSettings.mutate(
      { scan_library_time: scanTimes.library, scan_releases_time: scanTimes.releases },
      {
        onSuccess: () => show('Saved ✓'),
        onError: (error) => show(error.message, 'error'),
      },
    )
  }

  function runScan(type: 'library' | 'releases') {
    // Buttons are aria-disabled (not `disabled`) while a scan runs so the
    // "already in progress" message stays reachable on a late click (spec 11.2.5).
    if (running !== null) {
      show('Scan already in progress', 'error')
      return
    }
    startScan.mutate(type, {
      onSuccess: () => show(type === 'library' ? 'Library scan started' : 'Releases scan started'),
      onError: (error) => {
        if (error instanceof ApiError && error.status === 409) show('Scan already in progress', 'error')
        else show(error.message, 'error')
      },
    })
  }

  function saveNotifications() {
    if (notify.enabled && notify.urls.trim() === '') {
      setNotifyError('Add at least one Apprise URL (scheme://…) or disable notifications.')
      return
    }
    setNotifyError(null)
    updateSettings.mutate(
      { notify_enabled: notify.enabled, notify_urls: notify.urls },
      {
        onSuccess: () => show('Saved ✓'),
        onError: (error) => setNotifyError(error.message),
      },
    )
  }

  function sendTestNotification() {
    // Notifications are on by default (phase 09b): the test only needs URLs.
    if (notify.urls.trim() === '') {
      show('Add at least one Apprise URL first.', 'error')
      return
    }
    notifyTest.mutate(undefined, {
      onSuccess: () => show('Test notification sent'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  function saveIntegrations() {
    const errors: { email?: string } = {}
    if (integrations.email && !EMAIL_RE.test(integrations.email)) {
      errors.email = 'Enter a valid email address.'
    }
    setIntegrationsErrors(errors)
    if (errors.email) return
    const patch: Record<string, string> = { mb_contact_email: integrations.email.trim() }
    if (integrations.clientId.trim()) patch.spotify_client_id = integrations.clientId.trim()
    if (integrations.clientSecret.trim()) patch.spotify_client_secret = integrations.clientSecret.trim()
    if (integrations.discogsToken.trim()) patch.discogs_token = integrations.discogsToken.trim()
    updateSettings.mutate(patch, {
      onSuccess: () => {
        setIntegrations((prev) => ({ ...prev, clientId: '', clientSecret: '', discogsToken: '' }))
        show('Saved ✓')
      },
      onError: (error) => show(error.message, 'error'),
    })
  }

  function handleResetLibrary() {
    if (
      !window.confirm(
        'Reset the whole library?\n\nThis deletes all artists, releases, states, scan caches and the downloaded covers. Settings and your account stay.\n\nThis cannot be undone.',
      )
    ) {
      return
    }
    if (!window.confirm('Are you absolutely sure? Type nothing to keep it.\n\nThis is the last confirmation.')) {
      return
    }
    resetLibrary.mutate(undefined, {
      onSuccess: () => {
        show('Library reset')
        queryClient.invalidateQueries({ queryKey: ['releases'] })
        queryClient.invalidateQueries({ queryKey: ['artists'] })
        queryClient.invalidateQueries({ queryKey: ['artists-count'] })
        queryClient.invalidateQueries({ queryKey: ['releases-count'] })
        queryClient.invalidateQueries({ queryKey: ['scan-status'] })
      },
      onError: (error) => show(error.message, 'error'),
    })
  }

  function pickTheme(next: Theme) {
    setTheme(next)
    applyTheme(next)
    saveTheme.mutate(next, {
      onError: () => {
        // Local theme stays active; the server wins again on next load (see phase 07).
      },
    })
  }

  function submitPassword(event: React.FormEvent) {
    event.preventDefault()
    const errors: { next?: string; repeat?: string; submit?: string } = {}
    if (password.next.length < MIN_PASSWORD_LENGTH) {
      errors.next = `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`
    }
    if (password.next !== password.repeat) {
      errors.repeat = 'Passwords do not match.'
    }
    setPasswordErrors(errors)
    if (errors.next || errors.repeat) return
    setPasswordUpdated(false)
    changePassword.mutate(
      { current_password: password.current, new_password: password.next },
      {
        onSuccess: () => {
          setPassword({ current: '', next: '', repeat: '' })
          setPasswordUpdated(true)
          show('Password updated')
          queryClient.invalidateQueries({ queryKey: ['sessions'] })
        },
        onError: (error) => {
          setPasswordErrors({ submit: error.message })
        },
      },
    )
  }

  const scanButtonsDisabled = running !== null || startScan.isPending

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">Settings</h1>

      <div className="mt-4 space-y-6">
        <Section
          title="Discovery"
          description="From which date releases are discovered, which release types are tracked and the weekly featuring scan."
        >
          <div className="space-y-4">
            <div>
              <label htmlFor="discovery-from-date" className={labelClass}>
                Discover releases from
              </label>
              <input
                id="discovery-from-date"
                type="date"
                value={discovery.from}
                onChange={(e) => setDiscovery((f) => ({ ...f, from: e.target.value }))}
                className={inputClass}
              />
              <FieldError message={discoveryErrors.from} />
            </div>
            <div>
              <span className="block text-sm font-medium text-light-textDim dark:text-dark-textDim">Release types</span>
              <div className="mt-2 flex flex-wrap gap-4">
                {(
                  [
                    ['album', 'Albums', discovery.album],
                    ['single', 'Singles', discovery.single],
                    ['ep', 'EPs', discovery.ep],
                  ] as const
                ).map(([key, label, checked]) => (
                  <label key={key} className="flex cursor-pointer items-center gap-2 text-sm text-light-text dark:text-dark-text">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => setDiscovery((f) => ({ ...f, [key]: e.target.checked }))}
                      className="h-4 w-4 accent-accent"
                    />
                    {label}
                  </label>
                ))}
              </div>
              <FieldError message={discoveryErrors.types} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-light-text dark:text-dark-text">Weekly featuring scan</span>
              <Switch
                checked={discovery.feat}
                onChange={(v) => setDiscovery((f) => ({ ...f, feat: v }))}
                label="Weekly featuring scan"
              />
            </div>
            <div className="flex items-center justify-between gap-3">
              <div>
                <span className="block text-sm text-light-text dark:text-dark-text">Only official releases</span>
                <span className="text-xs text-light-textDim dark:text-dark-textDim">
                  Excludes bootlegs and unofficial reworks (e.g. "Yeezus (Andre's Rework)").
                </span>
              </div>
              <Switch
                checked={discovery.filterOfficial}
                onChange={(v) => setDiscovery((f) => ({ ...f, filterOfficial: v }))}
                label="Only official releases"
              />
            </div>
            <div className="flex items-center gap-3">
              <SaveButton pending={updateSettings.isPending} onClick={saveDiscovery} />
            </div>
          </div>
        </Section>

        <Section title="Scans" description="Daily scan times, manual scan triggers and the history of recent runs.">
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="scan-library-time" className={labelClass}>
                  Library scan time
                </label>
                <input
                  id="scan-library-time"
                  type="time"
                  value={scanTimes.library}
                  onChange={(e) => setScanTimes((t) => ({ ...t, library: e.target.value }))}
                  className={inputClass}
                />
                <FieldError message={scanTimesErrors.library} />
              </div>
              <div>
                <label htmlFor="scan-releases-time" className={labelClass}>
                  Releases scan time
                </label>
                <input
                  id="scan-releases-time"
                  type="time"
                  value={scanTimes.releases}
                  onChange={(e) => setScanTimes((t) => ({ ...t, releases: e.target.value }))}
                  className={inputClass}
                />
                <FieldError message={scanTimesErrors.releases} />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <SaveButton pending={updateSettings.isPending} onClick={saveScanTimes} />
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                aria-disabled={scanButtonsDisabled}
                onClick={() => runScan('library')}
                className={`inline-flex items-center gap-2 rounded-full bg-light-surface2 px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border ${
                  scanButtonsDisabled ? 'cursor-not-allowed opacity-50' : ''
                }`}
              >
                {running === 'library' && <Spinner />}
                Scan library now
              </button>
              <button
                type="button"
                aria-disabled={scanButtonsDisabled}
                onClick={() => runScan('releases')}
                className={`inline-flex items-center gap-2 rounded-full bg-light-surface2 px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border ${
                  scanButtonsDisabled ? 'cursor-not-allowed opacity-50' : ''
                }`}
              >
                {running === 'releases' && <Spinner />}
                Check for new releases now
              </button>
              {status.data?.running && (
                <span className="self-center text-sm text-light-textDim dark:text-dark-textDim">
                  {SCAN_TYPE_LABEL[status.data.running.type] ?? status.data.running.type} scan in progress…
                </span>
              )}
            </div>
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-light-textDim dark:text-dark-textDim">
                Recent scans
              </h3>
              {status.data && status.data.last_runs.length > 0 ? (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-light-border text-left text-xs uppercase tracking-wide text-light-textDim dark:border-dark-border dark:text-dark-textDim">
                        <th className="px-2 py-2 font-medium">Type</th>
                        <th className="px-2 py-2 font-medium">Started</th>
                        <th className="px-2 py-2 font-medium">Duration</th>
                        <th className="px-2 py-2 font-medium">Result</th>
                        <th className="px-2 py-2 font-medium">Stats</th>
                      </tr>
                    </thead>
                    <tbody>
                      {status.data.last_runs.map((run) => (
                        <tr key={run.id} className="border-b border-light-border dark:border-dark-border">
                          <td className="px-2 py-2 text-light-text dark:text-dark-text">
                            {SCAN_TYPE_LABEL[run.type] ?? run.type}
                          </td>
                          <td className="px-2 py-2 text-light-textDim dark:text-dark-textDim">
                            {startedLabel(run.started_at)}
                          </td>
                          <td className="px-2 py-2 text-light-textDim dark:text-dark-textDim">{durationOf(run)}</td>
                          <td className="px-2 py-2">
                            {run.status === 'ok' ? (
                              <span className="font-medium text-accentText dark:text-accent">ok</span>
                            ) : (
                              <span className="font-medium text-dangerText dark:text-danger">error</span>
                            )}
                          </td>
                          <td className="px-2 py-2 text-light-textDim dark:text-dark-textDim">{keyStatOf(run)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-2 text-sm text-light-textDim dark:text-dark-textDim">No scans yet.</p>
              )}
            </div>
          </div>
        </Section>

        <Section
          title="Notifications"
          description="Optional notifications via Apprise when new releases are discovered."
        >
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-light-text dark:text-dark-text">Notifications enabled</span>
              <Switch checked={notify.enabled} onChange={(v) => setNotify((n) => ({ ...n, enabled: v }))} label="Notifications enabled" />
            </div>
            <div>
              <label htmlFor="notify-urls" className={labelClass}>
                Apprise URLs (one per line)
              </label>
              <textarea
                id="notify-urls"
                rows={3}
                value={notify.urls}
                onChange={(e) => setNotify((n) => ({ ...n, urls: e.target.value }))}
                placeholder="tgram://token/chat_id"
                className={inputClass}
              />
              <FieldError message={notifyError} />
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <SaveButton pending={updateSettings.isPending} onClick={saveNotifications} />
              <button
                type="button"
                onClick={sendTestNotification}
                disabled={notifyTest.isPending}
                className="inline-flex items-center gap-2 rounded-full bg-light-surface2 px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
              >
                {notifyTest.isPending && <Spinner />}
                Send test notification
              </button>
            </div>
          </div>
        </Section>

        <Section
          title="Integrations"
          description="Optional Spotify credentials for direct album links and the MusicBrainz contact email."
        >
          <div className="space-y-4">
            <div>
              <label htmlFor="spotify-client-id" className={labelClass}>
                Spotify Client ID
              </label>
              <input
                id="spotify-client-id"
                type="text"
                autoComplete="off"
                value={integrations.clientId}
                onChange={(e) => setIntegrations((i) => ({ ...i, clientId: e.target.value }))}
                placeholder={settings?.spotify_client_id_set ? '••••••••' : ''}
                className={inputClass}
              />
            </div>
            <div>
              <label htmlFor="spotify-client-secret" className={labelClass}>
                Spotify Client Secret
              </label>
              <input
                id="spotify-client-secret"
                type="password"
                autoComplete="new-password"
                value={integrations.clientSecret}
                onChange={(e) => setIntegrations((i) => ({ ...i, clientSecret: e.target.value }))}
                placeholder={settings?.spotify_client_secret_set ? '••••••••' : ''}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-light-textDim dark:text-dark-textDim">
                Stored value is never shown; leave empty to keep it unchanged.
              </p>
            </div>
            <div>
              <label htmlFor="mb-contact-email" className={labelClass}>
                MusicBrainz contact email
              </label>
              <input
                id="mb-contact-email"
                type="email"
                autoComplete="off"
                value={integrations.email}
                onChange={(e) => setIntegrations((i) => ({ ...i, email: e.target.value }))}
                className={inputClass}
              />
              <FieldError message={integrationsErrors.email} />
            </div>
            <div>
              <label htmlFor="discogs-token" className={labelClass}>
                Discogs personal access token
              </label>
              <input
                id="discogs-token"
                type="password"
                autoComplete="new-password"
                value={integrations.discogsToken}
                onChange={(e) => setIntegrations((i) => ({ ...i, discogsToken: e.target.value }))}
                placeholder={settings?.discogs_token_set ? '••••••••' : ''}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-light-textDim dark:text-dark-textDim">
                Optional, enables Discogs artist search and releases. Stored value is never shown; leave empty to keep
                it unchanged.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <SaveButton pending={updateSettings.isPending} onClick={saveIntegrations} />
            </div>
          </div>
        </Section>

        <Section title="Appearance" description="Choose the color theme of the app.">
          <div role="radiogroup" aria-label="Appearance" className="flex gap-6">
            {(
              [
                ['dark', 'Dark'],
                ['light', 'Light'],
              ] as const
            ).map(([value, label]) => (
              <label
                key={value}
                className="flex cursor-pointer items-center gap-2 text-sm text-light-text dark:text-dark-text"
              >
                <input
                  type="radio"
                  name="appearance-theme"
                  value={value}
                  checked={theme === value}
                  onChange={() => pickTheme(value)}
                  className="h-4 w-4 accent-accent"
                />
                {label}
              </label>
            ))}
          </div>
        </Section>

        <Section
          title="Security"
          description="Change the admin password and manage active sessions."
        >
          <div className="space-y-6">
            <form onSubmit={submitPassword} className="space-y-4">
              <div>
                <label htmlFor="pw-current" className={labelClass}>
                  Current password
                </label>
                <input
                  id="pw-current"
                  type="password"
                  autoComplete="current-password"
                  value={password.current}
                  onChange={(e) => setPassword((p) => ({ ...p, current: e.target.value }))}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="pw-new" className={labelClass}>
                  New password
                </label>
                <input
                  id="pw-new"
                  type="password"
                  autoComplete="new-password"
                  value={password.next}
                  onChange={(e) => setPassword((p) => ({ ...p, next: e.target.value }))}
                  className={inputClass}
                />
                <FieldError message={passwordErrors.next} />
              </div>
              <div>
                <label htmlFor="pw-repeat" className={labelClass}>
                  Repeat new password
                </label>
                <input
                  id="pw-repeat"
                  type="password"
                  autoComplete="new-password"
                  value={password.repeat}
                  onChange={(e) => setPassword((p) => ({ ...p, repeat: e.target.value }))}
                  className={inputClass}
                />
                <FieldError message={passwordErrors.repeat} />
              </div>
              <FieldError message={passwordErrors.submit} />
              {passwordUpdated && (
                <p role="status" className="text-sm font-medium text-accentText dark:text-accent">
                  Password updated. All other sessions have been revoked.
                </p>
              )}
              <button
                type="submit"
                disabled={changePassword.isPending}
                className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover active:bg-accentActive focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
              >
                {changePassword.isPending ? 'Updating…' : 'Update password'}
              </button>
            </form>

            <div>
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-light-textDim dark:text-dark-textDim">
                  Active sessions
                </h3>
                <button
                  type="button"
                  disabled={revokeOthers.isPending}
                  onClick={() =>
                    revokeOthers.mutate(undefined, {
                      onSuccess: () => show('Other sessions revoked'),
                      onError: (error) => show(error.message, 'error'),
                    })
                  }
                  className="rounded-full border border-danger px-3 py-1.5 text-sm font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
                >
                  {revokeOthers.isPending ? 'Revoking…' : 'Revoke other sessions'}
                </button>
              </div>
              {sessions.isPending ? (
                <p className="mt-2 text-sm text-light-textDim dark:text-dark-textDim">Loading…</p>
              ) : sessions.data && sessions.data.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {sessions.data.map((session) => (
                    <li
                      key={session.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-light-bg px-3 py-2 text-sm dark:bg-dark-bg"
                    >
                      <span className="min-w-0 text-light-text dark:text-dark-text">
                        {truncate(browserOf(session.user_agent), 40)}
                        <span className="ml-2 text-light-textDim dark:text-dark-textDim">{session.ip}</span>
                      </span>
                      <span className="flex items-center gap-2">
                        <span className="text-light-textDim dark:text-dark-textDim">
                          {formatDateTime(session.last_seen_at)}
                        </span>
                        {session.current && (
                          <span className="rounded-full bg-accent px-2 py-0.5 text-xs font-semibold text-black">
                            Current
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-light-textDim dark:text-dark-textDim">No active sessions.</p>
              )}
            </div>
          </div>
        </Section>

        <Section title="About" description="Application information.">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-light-textDim dark:text-dark-textDim">App version</dt>
              <dd className="mt-0.5 font-medium text-light-text dark:text-dark-text">
                {health.data?.version ?? '…'}
              </dd>
            </div>
            <div>
              <dt className="text-light-textDim dark:text-dark-textDim">Tracked artists</dt>
              <dd className="mt-0.5 font-medium text-light-text dark:text-dark-text">
                {trackedArtists.data ?? '…'}
              </dd>
            </div>
            <div>
              <dt className="text-light-textDim dark:text-dark-textDim">Releases in DB</dt>
              <dd className="mt-0.5 font-medium text-light-text dark:text-dark-text">
                {releasesInDb.data ?? '…'}
              </dd>
            </div>
            <div>
              <dt className="text-light-textDim dark:text-dark-textDim">Library path</dt>
              <dd className="mt-0.5 font-medium text-light-text dark:text-dark-text">
                Configured via environment variable
              </dd>
            </div>
          </dl>
        </Section>
        <Section
          title="Danger zone"
          description="Destructive actions that cannot be undone."
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-light-text dark:text-dark-text">Reset library</p>
              <p className="mt-0.5 text-xs text-light-textDim dark:text-dark-textDim">
                Deletes all artists, releases, seen/hidden states, scan caches and the downloaded covers. Settings and
                your account stay. Refused while a scan is running.
              </p>
            </div>
            <button
              type="button"
              disabled={resetLibrary.isPending}
              onClick={handleResetLibrary}
              className="rounded-full border border-danger px-4 py-2 text-sm font-semibold text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
            >
              {resetLibrary.isPending ? 'Resetting…' : 'Reset library'}
            </button>
          </div>
        </Section>
      </div>

      <Toast toast={toast} />
    </div>
  )
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-light-border border-t-accent dark:border-dark-border dark:border-t-accent"
    />
  )
}
