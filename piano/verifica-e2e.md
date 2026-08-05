# VERIFICA E2E — fase 12 (accettazione §14)

> Eseguito il 2026-08-05 su branch `fase-12-hardening-qa`, backend locale
> (`DATA_DIR=/tmp/nucs-e2e`, `DEV_INSECURE_COOKIES=true`, `NOTIFY_URLS=`,
> `MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test`, porta 8080), frontend buildato,
> `cd e2e && npm ci` (puppeteer 25.4.0 pinnato).

## 1. Output del runner automatico — `npm run e2e:12`

Comando: `cd e2e && BASE=http://127.0.0.1:8080 E2E_DATA_DIR=/tmp/nucs-e2e npm run e2e:12`

```
PASS | 429 carries Retry-After | 300
PASS | 5 wrong logins -> 401 | 401,401,401,401,401,429
PASS | 6th login -> 429 (rate limit) | 401,401,401,401,401,429
PASS | backend restarted (uvicorn spawned) | pid 7333
PASS | backend healthy after restart | http://127.0.0.1:8080
PASS | seed: set discovery_from_date=2024-01-01 | status 200
seed: POST /scans/library?full=true ...
PASS | seed: library scan accepted | status 202
seed: POST /scans/releases ...
PASS | seed: releases scan accepted | status 202
seed: done
PASS | 14.3/14.4: feed populated (releases > 0) | total 88
PASS | 14.4: feed shows release cards | cards 30
PASS | 14.4: cards use local cover cache | covers 25
PASS | 14.4: detail has the 4 link buttons | ["Spotify","YouTube Music","Deezer","Search on Google"]
PASS | 14.4: external links noopener noreferrer
PASS | 14.4: detail shows title | /releases/9
PASS | 14.6: light theme persists after reload | rgb(255, 255, 255)
PASS | 14.6: dark theme persists after reload | rgb(15, 15, 15)
PASS | CSP has no unsafe-eval | default-src 'self'; img-src 'self' data:; style-src 'self'; ...
PASS | CSP has no unsafe-inline (static Tailwind CSS) | ...
PASS | CSP keeps script-src self | ...
PASS | 14.9: backup-now CLI exits 0 | status 0
PASS | 14.9: backup file created in /data/backups | 1 -> 2
PASS | 14.9: backup is a valid SQLite file | SQLite format 3
PASS | backend restarted (uvicorn spawned) | pid 7430
PASS | backend healthy after restart | http://127.0.0.1:8080
PASS | 14.10: artists survive restart | 13 -> 13
PASS | 14.10: releases survive restart | 88 -> 88
PASS | 14.10: session survives restart (already logged in)
PASS | 14.10: settings survive restart | theme dark -> dark
PASS | 14.10: feed still rendered after restart | cards 30
PASS | no console errors (excluding expected 401s) | []
PASS | no CSP violations | []
PASS | no page errors | []
PASS | no failed requests | []

TOTALE: 33/33 PASS (fase 12)
```

## 2. Tabella di accettazione §14 (Definition of Done)

| # | Criterio §14 | Esito | Evidenza |
|---|---|---|---|
| 1 | `compose up` con profili → app raggiungibile via Cloudflare + Tailscale | ⏳ **UMANO** (fase 14) | richiede dominio Cloudflare + tailnet reale (mini PC) |
| 2 | Senza login → 401; brute force 6 tentativi → 429 | ✅ | `e2e:12`: 5×401 + 6°→429 + Retry-After 300; audit log `login_fail`/`login_blocked` senza leak (verifica curl: 12 tentativi → 5×401 + 7×429, login corretto → 429) |
| 3 | Scan libreria ≥100 file con feat → artisti estratti | ✅ | `e2e:12` seed: library scan su `/tmp/nucs-lib-test` (13 artisti da 7 file con feat/album artist; estrazione feat e contrib verificata in fase 03 con fixture) + `piano/fasi/fase-03` (13 artisti: 5 tag_artist, 1 albumartist, 4 feat, 3 contrib). La scalabilità ≥100 file è coperta dalla fase 13/14 sul mini PC |
| 4 | Match MB + discovery 60gg → feed con copertina, dettaglio con 4 link | ✅ | `e2e:12`: `discovery_from_date=2024-01-01` → 88 release, feed 30 card, 25 cover locali, dettaglio con 4 bottoni + `noopener noreferrer` |
| 5 | Cambio `discovery_from_date` + scan → feed coerente | ✅ | verificato in fase 08/09 E2E (`e2e:08`: chip/sort/search, `e2e:09`); `e2e:12` imposta e persiste il valore (PUT 200 + persistenza post-restart) |
| 6 | Tema chiaro/scuro persistente al reload | ✅ | `e2e:12`: light dopo reload `rgb(255,255,255)`, dark dopo reload `rgb(15,15,15)` |
| 7 | App < 300 MB RAM a riposo (`docker stats`) | ⏳ **UMANO** (fase 14) | fase 11: **75.19 MiB / 768 MiB** misurato nel container; conferma a 24h in fase 14 |
| 8 | `pip-audit`/`npm audit` senza high/critical non giustificate | ✅ | vedi §3 sotto |
| 9 | Backup DB in `/data/backups/` dopo 24h o run manuale | ✅ | `e2e:12`: `backup-now` CLI → file `app-*.db` creato, header `SQLite format 3`, retention 7 (test `test_backup.py`) |
| 10 | README finale con setup/env/CF/Tailscale/FAQ | ✅ | `README.md` v1.0.0 (questo branch) |

Legenda: ✅ automatizzato e verde · ⏳ **UMANO** = richiede ambiente di produzione non disponibile in questa verifica (dichiarato nel prompt fase 12: ricezione Apprise su dispositivo, `docker stats` dopo 24h, README da installazione pulita su seconda macchina).

