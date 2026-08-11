# nucs E2E — verifica automatica delle fasi (puppeteer + Chrome headless)

Harness di test **browser/API** usata dai prompt di verifica delle fasi 06-15.
Sostituisce i "check manuali nel browser": lo stesso flusso viene eseguito
da Chrome headless, con tabella PASS/FAIL ed exit code ≠ 0 se qualcosa fallisce.

## Prerequisiti (da installare una volta)

- **Node ≥ 20** (stesso requisito del build frontend; verificare con `node --version`)
- **npm** (incluso con Node)
- **Backend in esecuzione** con admin attivo (vedi sotto)
- Alla prima installazione puppeteer **scarica Chrome for Testing**
  (~150-300 MB in `~/.cache/puppeteer`): serve la rete, una volta sola.

```bash
cd e2e
npm ci                       # installa puppeteer (pinnato) + package-lock.json
```

Niente altre dipendenze: `puppeteer` e `axe-core` (accessibilità, usato solo da
e2e:13) sono gli unici package e NON toccano `frontend/package.json` (l'app
resta senza dipendenze extra).

## Avvio dell'app sotto test

Per gli scenari browser (07+), l'app deve essere **buildata e servita dal backend**
(così si testa anche CSP e static serving), con cookie insicuri attivi per http:

```bash
cd frontend && npm run build
cd backend && DATA_DIR=/tmp/nucs-e2e DEV_INSECURE_COOKIES=true \
  ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' \
  .venv/bin/uvicorn app.main:app --port 8080
```

Lo scenario fase-06 (solo API/curl) funziona anche su un backend senza frontend
ma con dati arricchiti da fase 06 (release con link + cover).

## Esecuzione

```bash
cd e2e
npm run e2e:06   # fase 06: link esterni §9 + endpoint /covers (API, no browser)
npm run e2e:07   # fase 07: login, tema, navbar, logout, redirect, CSP (browser)
npm run e2e:08   # fase 08: feed release + dettaglio (browser, seed lungo)
npm run e2e:09   # fase 09: artisti + impostazioni (browser, seed lungo)
npm run e2e:11   # fase 11: login+tema+logout+security headers (browser, container)
npm run e2e:12   # fase 12: DoD §14 automatizzabili (brute force, seed+feed+dettaglio, tema, backup, persistenza)
npm run e2e:12b  # fase 12b: feed per giorno/seen/sync, dettaglio senza Favorite con tracklist+9 link, artisti (filtro unmatched/retry/delete), add-artist multi-provider, pagina errori, reset library
npm run e2e:13   # fase 13b: sottoinsieme deterministico della verifica manuale (fase 13) — A4 lockout reale, A5 timing, tema, feed/settings/artisti, viewport, axe, offline, API adversarial, due tab, riavvio backend
npm run e2e:15   # fase 15: correzioni feedback — colonna Match (MB/provider/Unmatched/Split), sort+badge unmatched, add-by-URL, pannello dettaglio candidato, retry con ricerca libera + toast, filtri feed nei query param, purge-orphans, stato "No tracked artists" (seed come e2e:12b; ~10-15 min)
```

Variabili d'ambiente:

| Variabile | Default | Note |
|---|---|---|
| `BASE` | `http://127.0.0.1:8080` | URL dell'app (backend uvicorn locale; per il container con dev override: `http://127.0.0.1:8066`; per fase 11: `https://<tunnel>` ) |
| `ADMIN_USER` | `admin` | credenziali admin |
| `ADMIN_PASS` | `password-lunga-12` | **il backend deve avere QUESTO utente** |
| `E2E_DATA_DIR` | `/tmp/nucs-e2e` | solo e2e:12 — DATA_DIR del backend sotto test (backup/persistenza) |
| `E2E_MUSIC_LIBRARY` | `/tmp/nucs-lib-test` | solo e2e:12 — libreria musica per il seed |

> **Importante**: il backend E2E va avviato con `NOTIFY_URLS=` (vuoto) se esiste un
> `backend/.env` di sviluppo con un URL Apprise reale: le env esplicite hanno
> precedenza sul file `.env` e il seed al primo avvio deve restare pulito
> (altrimenti i check "senza URL" di fase 09 falliscono e partono notifiche reali).

### e2e:12 (accettazione §14) — prerequisiti

