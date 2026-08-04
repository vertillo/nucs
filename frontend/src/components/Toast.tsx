import { useCallback, useEffect, useRef, useState } from 'react'

export type ToastKind = 'success' | 'error'

export interface ToastData {
  id: number
  message: string
  kind: ToastKind
}

/** Tiny self-contained feedback: a green/red pill that disappears after 4s. */
export function useToast() {
  const [toast, setToast] = useState<ToastData | null>(null)
  const timer = useRef<number | undefined>(undefined)

  const show = useCallback((message: string, kind: ToastKind = 'success') => {
    window.clearTimeout(timer.current)
    setToast({ id: Date.now(), message, kind })
    timer.current = window.setTimeout(() => setToast(null), 4000)
  }, [])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  return { toast, show }
}

export default function Toast({ toast }: { toast: ToastData | null }) {
  if (!toast) return null
  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed bottom-6 left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium shadow-lg shadow-black/20 ${
        toast.kind === 'success' ? 'bg-accent text-black' : 'bg-danger text-light-bg'
      }`}
    >
      {toast.message}
    </div>
  )
}