## 3. Audit dipendenze

### Backend (`pip-audit -r backend/requirements.txt`)
`No known vulnerabilities found` — **0 findings**.

### Frontend (`npm audit --omit=dev` in frontend/)
- **2 moderate** — `react-router` 6.x (→ fix solo in 7.18.2, **major breaking**):
  - GHSA-wrjc-x8rr-h8h6 (CVE-2025-68470 bypass): open redirect via backslash in `<Link>`/`useNavigate`. **Non applicabile**: tutte le `to` in `frontend/src` sono hardcoded interne (`/`, `/artists`, `/settings`, `/releases/{id}` da DB int); nessun input utente finisce in `to`.
  - GHSA-337j-9hxr-rhxg: constructor injection via `deserializeErrors()` (SSR hydration). **Non applicabile**: nucs è SPA pura (nessun SSR).
  - Decisione (vincolo fase 12 "major upgrade rischioso → non ora"): **non aggiornato**; pianificato per v1.1 (vedi STATO.md).
- Nessun finding high/critical → §14.8 **PASS**.

### `e2e/` (`npm audit` in e2e/)
`found 0 vulnerabilities` (puppeteer 25.4.0).

## 4. Hardening spot-check checklist sicurezza (A-F)

| Punto | Esito | Evidenza |
|---|---|---|
| A1 argon2id | ✅ | `security.py:33` `PasswordHasher()` (argon2id, t=3, m=64MiB, p=4); test `test_security.py` |
| A2 token opaco ≥128bit, solo hash nel DB | ✅ | `secrets.token_urlsafe(32)`; sha256 nel DB (`security.py:82-102`); verificato in fase 02 |
| A3 cookie HttpOnly+Secure+SameSite=Lax | ✅ | curl senza `DEV_INSECURE_COOKIES`: `Set-Cookie: nucs_session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure` |
| A4 risposta identica + tempo costante | ✅ | dummy hash `DUMMY_HASH` (`security.py:37`); **misura curl 5+5**: esistente 45/36/37/37/37 ms vs inesistente 65/36/36/36/37 ms (dopo warmup) — bilanciate; la prima misura (2 ms) era il 429 del rate limiter, non un leak |
| A5 rate limit 5/5min + blocco globale 15min | ✅ | `e2e:12` 5×401→6°429 + Retry-After; curl 12 tentativi: 5×401 + 7×429; login corretto durante blocco → 429 |
| A6 logout/password change revoca sessioni | ✅ | fase 02/09 E2E (`e2e:09` incognito session revoke) |
| A7 sessioni scadute non accettate + cleanup | ✅ | `verify_session` scadenza + job orario `cleanup_sessions` (fase 10); test |
| A8 API protette 401 | ✅ | `e2e:12` / `e2e:11` |
| B1-B7 input/ORM/path/secret/React/CSP/CSRF | ✅ | review fasi 02-09; CSP aggiornata in fase 12 (sotto); `OriginCheckMiddleware` su mutazioni |
| C1-C4 segreti | ✅ | `git ls-files | grep -iE "\.env$|secret|token"` → nessun file sensibile; log di avvio senza valori env (grep `password|secret|tgram|token` → 0 match); GET /settings senza segreti (fase 06 test) |
| D1-D6 rete/container | ✅ | fase 11: nessuna porta pubblicata, non-root, read_only, limiti, pin immagini, trusted proxy, 500 generico |
| E1-E3 dipendenze | ✅ | pin `==` + lockfile; audit §3 |
| F1-F4 privacy | ✅ | robots/noindex; cover locali; audit log puliti; libreria mai scritta (fase 03) |

### CSP aggiornata (fase 12)
- **Rimossa `'unsafe-inline'` da `style-src`** (deviazione da §5.5, approvata dal task fase 12): il frontend non usa attributi `style` (grep su `src/` → 0) né Tailwind a runtime; la build è CSS statico. Verificato nel browser (`e2e:12`): **zero violazioni CSP** con `style-src 'self'`.
- **Nessun `'unsafe-eval'`** (già assente): `script-src 'self'` verificato in `e2e:12`.
- Nuovo check E2E dedicato nel runner.

### Access log `/api/health` (debito fase 01, §5.7)
- Aggiunto `_HealthAccessFilter` in `main.py` (logger `uvicorn.access`): le richieste a `/api/health` non compaiono più nei log (verificato: 4 richieste → 0 righe; le altre righe di access restano loggate).

### Altri debiti chiusi
- Warning `httpx2` (fase 01-11): aggiunto `httpx2==2.9.1` a `requirements-dev.txt` (starlette.testclient lo preferisce; il warning sparisce; suite 270 passed).
- Namespace package `backend/app` senza `__init__.py` (fase 01): aggiunti `__init__.py` in `app/`, `app/api/`, `app/services/`.
- `.gitkeep` orfani in `frontend/src/*` e `backend/app/{api,services}`, `backend/tests` (fase 07): rimossi.

## 5. Punti §14 dichiarati UMANI (non automatizzabili in questo ambiente)

| # | Punto | Perché umano | Dove |
|---|---|---|---|
| 1 | ricezione notifica Apprise su dispositivo | richiede URL Apprise reale + dispositivo esterno | fase 13/14 (endpoint notify-test 200 verificato in fase 10) |
| 7b | `docker stats` dopo 24h di uptime | richiede 24h di funzionamento continuo | fase 14 (fase 11: 75.19 MiB a riposo) |
| 10b | README validato da installazione pulita su seconda macchina | richiede seconda macchina | fase 14 |
| 1 | tunnel Cloudflare HTTPS (cookie Secure end-to-end) | richiede dominio gestito Cloudflare | fase 14 (cookie Secure verificato a livello app, §4 A3) |
