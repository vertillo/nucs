import { useState } from 'react'

import { useClearErrors, useErrors, type AppErrorItem } from '../api/errors'
import Toast, { useToast } from '../components/Toast'

function formatTs(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

function exportPayload(items: AppErrorItem[]): string {
  return JSON.stringify(
    {
      app: 'nucs',
      exported_at: new Date().toISOString(),
      count: items.length,
      errors: items.map(({ id, ts, source, level, message, stack, context }) => ({
        id,
        ts,
        source,
        level,
        message,
        stack,
        context,
      })),
    },
    null,
    2,
  )
}

export default function Errors() {
  const { data, isPending, isError, refetch } = useErrors()
  const clear = useClearErrors()
  const { toast, show } = useToast()
  const [openIds, setOpenIds] = useState<Set<number>>(new Set())
  const [copied, setCopied] = useState(false)

  const items = data?.items ?? []
  const total = data?.total ?? 0

  function toggle(id: number) {
    setOpenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(exportPayload(items))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      show('Copy failed — use the download button', 'error')
    }
  }

  function downloadAll() {
    const blob = new Blob([exportPayload(items)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `nucs-errors-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function handleClear() {
    if (!window.confirm(`Delete all ${total} recorded errors?`)) return
    clear.mutate(undefined, {
      onSuccess: () => show('Errors cleared'),
      onError: (error) => show(error.message, 'error'),
    })
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-light-text dark:text-dark-text">
          Errors {total > 0 && <span className="text-lg text-light-textDim dark:text-dark-textDim">({total})</span>}
        </h1>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={copyAll}
            disabled={items.length === 0}
            className="rounded-full bg-light-surface2 px-4 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            {copied ? 'Copied ✓' : 'Copy JSON'}
          </button>
          <button
            type="button"
            onClick={downloadAll}
            disabled={items.length === 0}
            className="rounded-full bg-light-surface2 px-4 py-1.5 text-sm font-medium text-light-text transition-colors hover:bg-light-border focus:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50 dark:bg-dark-surface2 dark:text-dark-text dark:hover:bg-dark-border"
          >
            Download .json
          </button>
          <button
            type="button"
            onClick={handleClear}
            disabled={clear.isPending || total === 0}
            className="rounded-full border border-danger px-4 py-1.5 text-sm font-medium text-dangerText transition-colors dark:text-danger hover:bg-danger hover:text-light-bg focus:outline-none focus-visible:ring-2 focus-visible:ring-danger disabled:opacity-50"
          >
            {clear.isPending ? 'Clearing…' : 'Clear all'}
          </button>
        </div>
      </div>

      <p className="mt-1 text-sm text-light-textDim dark:text-dark-textDim">
        These are the background failures (scans, providers, matching) and client-side errors. Use Copy JSON or
        Download to report them.
      </p>

      {isPending && <p className="mt-8 text-light-textDim dark:text-dark-textDim">Loading…</p>}

      {isError && (
        <div className="mt-8 flex flex-col items-center gap-3 text-center">
          <p className="text-light-textDim dark:text-dark-textDim">Something went wrong loading errors.</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-full bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accentHover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            Retry
          </button>
        </div>
      )}

      {!isPending && !isError && items.length === 0 && (
        <p className="mt-16 text-center text-light-textDim dark:text-dark-textDim">No errors recorded.</p>
      )}

      {!isPending && !isError && items.length > 0 && (
        <ul className="mt-4 space-y-2">
          {items.map((error) => {
            const open = openIds.has(error.id)
            return (
              <li
                key={error.id}
                className="overflow-hidden rounded-2xl bg-light-surface dark:bg-dark-surface"
              >
                <button
                  type="button"
                  onClick={() => toggle(error.id)}
                  aria-expanded={open}
                  className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-medium text-light-text dark:text-dark-text">
                      {error.message}
                    </span>
                    <span className="mt-0.5 block text-xs text-light-textDim dark:text-dark-textDim">
                      {formatTs(error.ts)} · {error.source} · {error.level}
                    </span>
                  </span>
                  <span className="shrink-0 text-sm text-light-textDim dark:text-dark-textDim">
                    {open ? '▾' : '▸'}
                  </span>
                </button>
                {open && (
                  <div className="space-y-2 border-t border-light-border px-4 py-3 dark:border-dark-border">
                    {error.stack && (
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-light-bg p-3 text-xs text-light-text dark:bg-dark-bg dark:text-dark-text">
                        {error.stack}
                      </pre>
                    )}
                    {error.context != null && (
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-light-bg p-3 text-xs text-light-text dark:bg-dark-bg dark:text-dark-text">
                        {typeof error.context === 'string' ? error.context : JSON.stringify(error.context, null, 2)}
                      </pre>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <Toast toast={toast} />
    </div>
  )
}
