# nucs E2E: verifica automatica delle fasi 06-16 (puppeteer + Chrome headless)

Harness di test **browser/API** usata dai prompt di verifica delle fasi 06-16.
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
npm run e2e:12b  # fase 12b: feed per giorno/seen/sync, dettaglio con tracklist+9 link, artisti (filtro "Unmatched only"/file sorgente/delete), add-artist multi-provider, pagina errori, reset library
npm run e2e:13   # fase 13b: sottoinsieme deterministico della verifica manuale (fase 13): A4 lockout reale, A5 timing, tema, feed/settings/artisti, viewport, axe, offline, API adversarial, due tab, riavvio backend
npm run e2e:15   # fase 15: correzioni feedback: Status pill (Linked/Needs match/Ignored), sort+badge unmatched, add-by-URL, pannello dettaglio candidato, identità nel modal Manage, filtri feed nei query param, purge-orphans, stato "No tracked artists" (seed come e2e:12b; ~10-15 min)
npm run e2e:16   # fase 16: scenario deterministico della fase 9: 24 flussi con seed locale (solo il flow 5 fa ricerca candidati live; serve un backend live su BASE)
```

Variabili d'ambiente:

| Variabile | Default | Note |
|---|---|---|
| `BASE` | `http://127.0.0.1:8080` | URL dell'app (backend uvicorn locale; per il container con dev override: `http://127.0.0.1:8066`; per fase 11: `https://<tunnel>` ) |
| `ADMIN_USER` | `admin` | credenziali admin |
| `ADMIN_PASS` | `password-lunga-12` | **il backend deve avere QUESTO utente** |
| `E2E_DATA_DIR` | `/tmp/nucs-e2e` | DATA_DIR del backend sotto test: e2e:12 (backup/persistenza), e2e:13 (rename cover, sessione in DB, audit/backup con `E2E_PROD_STACK=1`), e2e:15 (audit log); e2e:16 usa un default dedicato `/tmp/nucs-e2e-f16` |
| `E2E_MUSIC_LIBRARY` | `/tmp/nucs-lib-test` | libreria musica per il seed di e2e:12/13/15; e2e:16 usa un default dedicato `/tmp/nucs-lib-f16` |
| `E2E_13B_QUICK` | unset | solo e2e:13: riduce le attese reali del lockout (solo validazione) |
| `E2E_PROD_STACK` | unset | solo e2e:13: abilita i check J3/J5 (audit log, backup) sullo stack di produzione |

> **Importante**: il backend E2E va avviato con `NOTIFY_URLS=` (vuoto) se esiste un
> `backend/.env` di sviluppo con un URL Apprise reale: le env esplicite hanno
> precedenza sul file `.env` e il seed al primo avvio deve restare pulito
> (altrimenti i check "senza URL" di fase 09 falliscono e partono notifiche reali).

### Deterministico vs rete live

Gli scenari NON sono tutti uguali: distinguono check deterministici, seed con
rete reale e riavvio del backend.

| Scenario | Seed | Riavvio backend | Classificazione |
|---|---|---|---|
| e2e:06 | dati già arricchiti (API) | no | API-only, no browser; check deterministici |
| e2e:07 | nessun seed | no | browser; comportamento app deterministico (login/tema/navbar) |
| e2e:08, 09 | scan libreria + discovery **live** | no | browser; check deterministici sul risultato del seed reale |
| e2e:11 | nessun seed | no | browser su app **containerizzata** (`FRONTEND_DIST=/app/static`), di norma via `https://<tunnel>` |
| e2e:12 | scan libreria + discovery (rete MusicBrainz, ~4-6 min) | **sì** (due volte) | DoD §14; check deterministici |
| e2e:12b | scan libreria + discovery **live** | no | browser; check deterministici |
| e2e:13 | scan libreria + discovery (rete MusicBrainz, ~4-6 min) | **sì** (G4, con `TZ=Pacific/Kiritimati`) | sottoinsieme deterministico della checklist manuale; attese reali del lockout (~15 min) |
| e2e:15 | scan libreria + discovery (rete MusicBrainz + cross-provider, ~6-10 min) | no | check deterministici sul seed reale; scrive nel DB via `sqlite3` per l'audit log |
| e2e:16 | **locale**: identità finte via API + scrittura diretta nel DB (`today_override`); solo il flow 5 fa ricerca candidati live | no | deterministico sul seed locale per 23 flussi; il flow 5 senza provider live degrada a FAIL documentato; **richiede comunque un backend live** su `BASE` |

Sintesi: **nessuno scenario è "network-free" rispetto al backend**: tutti hanno
bisogno di un backend in esecuzione su `BASE` (fase-06 inclusa). La
deterministicità riguarda i CHECK e il seed: e2e:16 è seminato in locale (solo
i POST artist name-only del seed e il flow 5 toccano provider live), mentre
e2e:15 e gli altri scenari "seed lungo" passano da rete MusicBrainz/provider
reali durante il seed.

