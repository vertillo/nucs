# FRONTEND KNOWLEDGE — nucs (child of `/AGENTS.md`)

Frontend-specific supplement. Read the root `/AGENTS.md` first; this file adds frontend detail only and never restates repo-wide rules.

## OVERVIEW

React 18 SPA (Vite 6 + Tailwind 3, `darkMode:'class'`, strict TS) with no own server; the backend Docker stage builds it and serves the static bundle. All data flows through @tanstack/react-query against `/api/v1/*`.

## STRUCTURE (frontend/src/)

- `main.tsx` — entry: React root, QueryClientProvider + BrowserRouter, theme bootstrap
- `App.tsx` — route table + RequireAuth guard (uses `/api/v1/auth/me`) + Navbar/ActivityBar layout
- `theme.ts` — Theme type (`'dark'|'light'`), localStorage key `nucs-theme`, `applyTheme`
- `pages/` — Login (public), Feed (`/`), ReleaseDetail (`/releases/:id`), Artists (`/artists`), Settings (`/settings`), Errors (`/errors`)
- `api/` — `client.ts` (core) + `releases.ts`, `artists.ts`, `settings.ts`, `errors.ts`, `library.ts` (types + react-query hooks per resource)
- `components/` — Navbar, ActivityBar, ReleaseCard, LinkButtons, Toast (shared cross-page widgets only)
- `hooks/useInfiniteScroll.ts` — IntersectionObserver sentinel (Feed + Artists)
- `styles/index.css` — Tailwind directives only

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Routing / auth guard | `src/App.tsx` | RequireAuth, `useMe()` |
| Fetch wrapper / API errors | `src/api/client.ts` | `apiFetch`, `ApiError(status, message)` |
| Resource types + hooks | `src/api/*.ts` | colocated per resource, no `src/types/` |
| Page UI | `src/pages/*.tsx` | one default-export PascalCase per route |
| Shared widgets | `src/components/` | cross-page use only |
| Infinite scroll | `src/hooks/useInfiniteScroll.ts` | used by Feed + Artists |
| Theme switching | `src/theme.ts` | `localStorage 'nucs-theme'` |
| Verification | `npm run build` | `tsc --noEmit && vite build` (no unit tests) |

## CONVENTIONS (frontend-specific)

- **Data access**: components never call `fetch` directly (only Login.tsx raw-fetches). `apiFetch` in `client.ts`: 30s AbortController timeout, `credentials: 'same-origin'`, `X-Requested-With: XMLHttpRequest` (CSRF), 401 → redirect `/login`, `get`/`post`/`put` helpers.
- **Query key families**: `['me']`, `['releases']`, `['artists']`, `['settings']`, `['scan-status']`, `['sessions']`, `['errors']`, `['health']`, `['release', id]`.
- **Optimistic mutations** for seen/hidden/favorite/ignored toggles: `onMutate` cancel+snapshot, `onError` rollback, `onSettled` invalidate.
- **QueryClient defaults**: `retry:false`, `refetchOnWindowFocus:false`, `mutations.networkMode:'always'` (phase 13b finding 13B-03).
- **Page-local primitives**: small UI pieces (Switch, Section, SaveButton, Spinner, modals) are defined LOCALLY in the page; `components/` only holds cross-page widgets.
- **Styling**: Tailwind utilities inline with paired `light-*`/`dark-*` variants; no `@layer components`.
- **Feed filters live in URL query params** (`?type=`, `?unseen=1`, `?q=`) — survive navigation (phase-15); 300ms debounce on search.
- **Infinite scroll**: `useInfiniteQuery` + `useInfiniteScroll` in Feed/Artists.
- **Phase-citing comments** ("phase 12b", "phase 13b finding 13B-03", "phase 15").
- **Client-side validation mirrors backend**: `TIME_RE`/`EMAIL_RE`/`MIN_PASSWORD_LENGTH` duplicated in Settings.tsx.

## ANTI-PATTERNS (frontend-specific)

- No new shared components in `components/` for single-page use — keep primitives local (project convention).
- No state management libs (no Redux/Zustand) — react-query + local state is the pattern.
- No ESLint/Prettier configs — typecheck is the gate; don't assume a linter exists.
- No path aliases in tsconfig/vite — imports are relative.
- Don't remove `noUnusedLocals`/`noUnusedParameters` or `strict` from tsconfig.

## NOTES

- **Monoliths**: `Settings.tsx` (953L) is one ~780-line component with 8 `<Section>` blocks (Discovery/Scans/Notifications/Integrations/Appearance/Security/About/Danger zone); `Artists.tsx` (1030L) inlines AddArtistModal/RetryModal/MatchCell/CandidateDetailsPanel. Edit carefully; extraction is a candidate refactor but NOT required.
- **No unit tests** — verification is `npm run build` (`tsc --noEmit && vite build`) + the e2e harness against the built bundle served by the backend.
- **Dev server proxies `/api` → http://127.0.0.1:8080** — backend must run locally for `npm run dev`.
- **No `public/` dir**; SPA is served by the backend static mount in production.
