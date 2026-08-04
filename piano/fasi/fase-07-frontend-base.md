# FASE 07 — Frontend base: Vite/React/Tailwind, tema, login, layout

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 06 (backend completo fino alle cover)
- **Branch**: `git checkout -b fase-07-frontend-base`

---

## 1. Obiettivo

SPA React funzionante con: routing, tema scuro/chiaro (token §11.1), client API con gestione 401,
pagina login, layout con navbar e rotte protette. Le pagine Feed/Artisti/Impostazioni saranno
riempite nelle fasi 08-09 (ora: stub con titolo). Build integrata: il backend serve `dist/`.

## 2. Prerequisiti

- Fasi backend completate fino alla 06.
- Node 20+ installato per lo sviluppo (`node --version`).
- **Test E2E browser** (sostituiscono i check manuali): `cd e2e && npm ci` una volta
  (installa puppeteer + Chrome headless, ~150-300 MB al primo run). Nessuna dipendenza
  aggiunta a `frontend/package.json`. Dettagli in `e2e/README.md`.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §11 (UI/UX: palette §11.1 ESATTA, pagina login §11.2.1, comportamenti §11.3),
  §5.4 (header X-Requested-With obbligatorio), §10 (endpoint auth), §2 (stack frontend)
- piano/README.md §4
- piano/STATO.md
Branch: fase-07. Codice/commenti inglese, STRINGHE UI IN INGLESE. Versioni pinnate.
Se esistono mockup in piano/mockup/ (generati con piano/mockup-opendesign.md): usali come riferimento visivo vincolante per layout e componenti.

OBIETTIVO
Base frontend: build, tema, login, layout, routing protetto, integrazione static serving.

COMPITI
1. Scaffolding frontend/ con Vite (react-ts) MANUALE (niente create-vite interattivo): scrivi
   package.json con versioni ESATTE di: react, react-dom, react-router-dom@6, @tanstack/react-query@5,
   vite, @vitejs/plugin-react, typescript, tailwindcss@3.4, postcss, autoprefixer. Poi `npm install`
   e COMMITTA package-lock.json. Niente altre dipendenze.
