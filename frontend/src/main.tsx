import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import { applyTheme, getInitialTheme } from './theme'
import './styles/index.css'

applyTheme(getInitialTheme())

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
    // Phase 13b finding 13B-03: v5 pauses mutations while navigator.onLine is
    // false (networkMode "online"), leaving the UI stuck on "Saving…" with no
    // error. Mutations must always attempt the request so the fetch failure
    // (or the apiFetch timeout) surfaces as an inline error.
    mutations: {
      networkMode: 'always',
    },
  },
})

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