**Riavvio automatico del backend: SOLO e2e:12 e e2e:13.** Gli altri scenari non
riavviano nulla; e2e:15/16 usano `sqlite3` solo per leggere/scrivere nel DB di
test.

### e2e:12 (accettazione §14): prerequisiti

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

### e2e:13 (fase 13b: sottoinsieme automatizzato della verifica manuale)

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
  `area | PASS/FAIL/N.A. | evidenza`).

### e2e:15 (fase 15: correzioni dal feedback manuale)

Stesse env di e2e:12b (backend su DB di test, `DEV_INSECURE_COOKIES=true`,
`NOTIFY_URLS=`, `MUSIC_LIBRARY_PATH` reale). Il seed fa full library scan +
discovery (rete MusicBrainz + cross-provider, ~6-10 min). Lo scenario
verifica i nuovi flussi della fase 15:

- **Status a pill** (Linked / Needs match / Ignored) con il nome linkato alla
  prima identità di catalogo, badge `unmatched_total` coerente con l'API e sort
  per nome asc/desc. La vecchia colonna Match a 4 stati è stata rimossa
  (contract supersession, spec §3 Artist status): fase-15 verifica il contratto
  nuovo, non quello vecchio.
- **Add Artist by URL** (locale Deezer, risoluzione nome; fallback name+URL se
  il provider è giù), pannello dettaglio candidato, gestione identità nel modal
  **Manage** con ricerca libera e toast "Linked {provider}" (mai falso
  "Matched on MusicBrainz"; nessun pulsante "Search again by name").
- `GET /artists/lookup` e `rematch` con `resolved_split`, purge-orphans (API +
  bottone feed + audit `releases_purged`), filtri feed nei query param
  (sopravvivono a navigazione/back/forward e alla race col debounce), stato
  "No tracked artists" post-reset.
- Usa `E2E_DATA_DIR` (default `/tmp/nucs-e2e`) per il check dell'audit log.
  Esporta la tabella compilata in `artifacts/fase-15-results.md`.

### e2e:16 (fase 16: scenario deterministico della fase 9)

Stesse env di e2e:12b, con `E2E_DATA_DIR` default `/tmp/nucs-e2e-f16` e
`E2E_MUSIC_LIBRARY` default `/tmp/nucs-lib-f16`. Il seed è **locale**: gli
artisti vengono creati via API con identità fisse (nessuna rete), mentre le
release e la chiave `today_override` vengono scritte direttamente nel DB SQLite
di test (stesso seam di test usato dal livello date). Quasi tutti i check sono
deterministici sullo stato seminato; le uniche dipendenze live sono i POST
artist name-only del seed (match MB in background) e la ricerca candidati del
flow 5 (ricerca live su MusicBrainz/Deezer/iTunes/Discogs): se i provider non
rispondono il flow 5 degrada a un FAIL documentato con evidenza, mai a uno
skip silenzioso. fase-16 non è quindi completamente ermetico: l'esito del flow
5 dipende dalla disponibilità dei provider live.

Copre i 24 flussi della fase 9 (spec §2–§4, §13, §15–§18): navbar sticky, Status senza colonne
Match/Source, identity manager multi-provider (sostituzione senza perdere
l'altra identità), sync + refresh che non duplica, 409 sul secondo sync, cancel
con run finale `cancelled`, feed aggiornato senza refresh, progress che esce dal
100% fittizio, badge errori = unread, read/mark-all, errori visibili in All,
report diagnostico Markdown copiabile, tab Upcoming senza controlli seen,
transizione Upcoming→Released con data mockata (`today_override`) e reset
rifiutato durante uno scan.

**Non riavvia il backend**: usa `sqlite3` solo per seminare/leggere il DB di
test. Esporta la tabella compilata in `artifacts/fase-16-results.md`.

## Struttura

- `harness.js`: core, launch Chrome headless, `check()` PASS/FAIL, login UI,
  POST autenticati, poll scan, raccoglitori console/CSP/network/immagini,
  screenshot su FAIL in `e2e/artifacts/`
- `scenarios/fase-XX.js`: uno scenario per fase (le fasi 08+ aggiungono il
  proprio file quando implementano l'UI)
- `artifacts/`: screenshot su FAIL (gitignored)

## Regole per chi aggiunge uno scenario

1. `check()` con messaggio esplicito e `extra` = evidenza (status, valore reale).
2. Gli errori console/network da flussi **intenzionali** (401 di login/logout)
   vanno esclusi con `h.realErrors(state)` / `h.realFailed(state)`.
3. Per i dati reali usare `await h.seed(page)` (login UI → scan library →
   discovery MB) o partire da un DB già popolato; per dati deterministici usare
   il pattern ermetico di fase-16 (identità fisse + scrittura diretta nel DB).
4. Lo scenario deve terminare con `await h.finish(...)` (screenshot + exit code).