2. tailwind.config.js: darkMode:'class'; content ./src/**; theme.extend.colors ESATTAMENTE i token §11.1
   (accent, accentHover, accentActive, danger + dark./light. bg,surface,surface2,border,text,textDim,
   yt:#FF0000, deezer:#A238FF); borderRadius ereditato; fontFamily stack §11.1.
3. src/theme.ts: getInitialTheme() → localStorage 'nucs-theme' o 'dark'; applyTheme(t) → toggle classe
   'dark' su documentElement + localStorage; usata subito in main.tsx (anti-flash) e poi sincronizzata
   con settings.theme da /auth/me (se diversa da locale → vince server e aggiorna localStorage).
4. src/api/client.ts: fetch wrapper: base '' (same-origin), credentials:'same-origin',
   headers {'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'} su TUTTE le mutazioni;
   su 401 → window.location='/login'; parse json sicuro; tipo ApiError.
5. Router (App.tsx): /login pubblica; Layout protetto (RequireAuth: GET /api/v1/auth/me, loading →
   spinner centrato, errore → /login): rotte / (Feed stub), /releases/:id (stub), /artists (stub),
   /settings (stub). Stub = pagina con H1 in inglese e testo "Under construction".
6. pages/Login.tsx: come §11.2.1: centrata, emoji 🎵 + "nucs", card surface, input username
   e password (label "Username"/"Password", autocomplete username/current-password), bottone accent "Log in",
   errore inline rosso su 401 ("Invalid credentials") e generico su altri errori ("Something went wrong. Try again."); su 204 →
   invalidate query me → navigate '/'. NO password manager hacks.
7. components/Navbar.tsx: logo+ nome, link Feed/Artists/Settings (NavLink con stato attivo accent),
   toggle tema (icone sole/luna SVG inline, aria-label "Toggle theme"), bottone "Log out" (POST logout → /login).
   Mobile <640px: navbar compatta con icone (testo nascosto).
8. Integrazione backend: in app/main.py monta StaticFiles da FRONTEND_DIST (env, default ../frontend/dist)
   su '/' con html=True DOPO i router /api; catch-all: qualsiasi GET non-/api → index.html (SPA fallback);
   404 JSON solo sotto /api. Attenzione a non rompere /api/health.
9. vite.config.ts: plugin react, server.proxy '/api' → http://127.0.0.1:8080 (dev), build.outDir 'dist'.
10. `npm run build` deve produrre dist/ funzionante; typecheck `npx tsc --noEmit` pulito.
11. README-dev? NO: aggiungi a STATO.md i comandi dev (uvicorn + npm run dev).

VINCOLI
- Niente librerie UI (niente MUI/Chakra/HeadlessUI): solo Tailwind + SVG inline. Niente emoji oltre 🎵 login.
- Palette §11.1 esatta; nessun colore arbitrario fuori token (cerca "#" nei file: solo in tailwind.config).
- Nessuna logica di feed/dettaglio/impostazioni: fasi 08-09.

DELIVERABLE
Report + output build/tsc + aggiornamento piano/STATO.md (fase 07).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 07 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd frontend && npm ci && npx tsc --noEmit && npm run build` → tutto exit 0, dist/ generata.
2. Backend integrato: `cd backend && DATA_DIR=/tmp/nucs-d7 FRONTEND_DIST=../frontend/dist /tmp/nucs-venv/bin/uvicorn app.main:app --port 18099 &`
   - `curl -s localhost:18099/` → HTML con <div id="root">.
   - `curl -s localhost:18099/qualcosa/di/spa` → stesso index.html (fallback).
   - `curl -s localhost:18099/api/health` → JSON health (non index.html!).
   - `curl -si localhost:18099/api/v1/auth/me` → 401 JSON.
3. Browser (AUTOMATICO, niente check manuali): build + backend avviato
   (`DATA_DIR=/tmp/nucs-d7 FRONTEND_DIST=../frontend/dist DEV_INSECURE_COOKIES=true
   ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' uvicorn app.main:app --port 8080`)
   poi `cd e2e && npm run e2e:07` → tabella PASS/FAIL (atteso 21/21): login page dark
   (#0F0F0F), "Invalid credentials" inline, login corretto → / con navbar (Feed/Artists/Settings,
   toggle tema, Log out), toggle tema in entrambe le direzioni, persistenza tema dopo reload,
   logout → /login, / senza sessione → redirect /login, zero errori console/CSP/network.
4. Dev-mode: uvicorn :8080 + `npm run dev` → proxy /api funziona (login da :5173).
5. `grep -rn "#[0-9a-fA-F]\{3,6\}" frontend/src` → nessun hex fuori dai token (deve essere vuoto).
6. CSP: `curl -si localhost:18099/ | grep -i content-security` → header presente e la pagina
   funziona senza errori CSP in console browser (script-src 'self' — niente inline scripts).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 07 di nucs.
1. Leggi piano/00-specifiche.md §11 §5.4 §5.5 e piano/checklist-sicurezza.md (B5, B6, C1, F2).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: X-Requested-With su tutte le mutazioni, 401 handling senza loop di redirect,
   catch-all SPA che non inghiotte /api, nessun dangerouslySetInnerHTML, nessun colore fuori token,
   anti-flash tema corretto, package-lock committato, nessuna dipendenza extra, versioni pinnate.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Build + tsc puliti; app servita dal backend con fallback SPA funzionante.
- [ ] Login/logout/tema verificati con `e2e:07` (dark default, persistenza, luce ok) — 21/21 PASS.
- [ ] CSP senza errori console; nessun colore fuori token.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(frontend): base SPA with theme, login, protected layout`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-08-ui-release`.
3. Apri `piano/fasi/fase-08-ui-release.md`.