Avviare il backend con **DATA_DIR=$E2E_DATA_DIR** e la libreria di test
`/tmp/nucs-lib-test` (o puntare `E2E_MUSIC_LIBRARY` a un'altra):

```bash
rm -rf /tmp/nucs-e2e && mkdir -p /tmp/nucs-e2e
cd backend && DATA_DIR=/tmp/nucs-e2e DEV_INSECURE_COOKIES=true NOTIFY_URLS= \
  ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' \
  MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test \
  .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Lo scenario **riavvia il backend da solo** (per il reset del rate limiter
in-memory e per la prova di persistenza §14.10) usando le stesse env; il seed
richiede rete MusicBrainz (~4-6 min). Il primo `pkill` colpisce SOLO la porta
di `BASE`: se il backend gira su un'altra porta/container, passare
`BASE`/`E2E_DATA_DIR` coerenti o non usare il riavvio automatico.

### e2e:13 (fase 13b — sottoinsieme automatizzato della verifica manuale)

Stesse env di e2e:12b (backend su DB di test, `DEV_INSECURE_COOKIES=true`,
`NOTIFY_URLS=`, `MUSIC_LIBRARY_PATH` reale). Il seed fa full library scan +
discovery (rete MusicBrainz, ~4-6 min). Lo scenario:

- esegue le voci deterministiche della checklist fase 13 (vedi header di
  `scenarios/fase-13.js`) e alla fine **riavvia il backend da solo** (G4, kill
  per porta di BASE + spawn uvicorn con le stesse env + `TZ=Pacific/Kiritimati`
  per G5): se il backend gira su un'altra porta/container, passare
  `BASE`/`E2E_DATA_DIR` coerenti.
- A4 richiede l'**attesa reale del lockout globale** (~15 min): il run completo
  dura ~35-50 min. `E2E_13B_QUICK=1` riduce le attese (solo validazione).
- usa `E2E_DATA_DIR` (default `/tmp/nucs-e2e`) per: rename cover su disco (C13),
  sessione scaduta in DB (A11), audit log/backup (J3/J5, solo con
  `E2E_PROD_STACK=1`).
- esporta la checklist compilata in `artifacts/fase-13-results.md` (tabella
  `area | PASS/FAIL/N.A. | evidenza` da incollare in STATO.md).

### e2e:15 (fase 15 — correzioni dal feedback manuale)

Stesse env di e2e:12b (backend su DB di test, `DEV_INSECURE_COOKIES=true`,
`NOTIFY_URLS=`, `MUSIC_LIBRARY_PATH` reale). Il seed fa full library scan +
discovery (rete MusicBrainz + cross-provider, ~6-10 min). Lo scenario
verifica i nuovi flussi della fase 15: semantica "matched" multi-provider
(colonna Match a 4 stati, nome linkato, badge `unmatched_total`, sort
asc/desc), Add Artist by URL (locale Deezer, risoluzione nome; fallback
name+URL se il provider è giù), pannello dettaglio candidato, retry con
ricerca libera e toast coerenti (mai falso "Matched on MusicBrainz"),
`GET /artists/lookup` e `rematch` con `resolved_split`, purge-orphans (API +
bottone feed + audit `releases_purged`), filtri feed nei query param
(sopravvivono a navigazione/back/forward e alla race col debounce), stato
"No tracked artists" post-reset. Usa `E2E_DATA_DIR` (default `/tmp/nucs-e2e`)
per il check dell'audit log. Esporta la tabella compilata in
`artifacts/fase-15-results.md`.

## Struttura

- `harness.js` — core: launch Chrome headless, `check()` PASS/FAIL, login UI,
  POST autenticati, poll scan, raccoglitori console/CSP/network/immagini,
  screenshot su FAIL in `e2e/artifacts/`
- `scenarios/fase-XX.js` — uno scenario per fase (le fasi 08+ aggiungono il
  proprio file quando implementano l'UI)
- `artifacts/` — screenshot su FAIL (gitignored)

## Regole per chi aggiunge uno scenario

1. `check()` con messaggio esplicito e `extra` = evidenza (status, valore reale).
2. Gli errori console/network da flussi **intenzionali** (401 di login/logout)
   vanno esclusi con `h.realErrors(state)` / `h.realFailed(state)`.
3. Per i dati reali usare `await h.seed(page)` (login UI → scan library →
   discovery MB) o partire da un DB già popolato.
4. Lo scenario deve terminare con `await h.finish(...)` (screenshot + exit code).
