# STATO DEL PROGETTO — diario di avanzamento

> Questo file viene aggiornato dal modello alla fine di ogni fase.
> Ogni prompt di fase inizia leggendo questo file + `piano/00-specifiche.md`.
> Formato: una sezione per fase completata, più recente in cima.

## Riepilogo rapido

- Fase corrente: **11** → aprire `piano/fasi/fase-11-docker-rete.md` (**review con modello avanzato**)
- Fasi completate: 00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 09b, 10 (fase 13 = checklist manuale, da eseguire dopo la 12)
- **Fase 14 (verifica di produzione, dopo la 13)**: `piano/fasi/fase-14-verifica-produzione.md` —
  deploy e verifica completa sul mini PC (HTTPS tailnet senza dominio, scans vera libreria,
  IP reali, Cloudflare quando ci sarà un dominio); chiusura dei punti "differiti" della fase 11
- Branch attivo: `fase-11-docker-rete` (fase-10 mergiata su main con `e25c3ac`)
- Decisione di percorso (registrata): sviluppo su Mac + container multi-arch (build locale per
  macchina, nessun registry); container eseguibile su più macchine; mini PC solo come macchina
  di deploy (verifica in fase 14)
- Problemi aperti: warning deprecazione `httpx2` da `fastapi.testclient` (non bloccante); header `server: uvicorn` visibile in dev (fix in fase 11); **il `backend/.env` di sviluppo con URL Apprise reale va neutralizzato nei backend E2E con `NOTIFY_URLS=`** (documentato in `e2e/README.md`; il gap notify-test è chiuso — endpoint implementato in fase 10)
- Idee emerse ma rimandate (v2): nessuna

---

## FASE 10 — Scheduler, backup DB, notifiche Apprise — 2026-08-04
- Branch: fase-10-scheduler-notifiche
- Cosa è stato fatto:
  - **Dipendenze** (`requirements.txt`): `apscheduler==3.11.3` (AsyncIOScheduler, spec 2) e `apprise==1.12.0` (multi-provider, spec 1.2).
  - **`backend/app/scheduler.py`** (nuovo): singleton `AsyncIOScheduler(timezone=settings.TZ)` avviato nel lifespan (dopo migrazioni/seed) e spento con `shutdown(wait=False)` all'uscita (idempotente, gestisce `SchedulerNotRunningError`). `populate_jobs(scheduler, db)` ricostruisce i job da settings (idempotente: rimuove i job esistenti prima di aggiungere — **mai duplicati**); `refresh_jobs(db)` chiamato dal PUT /settings quando il payload tocca `SCHEDULE_KEYS` (`scan_library_time`, `scan_releases_time`, `feat_scan_weekday`, `feat_scan_enabled`). Job (tutti `coalesce=True, max_instances=1, misfire_grace_time=3600`):
    - `library_scan` daily da `scan_library_time` → `library_scan.start_library_scan` (include auto-match fase 04)
    - `releases_scan` daily da `scan_releases_time` → discovery livello 1
    - `feat_scan` weekly (weekday da `feat_scan_weekday`, alla stessa ora di `scan_releases_time`) **solo se `feat_scan_enabled`**
    - `backup_db` daily **02:30** (fisso) → `backup.backup_now` in `to_thread`
    - `cleanup_sessions` hourly → `security.cleanup_expired_sessions` in `to_thread` (**sostituisce il vecchio loop asyncio di main.py, rimosso** — niente doppia esecuzione)
    - I job riusano gli STESSI lock degli scan manuali (`scan_locks`): se occupato → log INFO `"skipped, already running"`, mai doppia esecuzione.
  - **`backend/app/services/backup.py`** (nuovo): `backup_now(db_path, backup_dir={DATA_DIR}/backups)` con la **API di backup online di sqlite3** (sorgente aperta `mode=ro`, safe su WAL in uso) → `app-YYYYMMDD-HHMMSS.db`; **retention 7** (`_cleanup_old`, solo file `app-<data>-<ora>.db`, i più vecchi cancellati); log path+dimensione. CLI `python -m app.cli backup-now`.
  - **`backend/app/services/notify.py`** (nuovo): `send_notification(title, body)` async → legge settings (`notify_enabled`, `notify_urls`), **Apprise MAI invocato se disabilitato o senza URL** (ritorna `(False, "Notifications are disabled")` / `"No notification URLs configured"`), URL splittati su `[\n,]` con strip (lista anche mista tgram://+ntfy://), invio sync in `to_thread`, non lancia mai (difensivo). `maybe_notify_new_releases(new_rgids)` — **hook aggregato** (§8.4.3) chiamato a fine `run_discovery` (solo se `releases_new` rilevati via rgid): 1 sola notifica `"nucs: {n} new releases"` con le prime 5 righe `"Artist – Title (type, date)"` + `"…and {k} more"`.
  - **Endpoint `POST /api/v1/settings/notify-test`** (nuovo, `require_user`): disabilitato → 400 `"Notifications are disabled"`; senza URL → 400 `"No notification URLs configured"`; altrimenti invio → `{"sent": true}` o 400 con l'errore inglese. **Colma il gap segnalato in fase 09** (endpoint mancante).
  - **`main.py`**: lifespan avvia/arresta lo scheduler; rimosso `_session_cleanup_loop` e i relativi import.
  - **`cli.py`**: comando `backup-now`.
- Decisioni prese (e perché):
  - **Orari di default** (documentati qui come richiesto): scan libreria `03:00`, scan release `04:00` (spec §4), backup `02:30` (fisso da prompt), feat scan weekly alla stessa ora dello scan release, cleanup sessioni ogni ora.
  - **Misfire**: `misfire_grace_time=3600` — un job che non è partito all'orario esatto (es. app in stop o evento loop occupato) viene comunque eseguito entro 1h; oltre viene perso (loggato da APScheduler). `coalesce=True`: se più run sono in ritardo ne parte una sola. `max_instances=1`: mai due istanze dello stesso job.
  - **Backup via API sqlite3 backup** (non copia a caldo): coerente con WAL — richiesto dalla review.
  - **Reschedule solo sulle chiavi di scheduling** (`SCHEDULE_KEYS`): un PUT di altre sezioni non tocca i job.
  - **Scheduler nei test**: fixture autouse `_no_scheduler` — `start_scheduler` diventa no-op e viene installato un `AsyncIOScheduler` **mai avviato** come singleton (i job NON possono partire durante pytest; `refresh_jobs` resta ispezionabile). Il test del reschedule PUT lo usa per ispezionare i trigger.
  - **Fixture `_no_real_notifications`**: `send_notification` no-op in tutti i test (come mb_matching); test_notify ri-abilita la funzione reale esplicitamente (`REAL_SEND_NOTIFICATION`, stesso pattern di `REAL_MATCH_ALL_PENDING`).
  - **Hermeticità dei test dall'ambiente reale**: `app_env` ora forza `NOTIFY_URLS=""` e rimuove `NOTIFY_ENABLED` — il `backend/.env` di sviluppo (con token reali) non deve mai filtrare nei test (bug trovato in verifica: i test seedavano l'URL reale dell'utente).
- Test (nuovi): `test_backup.py` (6: copia apribile+integro, dir default, DB aperto, retention 7 su 9 file, file estranei ignorati), `test_notify.py` (11: disabled→nessuna chiamata, senza URL→errore chiaro, enabled→apprise chiamato con TUTTI gli URL, URL invalido, provider failure, aggregata 1 sola notifica 5+1 righe con ordine per data desc, skip se disabled/senza URL, mai eccezioni), `test_scheduler.py` (8: 5 job con trigger corretti, feat solo se enabled con weekday, reschedule via PUT senza duplicati, skip con lock occupato, wiring al launcher, SCHEDULE_KEYS), `test_settings_api.py` (+4 notify-test: disabled 400, senza URL 400, successo, failure riportata). Suite: **267 passed** (238 → 267), ruff check+format OK.
- Esito verifica (reale, backend su :8099 con DB fresco, credenziali e URL Apprise dal `backend/.env`):
  - Scheduler: log `"scheduler started with 5 jobs"`; PUT `scan_releases_time` a +2 min → `"scheduler jobs refreshed: 5 jobs"` → **run releases partito alle 20:59:00 UTC** esatto, status ok; **riavvio → 5 job, nessun duplicato**.
  - Backup CLI: `app-20260804-225947.db` (102400 byte), `PRAGMA integrity_check` → ok.
  - Notifiche: **POST notify-test → 200 `{"sent": true}` con URL reale (notifica Telegram inviata — conferma umana richiesta all'utente)**; con `notify_enabled=false` → 400 `"Notifications are disabled"`.
  - Seed env da `.env` reale confermato (`"settings seeded from env: notify_urls"`, `notify_urls` len 64, mai stampata).
  - **Regressione `e2e:09` → 43/43 PASS** — dopo il fix del leak del `.env` (vedi sotto).
- Problemi noti / debito tecnico:
  - **Leak del `.env` di sviluppo nei backend E2E** (bug trovato in verifica): con `backend/.env` presente, il backend di test seedava l'URL reale → il check "notify-test senza URL" falliva e partiva una notifica reale. Fix operativo: avviare i backend E2E con `NOTIFY_URLS=` esplicita (le env vincono sul dotenv); documentato in `e2e/README.md`.
  - Il job `feat_scan` usa l'ora di `scan_releases_time` (interpretazione, il prompt non specificava l'ora del job weekly) — registrato qui.
  - Restano: warning httpx2, header `server: uvicorn` (fase 11).
- Istruzioni avvio dev (fase 10):
  ```bash
  # backend: scheduler attivo al boot (5 job), notifiche dal backend/.env se presente
  DATA_DIR=/tmp/nucs-f10 DEV_INSECURE_COOKIES=true ADMIN_USERNAME=admin \
    ADMIN_PASSWORD='password-lunga-12' .venv/bin/uvicorn app.main:app --port 8080
  # backup manuale
  python -m app.cli backup-now
  # test (hermetici: l'env reale è neutralizzato dalle fixture)
  .venv/bin/python -m pytest -q
  ```

---

## FASE 09b — Notifiche: default attivo e seed da env — 2026-08-04
- Branch: fase-09b-notifiche-env
- Cosa è stato fatto:
  - **`backend/app/config.py`**: nuove settings `notify_urls: str = ""` (env `NOTIFY_URLS`, URL Apprise opzionali, anche misti tgram://+ntfy://) e `notify_enabled: bool | None = None` (env `NOTIFY_ENABLED`; `None` = env assente → non sovrascrive il default).
  - **`backend/app/main.py`**: `_DEFAULT_SETTINGS["notify_enabled"]` da `"false"` a `"true"` (**deviazione da §4, registrata sotto**); `seed_settings_if_empty()` applica gli override da env **solo quando la tabella settings è vuota** (stessa semantica primo-avvio di ADMIN_* di §5.1): NOTIFY_URLS non vuota → seed `notify_urls`; NOTIFY_ENABLED esplicitamente impostata → seed quel valore. Log INFO con i **soli nomi delle chiavi** (mai i valori: possono contenere token Telegram, checklist C4). Nessuna validazione bloccante al boot.
  - **`backend/app/api/settings.py` (rilassamento necessario, registrato sotto)**: il check cross-field "notify_enabled senza URL → 422" ora scatta **solo se la richiesta abilita esplicitamente** le notifiche (`notify_enabled` presente nel PUT). Con il default true, altrimenti QUALSIASI salvataggio di altre sezioni fallirebbe su installazione nuova senza URL.
  - **`frontend/src/pages/Settings.tsx`**: guard di `sendTestNotification` basato solo sugli URL (`if (notify.urls.trim() === '')`) — con il default true lo switch non blocca più il messaggio "Add at least one Apprise URL first.".
  - **`.env.example`**: aggiunte `NOTIFY_URLS=` e `NOTIFY_ENABLED=` con commento (opzionali; seed solo al primo avvio; supportano più URL anche misti).
  - **Test**: `test_db.py` — default true senza URL, seed da env su DB fresco (multi-URL), `NOTIFY_ENABLED=false`, env ignorato su tabella già popolata (riavvio); `test_settings_api.py` — assert aggiornato a `notify_enabled=="true"`, nuovo test "salvataggi di altre sezioni passano con default attivo". Suite: **237 passed** (232 → 237).
- Decisioni prese (e perché):
  - **Default notify_enabled=true (deviazione da §4, approvata dall'utente)**: notifiche attive di default ma disattivabili dalla UI; "attive senza URL" = **no-op silenzioso** (nessun invio, nessun warning bloccante); l'errore appare solo se salvi la sezione Notifications con switch ON e textarea vuota (come prima). L'invio reale resta gated da `notify_urls` non vuota.
  - **Semantica env primo-avvio (§5.1)**: NOTIFY_URLS/NOTIFY_ENABLED valgono SOLO su DB vuoto (tabella settings senza chiavi); dopo un save UI (o qualsiasi boot successivo) il DB vince. Così ricreando il container con volume nuovo le notifiche funzionano subito, e la UI resta sovrana. Nessun override live (renderebbe ambigui GET/PUT /settings).
  - **Supporto Telegram + ntfy**: nessuna struttura dedicata — Apprise gestisce entrambi via scheme (`tgram://`, `ntfy://`) e `notify_urls` è una lista CSV che accetta più URL anche misti (già dalla fase 06; la UI li accetta una riga ciascuno).
  - **Rilassamento del check cross-field (conseguenza necessaria, registrato)**: il vincolo della fase diceva "nessuna modifica ai validatori", ma con il default true il vecchio check (che leggeva lo stato CURRENT del DB) avrebbe fatto fallire QUALSIASI PUT di altre sezioni su installazione nuova senza URL — regressione bloccante per la UI di fase 09. Rilassamento minimo e semantico: il 422 scatta solo quando la richiesta abilita esplicitamente le notifiche senza URL (comportamento richiesto dall'utente: "è necessario l'url/token per tenerle attive"). Test di regressione dedicato.
- Deviazioni dalle specifiche (approvate da chi): (1) default `notify_enabled` true invece di false (§4) — approvato dall'utente; (2) `.env.example` esteso oltre la lista esatta di §12.3 con 2 chiavi opzionali; (3) check cross-field di `PUT /settings` rilassato come sopra.
- Esito verifica (boot reali via uvicorn + curl, come da file di fase):
  - DB fresco + `NOTIFY_URLS="tgram://tok/chat"` → login → GET /settings → `notify_urls` valorizzato e `notify_enabled` "true" **senza toccare la UI** ✓.
  - Stesso DB con env diverse (`tgram://OTHER/chat`, NOTIFY_ENABLED=false) → GET /settings restituisce i valori precedenti (env ignorato, seed non rieseguito) ✓.
  - DB fresco senza env → `notify_enabled` "true", `notify_urls` "" ✓.
  - DB fresco con `NOTIFY_ENABLED=false` → seed "false" ✓.
  - `grep -i tgram` sui log dei 4 boot → **0** (mai loggati i valori) ✓.
  - `pytest` **237 passed**, ruff check + format OK; frontend `tsc --noEmit` + build OK.
  - **`e2e:09` → 43/43 PASS** (prima esecuzione con il nuovo default true: check "notify-test senza URL → messaggio chiaro" e tutti i save delle sezioni verdi).
- Problemi noti / debito tecnico: nessuno nuovo; restano i noti (notify-test endpoint fase 10, aria-disabled, httpx2/uvicorn header).
- Istruzioni avvio dev (fase 09b):
  ```bash
  # backend con notifiche pre-configurate al primo avvio (DB vuoto)
  NOTIFY_URLS="tgram://<token>/<chat_id>" DATA_DIR=/tmp/nucs-f09b \
    DEV_INSECURE_COOKIES=true ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' \
    .venv/bin/uvicorn app.main:app --port 8080
  ```

---

## FASE 09 — UI: pagina artisti + pagina impostazioni — 2026-08-04
- Branch: fase-09-ui-artisti-impostazioni
- Cosa è stato fatto:
  - **`frontend/src/api/artists.ts`** (nuovo): tipi TS allineati a §10 (`ArtistItem`, `ArtistsResponse`), `useArtists(filters)` (infinite query come il feed, "Load more" con `page*page_size < total`), `useTrackedArtistsCount` (GET `/artists?ignored=no&page_size=1` → total, per About), `useAddArtist` (POST → 202, invalidate), `useSetArtistIgnored` (**PATCH ottimistico** con rollback — attenzione: l'updater di `setQueriesData` deve gestire la shape `{pages, pageParams}` delle infinite query, NON una `ArtistsResponse` piatta: la prima versione assumeva `old.items` → `onMutate` lanciava → react-query abortiva la mutation **senza errore visibile** → il toggle non faceva nulla (bug trovato in E2E, fix documentato sotto)), `useRematchArtist` (POST rematch → invalidate).
  - **`frontend/src/api/settings.ts`** (nuovo): `Settings` con i booleani server tipati `'true'|'false'` (il backend serializza stringhe), `useSettings`, `useUpdateSettings` (**PUT che setta il cache con la risposta piena** + invalidate `me`), `useScanStatus` (**polling 3s SOLO mentre `running != null`** via `refetchInterval: (query) => query.state.data?.running ? 3000 : false`), `useStartScan` (POST `/scans/{type}` → invalidate status), `useNotifyTest` (POST `/settings/notify-test`, endpoint assente → vedi sotto), `useChangePassword` (POST `/auth/password`), `useSessions`, `useRevokeOtherSessions`, `useHealth` (GET `/api/health`, pubblico).
  - **`frontend/src/components/Toast.tsx`** (nuovo): `useToast()` + pill verde/rossa `role="status"` fissa in basso, sparisce dopo 4s, nessuna libreria.
  - **`frontend/src/pages/Artists.tsx`** (§11.2.4): H1 "Tracked artists"; toolbar con search "Search artist…" (debounce 300ms), select [All|Active|Ignored] → `ignored=all|no|yes`, bottone accent "+ Add artist" → **modale** (overlay `role=dialog aria-modal`, autofocus, Escape, click fuori, "Add"/"Cancel", su 400 → "Artist already exists"/"Invalid artist name" inline); **tabella responsive** (`hidden md:table` + card list mobile `md:hidden`): Name | Source badge (mappa tag_artist→Artist, tag_albumartist→Album artist, tag_feat→Featuring, tag_contrib→Contributor, manual→Manual) | MB match (**✅ + score accent se mbid**, altrimenti **⚠️ Unmatched** + bottone text-sm "Retry" → rematch → esito inline nella riga + toast; 503 → messaggio d'errore) | Releases (n) | switch "Ignore" (`role=switch aria-checked`, ottimistico). "Load more" come il feed; skeleton; empty state; errore con Retry.
  - **`frontend/src/pages/Settings.tsx`** (§11.2.5): layout card impilate `max-w-3xl` (`Section` con H2 + descrizione textDim). **a. Discovery**: `input type=date` "Discover releases from", checkbox Albums/Singles/EPs → CSV (almeno 1 obbligatorio, errore inline; **preserva "other" se presente nel server**), switch "Weekly featuring scan", Save → PUT → toast "Saved ✓". **b. Scans**: due `input type=time` (HH:MM validato inline come il server), bottoni "Scan library now"/"Check for new releases now" con spinner e `aria-disabled` mentre running (vedi decisioni), tabella "Recent scans" (tipo, inizio ISO, durata da `stats.duration_s` o diff, esito ok/error, stats chiave: `artists_new` per library / `releases_new` per releases-feat). **c. Notifications**: switch notify_enabled, textarea "Apprise URLs (one per line)" (CSV↔righe via split `[\n,]`), guard client "Add at least one Apprise URL…" + errore inline se notify_enabled senza URL (spec server), bottone "Send test notification". **d. Integrations**: Spotify Client ID (text), Client Secret (`type=password`, placeholder "••••••••" se `spotify_client_secret_set`, **inviati SOLO se l'utente scrive**, svuotati dopo il save — mai mostrati), "MusicBrainz contact email" (regex client = regex server, errore inline). **e. Appearance**: radio Dark/Light → `applyTheme` immediato + PUT `{theme}` + invalidate `me` (navbar si sincronizza). **f. Security**: form cambio password (Current/New/Repeat, validazione client: min 12 char e coincidenza, errori inline; POST `/auth/password` → "Password updated. All other sessions have been revoked." + invalidate sessions; 400 "Current password is incorrect"/429 inline), lista "Active sessions" (browser da user_agent troncato 40 char, IP, ultimo accesso locale "YYYY-MM-DD HH:MM", badge accent "Current") + bottone danger "Revoke other sessions". **g. About**: versione da `/api/health`, artisti trackati (count), release nel DB (count), library path → "Configured via environment variable" (GET /settings non lo espone, fallback spec-sanctioned); i due count si invalidano quando una run termina (watcher su `running`).
  - **Backend (cambio minimo e documentato, vedi sotto)**: `releases_count` ora popolato in `GET/POST/PATCH /artists` con una singola query raggruppata (era hardcoded 0 — bug bloccante per la colonna "Releases").
  - **`e2e/scenarios/fase-09.js`** (nuovo) + script `e2e:09` in `e2e/package.json`: harness estesa in locale al file (helper per click per-sezione, set di input React-controlled, waitForToast, listener 404 in Network).
- Decisioni prese (e perché):
  - **Fix bug frontend (E2E) — infinite query vs `setQueriesData`**: `useSetArtistIgnored` ottimistico: `queryClient.setQueriesData(['artists'], updater)` riceve la shape **InfiniteData `{pages, pageParams}`**, non `ArtistsResponse`; `old.items` era `undefined` → l'updater lanciava dentro `onMutate` → react-query v5 **abortisce la mutation** (nessun PATCH inviato, nessun errore in console, solo stato UI invariato). Fix: helper `patchArtistIgnored` che riconosce `{pages}` vs risposta piatta. Trovato con instrumentazione (`onMutate` con try/catch + console.error).
  - **`aria-disabled` + guard client sui bottoni scan invece dell'attributo `disabled`** (deviazione registrata): con `disabled`, i click sono soppressi dal browser/React mentre running → il messaggio "Scan already in progress" (richiesto da §11.2.5) sarebbe **codice morto irraggiungibile** (il doppio click nello stesso tick non produce un secondo POST: React 18 flushes gli eventi discreti in modo sincrono, il secondo click cade su un nodo ri-renderizzato; verificato empiricamente in E2E). Ora: bottone `aria-disabled` + `opacity-50 cursor-not-allowed` (stessa percezione visiva e a11y), e `runScan` mostra "Scan already in progress" se `running != null`; il contratto 409 del server resta verificato direttamente in E2E (`POST` → 409). La chiamata al server su race genuine produce comunque il messaggio dal `detail`.
  - **POST `/settings/notify-test` NON esiste nel backend** (vedi anche "Problemi noti"): è in §10 e nel prompt di fase ma non è mai stato implementato (Apprise è fase 10). Vincolo rispettato: **NON modificato il backend** (il notify-test reale richiede la dipendenza Apprise, fase 10). Il bottone è cablato all'endpoint; la guard client mostra "Add at least one Apprise URL first." senza URL; con URL la chiamata risponde 404 finché la fase 10 non implementa l'endpoint. Registrato qui come richiesto.
  - **Fix backend (bug bloccante, segnalato)**: §10 dice che `GET /artists` "include `releases_count`"; il campo era hardcoded a 0 con commento "populated in phase 05" mai adempiuto → la colonna Releases della pagina artisti sarebbe sempre 0. Fix minimo: conteggio per artista con **una sola query raggruppata** su `release_artists` (no N+1) per lista, POST e PATCH; test aggiornato (fixture con release+role → count reale). Suite: 232 passed.
  - **Release types UI**: la spec prevede solo checkbox Album/Single/EP; se il server ha "other" nel CSV, il save lo preserva (evita perdita di dati). Almeno 1 obbligatorio lato client, stesso messaggio coerente col server.
  - **Date sessioni "YYYY-MM-DD HH:MM"**: convertite nel timezone del browser (§11.3); le date scan mostrate come ISO dal server (UTC, `replace('T',' ')` slice 16).
  - **Polling scans**: `refetchInterval` funziona SOLO mentre `running != null`; a fine run l'ultimo poll porta la riga nuova (nessun polling quando non serve — niente memory leak).
  - **About counts refresh a fine scan**: `useEffect` su `status.running` → invalidate `['releases-count']`/`['artists-count']` quando running passa da non-null a null.
- Ambiguità riscontrate (interpretazione scelta): nessuna ambiguità di spec; l'unica lacuna è l'endpoint notify-test (sopra).
- Deviazioni dalle specifiche (approvate da chi): (1) `aria-disabled` + guard sui bottoni scan (sopra, necessaria per rendere raggiungibile il messaggio 409 richiesto dalla spec); (2) fix backend `releases_count` (bug bloccante §10, con test); (3) notifica: bottone presente ma endpoint backend assente fino alla fase 10 (vincolo rispettato: segnalato, non implementato).
- Test: backend — **232 passed** (test `releases_count` aggiornato con conteggio reale), ruff check + format OK. Frontend — `tsc --noEmit` + `npm run build` puliti; grep hex in src/index.html/vite.config.ts/package.json → 0 (hex solo in tailwind.config.js).
- Esito verifica (E2E automatico, backend reale su :8094 con MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test, DB fresco):
  - **`npm run e2e:09` → 43/43 PASS**: artisti — lista popolata, badge source, search "daft" filtra (debounce), toggle Ignore → artista sotto il filtro "Ignored", add artist nuovo nome → in lista + background match → "Unmatched" visibile, Retry → esito inline "No match found", duplicato → errore inline nel modale; Discovery — data cambiata → Save → reload → persistita, zero tipi selezionati → errore inline; Scans — tabella recent scans dal seed, click "Scan library now" → aria-disabled+spinner → riga nuova con ok+stats, "Check for new releases now" → aria-disabled, **POST diretto → 409**, secondo click → toast "Scan already in progress", riga releases a fine run (polling); Notifications — senza URL → messaggio chiaro; Integrations — secret finto → Save → reload → placeholder "••••••••" e valore vuoto, **GET /settings senza il secret nel body**; Appearance — Light immediato, persiste al reload e dopo logout/login, ritorno a Dark; Security — <12 char → errore inline, attuale errata → "Current password is incorrect", corretta → "Password updated", **seconda sessione in contesto incognito** → revoca → 401 al refresh (redirect /login); About — versione 1.0.0, count artisti/release, library path placeholder; mobile 375px — card list al posto della tabella, nessuno scroll orizzontale su entrambe le pagine; console pulita (filtrati i 2 messaggi 4xx intenzionali: 400 del password-errata e 409 del probe diretto), zero violazioni CSP, zero page errors, **zero 404 in Network**.
  - Regressioni: `e2e:08` su backend fresco (:8095) → **30/30 PASS**; `e2e:07` (:8096) → **21/21 PASS**; pytest 232, ruff OK.
  - Note operativa per l'E2E: i seed E2E richiedono rete MusicBrainz e DB **fresco** a ogni run (il cambio password e i toggle ignorati non sono idempotenti su DB sporco; il run fallito lascia uno scan in corso che rompe il seed successivo → usare DATA_DIR nuovo e riavviare uvicorn).
- Problemi noti / debito tecnico:
  - **`POST /settings/notify-test` manca dal backend** (spec §10, fase 10): il bottone "Send test notification" con URL risponde 404 finché la fase 10 non lo implementa (guard client senza URL funziona già).
  - I bottoni scan usano `aria-disabled` (non l'attributo `disabled`): deviazione registrata sopra (per rendere raggiungibile il messaggio 409).
  - La colonna "Releases" degli artisti usa `releases_count` ora reale (fix backend di questa fase).
  - `server: uvicorn` + warning httpx2 (noti, fix fase 11).
  - Seed E2E fase 09: ~4-6 min totali (2 scan libreria + 2 scan discovery reali).

---

## FASE 08 — UI: feed release + pagina dettaglio — 2026-08-04
- Branch: fase-08-ui-release
- Cosa è stato fatto:
  - **`frontend/src/api/releases.ts`** (nuovo): tipi TS allineati a §10 (`ReleaseListItem` con `rgid` ora presente anche in lista, `ReleaseDetail` con i 4 link, `MatchedArtist`, `ReleasesResponse`) e hook react-query: `useReleases(filters)` (infinite query: pagina successiva se `page*page_size < total`), `useRelease(id)` (404 → ApiError), `useSetReleaseState(id)` (**ottimistico** con `onMutate` set del dato + rollback su errore + invalidate `['release', id]` e `['releases']`), `useSeenAll`. Filtri mappati: type CSV escluso 'all', seen=no se unseenOnly, q.
  - **`frontend/src/components/ReleaseCard.tsx`** (§11.2.2): card = Link a `/releases/{id}`; copertina quadrata `aspect-square` da `/api/v1/covers/{rgid}` (`loading="lazy"`, `onError` → **placeholder surface2 con icona nota SVG**; placeholder diretto se `cover_path` null); titolo `line-clamp-2`; riga artisti con **i tuoi artisti (role primary/featured) evidenziati in accent font-medium** dentro `primary_artist` (parti non-tracked in textDim) + suffisso ` (feat. {nomi})` solo per i featured NON già presenti nella phrase (evita "X feat. Y (feat. Y)"); data ISO come da server (parziali incluse); badge tipo pill surface2 (Album/Single/EP/Other); **pallino accent top-right se !seen** (`aria-label="New"`); hover scale+shadow (dark `shadow-black/40`), `focus-visible:ring-2 ring-accent`.
  - **`frontend/src/components/LinkButtons.tsx`** (§11.2.3): 4 pill — Spotify `bg-accent text-black` (AA, come prescritto), YouTube Music `bg-yt text-light-bg`, Deezer `bg-deezer text-light-bg`, "Search on Google" `bg-surface2 border border-border`; icona SVG inline ciascuna; `target="_blank" rel="noopener noreferrer"`; campo null → `<span aria-disabled>` opacity-50 (niente link).
  - **`frontend/src/pages/Feed.tsx`** (§11.2.2): H1 "New releases"; chip [All|Albums|Singles|EPs] (attivo `bg-accent text-black`, `aria-pressed`); switch "Unseen only" (`role="switch" aria-checked`, `aria-label`); search placeholder "Search…" **debounce 300ms**; "Mark all as seen" (`window.confirm` → `POST seen-all` → invalidate); grid `grid-cols-2 sm:3 md:4 lg:5 xl:6 gap-4`; "Load more" se `hasNextPage` + "N of total" a fine pagine; stati: skeleton ×12 `animate-pulse`, errore + "Retry", empty state con icona + "No new releases" + "Try running a scan from Settings" + link.
  - **`frontend/src/pages/ReleaseDetail.tsx`** (§11.2.3): "← Back to feed"; grid `md:grid-cols-[384px,1fr]`; copertina grande `max-w-[384px] rounded-xl` (o placeholder + `alt={title}`); H1; riga meta: data + badge tipo + secondary_types; blocco "Your artists" con ruolo tradotto (**Main artist / Featuring / Contributor**) in accent; LinkButtons; toggle **Seen** (aria-pressed) / **Favorite** (cuore SVG filled, aria-pressed) / **Hide↔Restore** — tutti `useSetReleaseState` ottimistico; badge "Hidden" se hidden; **404 → "Release not found" + back to feed**; errore generico → Retry; skeleton dedicato.
  - **Backend (cambio minimo, vedi sotto)**: `rgid` aggiunto al list item di `GET /releases` (+ test aggiornato).
  - **`e2e/scenarios/fase-08.js`** (nuovo, come da fase-08 aggiornata): harness con **seed esteso** — oltre a `h.seed` ora `PUT /settings {discovery_from_date:'2024-01-01'}` così il seed produce **87 release reali** (paginazione esercitabile); helper nuovi in harness: `apiPut`, `apiJson`, `clickByText`, `ariaPressedByText`, `setSearch` (React-controlled). Script `e2e:08` in package.json.
- Decisioni prese (e perché):
  - **`text-black` su `bg-accent`** (bottoni Spotify/chip/stati attivi): prescritto da §11.2.3 per contrasto AA su #1DB954 (il nero non è un token §11.1 ma è esplicitamente richiesto dalla spec per questo caso — annotato per la review).
  - **Suffisso feat. deduplicato**: " (feat. {nomi})" aggiunto solo per i matched featured NON già contenuti in `primary_artist` (la phrase MB li include già nei casi "X feat. Y"; aggiungerli sempre produrrebbe doppioni).
  - **Cover senza `rgid`**: il list item non esponeva `rgid` (solo il dettaglio) → la card feed NON poteva costruire `/api/v1/covers/{rgid}` (requisito §11.2.2). Trattato come **bug evidente del backend** (incoerenza interna alla spec: feed richiede copertina, endpoint copertine è per-rgid): aggiunto `"rgid": row.rgid` al list item, test aggiornato (`set(item)` + `item["rgid"] == "rg-2"`). Documentato qui come richiesto dal vincolo "dato mancante → FERMATI e scrivilo in STATO.md".
  - **Stati con `0|1`** nei tipi TS (il backend li serializza come int): coerenti con `_state_filters`; verità convertita con `!!x`.
  - **Skeleton su cambio filtri**: niente `keepPreviousData` → al cambio chip/search il feed mostra skeleton (niente dati stantii); l'infinite query riparte pulita da pagina 1.
- Ambiguità riscontrate (interpretazione scelta):
  - §11.2.2 "riga artisti ... in accent" vs `primary_artist` (phrase unica del server): resi in accent **solo i nomi dei tuoi artisti matched** presenti nella phrase (parti restanti in textDim) — l'highlight della riga intera non era possibile senza spezzare la phrase; il resto della phrase resta leggibile in textDim.
  - "Mark all as seen" con `window.confirm` (spec §11.2.2 dice "conferma window.confirm"): ok; lo scenario E2E auto-accept il dialog.
- Deviazioni dalle specifiche (approvate da chi): il cambio backend `rgid` nel list item (sopra) — unico e minimo, con test.
- Test: backend — suite completa **231 passed** (aggiornato `test_releases_api.py` per `rgid`), ruff OK. Frontend — `tsc --noEmit` e `npm run build` puliti; grep hex in src → 0.
- Esito verifica (E2E automatico `npm run e2e:08`, backend :8094 con seed reale 87 release):
  - **29/29 PASS**: feed card+cover da /api/v1/covers (26/30 con cover), badge e date ISO, pallino "new" su tutte le unseen; chip Singles → 30 card tutte SINGLE (API 69); toggle unseen → card == min(total,30) e pallino su ogni card; search "daft" → 3 card (debounce), stringa inesistente → empty state; **Load more → 60 card senza duplicati**; dettaglio: H1, 4 bottoni con `rel=noopener` e domini §9 esatti, cover locale; favorite → aria-pressed=true **persiste dopo reload**; back → pallino sparito; hide → release assente dal feed; mark-all (confirm) → unseen-only empty; mobile 375px → grid 2 colonne e nessuno scroll orizzontale; **zero errori console (esclusi 401 intenzionali), zero violazioni CSP, zero immagini da domini esterni**.
  - Regressioni: `e2e:07` → **21/21**, `e2e:06` → **23/23** (sullo stesso backend), pytest 231, ruff OK.
- Esito review (modello economico): **eseguita (2026-08-04) — 1 MEDIA, 2 BASSA** (vedi sotto).
  Check: nessun hotlink esterno (F2: img solo da /api/v1/covers, verificato anche via `state.imageHosts`
  nell'E2E), `target=_blank` sempre con `rel="noopener noreferrer"` (LinkButtons), date parziali
  mostrate come sono (§11.3), paginazione senza duplicati (id unici verificati E2E + disabled su
  Load more durante fetch), **race seen-side-effect vs cache react-query → MEDIA trovata e fixata**,
  accessibilità minima (focus-visible ring ovunque, aria-pressed/role=switch/aria-label, alt sensati,
  empty state con link, dot con aria-label), nessun dato inventato oltre §10 (tipi allineati alle
  risposte reali; unico campo aggiunto = `rgid` nel list item, documentato), stringhe UI tutte in
  inglese. Checklist sicurezza: B5 ✅ (nessun dangerouslySetInnerHTML, URL esterni solo dal server),
  F2 ✅.
- **Fix dei findings (post-review, 2026-08-04)** — commit `fix(frontend): phase-08 review findings...`:
  - **MEDIA 1 (toggle Seen non funzionante in direzione off)** — il GET del dettaglio ha il
    side-effect `seen=true` (§10): dopo un un-see esplicito (`POST state seen:false`), il refetch
    dell'invalidate (e ogni re-view) ribaltava `seen` a 1 → la release non poteva restare non vista
    (verificato empiricamente: unsee poi GET → seen=1). Fix in `api/releases.py::get_release`: il
    side-effect marca seen **solo se la release non è già esplicitamente non-vista** (riga stato
    assente → seen=1 come prima; seen=1 → refresh di `seen_at`; seen=0 → rispettata). **Deviazione
    da §10 registrata**: "side-effect seen=true" vale per le release mai viste/esplicitamente viste;
    l'un-see esplicito viene rispettato (necessario per il toggle §11.2.3). Regression test
    `test_api_release_detail_respects_explicit_unsee` + test esistente `..._sets_seen` invariato
    (auto-mark su release senza stato). Suite: **232 passed**.
  - **BASSA 1 (`coverBroken` stantio tra release diverse)** — `ReleaseDetail.tsx`: lo stato
    `coverBroken` non si resettava navigando da `/releases/1` a `/releases/2` (stessa istanza del
    componente): una cover rotta nella prima nascondeva la cover della seconda. Fix: `useEffect`
    che resetta lo stato al cambio di `id`.
  - **BASSA 2 (seenAll senza onError, ACCETTATO)** — `useSeenAll` senza `onError`: un fallimento
    di rete del seen-all è silenzioso (stesso pattern del BASSA 3 fase 07, accettato per app
    single-user; fase 13 copre offline/retry).
  - Re-verifica post-fix: pytest **232 passed**, ruff OK, `tsc --noEmit` + build OK, API reale:
    un-see poi GET → `seen=0` (prima `seen=1`).
- Problemi noti / debito tecnico:
  - Il seed E2E con `discovery_from_date=2024-01-01` richiede rete MusicBrainz e ~3-5 min (87 release + cover): documentato in `e2e/README.md` e nel file di fase.
  - `text-black` su accent (spec-mandato, sopra).
  - Warning httpx2 e `server: uvicorn` noti (fix fase 11).

---

## STRUMENTAZIONE E2E AUTOMATICA + FASE 13 (2026-08-04, fuori fase 07)

- **Harness `e2e/`** (nuovo, committato): puppeteer 25.4.0 pinnato in `e2e/package.json`
  (package-lock committato), `e2e/harness.js` (launch Chrome headless, `check()` PASS/FAIL,
  login UI, POST autenticati con X-Requested-With, poll scan, raccoglitori
  console/CSP/network/immagini-esterne, screenshot su FAIL in `e2e/artifacts/` gitignored),
  `e2e/scenarios/fase-06.js` (link §9 + /covers, solo API via node fetch) e
  `e2e/scenarios/fase-07.js` (login/tema/logout/redirect/CSP). `.gitignore` aggiornato.
  Documentazione in `e2e/README.md`.
- **Deviazione da §3 e da "niente altre dipendenze" (annotata)**: la struttura repo §3 non
  prevede `e2e/` e il vincolo "niente altre dipendenze" vale per `frontend/package.json`
  (che resta pulito). Puppeteer è tooling di verifica separato, installato solo in `e2e/`.
- **Esiti eseguiti (backend con dati/seed reali)**:
  - `npm run e2e:07` (backend :8091, FRONTEND_DIST, DEV_INSECURE_COOKIES=true, DB fresco) →
    **21/21 PASS**: login dark #0F0F0F, "Invalid credentials" inline rosso, redirect / + navbar,
    toggle tema entrambe le direzioni, persistenza light E dark dopo reload, logout, redirect
    senza sessione, zero errori console/CSP/page/network (favicon risolta).
  - `npm run e2e:06` (backend :8092, DB seedato via API: library scan su /tmp/nucs-lib-test +
    discovery con `discovery_from_date=2026-04-01` → 13 release, 13 con 4 link, 11 con cover) →
    **23/23 PASS**: dettaglio con 4 link, dominio §9 esatto, **probe live reali** su
    Spotify/YTM/Deezer/Google tutti 200 (anche l'URL diretto Deezer `album/1020773921`),
    /covers rgid→200, path traversal→404, uuid inesistente→404, senza sessione→401.
- **Fase 13 creata**: `piano/fasi/fase-13-verifica-manuale-completa.md` — checklist manuale
  esaustiva (10 aree A-J, ~90 passi) con happy path E **azioni non convenzionali/avversarie**
  (input limite, doppio click, due tab, cookie manipolati, throttle, offline, adversarial API
  curl, concorrenza, a11y, post-deploy), template dei finding (severità ALTA/MEDIA/BASSA +
  evidenza) e regole di chiusura (zero ALTA/MEDIA aperti senza decisione). Da eseguire
  dall'operatore dopo la fase 12 (o prima come sanity check). Aggiunta all'indice in
  `piano/README.md`.
- **File di fase 07-12 aggiornati**: prerequisiti E2E (`cd e2e && npm ci`, Node ≥ 20, Chrome
  headless al primo run) e prompt di verifica ora riferiti agli scenari automatici
  (`npm run e2e:07` / `e2e:08` / `e2e:09` / `e2e:11` / `e2e:12`); la fase 08/09/11/12 creano
  i propri file di scenario estendendo l'harness (l'UI non esiste ancora → gli scenari nascono
  con la fase); fase 10: tutto automatico tranne la ricezione Apprise su dispositivo esterno
  (umana); fase 12: `piano/verifica-e2e.md` generato dal runner, umani dichiarati = stats 24h,
  README su macchina pulita, ricezione Apprise.

---

## FASE 07 — Frontend base: Vite/React/Tailwind, tema, login, layout — 2026-08-04
- Branch: fase-07-frontend-base
- Cosa è stato fatto:
  - **Scaffolding manuale** `frontend/` (nessun create-vite interattivo): `package.json` con versioni ESATTE — react 18.3.1, react-dom 18.3.1, react-router-dom 6.30.4, @tanstack/react-query 5.101.4, vite 6.4.3, @vitejs/plugin-react 5.2.0, typescript 5.9.3, tailwindcss 3.4.19, postcss 8.5.25, autoprefixer 10.5.4 — + `@types/react` 18.3.31 e `@types/react-dom` 18.3.7 (solo dev, vedi decisioni). `package-lock.json` generato e da committare. Nessuna altra dipendenza. Scripts: dev/build (`tsc --noEmit && vite build`)/preview.
  - `tailwind.config.js`: `darkMode:'class'`, content `./src/**/*.{ts,tsx}` + `index.html`, `theme.extend.colors` = **tokens §11.1 esatti** (accent #1DB954, accentHover #1ED760, accentActive #169C46, danger #E5484D, yt #FF0000, deezer #A238FF, dark./light. {bg,surface,surface2,border,text,textDim}), borderRadius ereditato, fontFamily stack §11.1. `postcss.config.js` (tailwindcss + autoprefixer).
  - `src/theme.ts`: `getStoredTheme()`/`getInitialTheme()` (localStorage `nucs-theme`, default `dark`) e `applyTheme(t)` (toggle classe `dark` su `documentElement` + localStorage). Chiamata **subito in `main.tsx`** a livello modulo (anti-flash, CSP-safe: niente inline script) e poi sincronizzata in `RequireAuth`: `theme` da `/auth/me` **vince** se diverso da locale e aggiorna localStorage (come da prompt).
  - `src/api/client.ts`: `apiFetch<T>` wrapper — base `''` same-origin, `credentials:'same-origin'`, header `Content-Type: application/json` + `X-Requested-With: XMLHttpRequest` (spec §5.4); su **401 → `window.location.assign('/login')`**; 204 → undefined; parse JSON sicuro (corpo non-JSON → null); `ApiError{status}` con `detail` dal body quando stringa; helper `get`/`post`.
  - `src/App.tsx`: router — `/login` pubblica; `RequireAuth` (GET `/api/v1/auth/me` via react-query, loading → **spinner centrato** `animate-spin` accent, errore → `<Navigate to="/login">`) + `Navbar`; rotte protette `/` (Feed), `/releases/:id` (ReleaseDetail), `/artists`, `/settings`; wildcard → `/`. Stub = H1 inglese + "Under construction" (nessuna logica feed/dettaglio/impostazioni, fasi 08-09).
  - `src/pages/Login.tsx` (§11.2.1): centrata, emoji 🎵 + "nucs", card `surface` `rounded-2xl` con ombra dark `shadow-black/40`, input Username/Password (label, `autocomplete="username"/"current-password"`, focus `ring-2 ring-accent`), bottone pill accent "Log in" (hover accentHover, active accentActive), errore inline `text-danger`: 401 → **"Invalid credentials"**, altri errori → **"Something went wrong. Try again."**; su 204 → `invalidateQueries(['me'])` + navigate `/`. Nessun hack password manager.
  - `src/components/Navbar.tsx`: logo testuale "nucs", `NavLink` Feed/Artists/Settings con stato attivo `text-accent`, **toggle tema con icone sole/luna SVG inline** (`aria-label="Toggle theme"`), bottone "Log out" (POST logout → `queryClient.clear()` + `/login`). **Mobile <640px: navbar compatta — icone SVG inline al posto del testo nascosto con `hidden sm:inline`**; nessuna emoji (vincolo "niente emoji oltre 🎵 login").
  - **Integrazione backend**: `backend/app/config.py` nuova setting `frontend_dist` (env `FRONTEND_DIST`, default `"../frontend/dist"`); `backend/app/main.py` — dopo i router `/api` e `/api/health`: risolve FRONTEND_DIST (relativo rispetto a `backend/`), se è una directory `app.mount("/", StaticFiles(html=True))` (log INFO/WARNING); nuovo `exception_handler(StarletteHTTPException)` che fa da **SPA fallback**: GET non-`/api` con 404 → `index.html` (200), tutto il resto (inclusi tutti i 404/403/401/429 sotto `/api`) → JSON `{"detail": ...}` con **headers preservati** (Retry-After incluso — prima versione li perdeva, trovato dai test 429). `/api/health` non toccato.
  - `vite.config.ts`: plugin react, `server.proxy '/api' → http://127.0.0.1:8080` (**senza changeOrigin**, vedi decisioni), `build.outDir 'dist'`. `tsconfig.json` strict + `types: ["vite/client"]`, `index.html` senza inline script (CSP `script-src 'self'`).
- Versioni dipendenze introdotte: tutte pinnate `==` (lista sopra); Node locale v22.23.1 (il Dockerfile userà node:20-alpine in fase 11 — vite 6.4.3 supporta `^18||^20||>=22`, typescript 5.9.3 e le altre funzionano su Node 20).
- Decisioni prese (e perché):
  - **`@types/react`/`@types/react-dom` aggiunti**: `npx tsc --noEmit` senza fallire richiede i tipi (modulo 'react' senza dichiarazioni); sono package **solo dev di tipi**, parte standard del template Vite react-ts; nessuna dipendenza runtime aggiunta. Pinnati 18.3.31/18.3.7 (allineati a React 18).
  - **Login NON usa il wrapper con redirect su 401**: una 401 sulla POST login deve mostrare "Invalid credentials" inline, non fare reload/redirect; `Login.tsx` fa una fetch raw con gli stessi header §5.4 (X-Requested-With + Content-Type) e gestisce 204/401/altro esplicitamente.
  - **Header `X-Requested-With`/`Content-Type` inviati anche sulle GET** dal wrapper: innocuo (il backend li esige solo sulle mutazioni) e mantiene il wrapper unico.
  - **Proxy senza `changeOrigin`**: con changeOrigin vite riscriveva `Host` a `127.0.0.1:8080` lasciando `Origin: localhost:5173` → il CSRF check backend (§5.4) rispondeva 403 al login in dev (verificato live). Senza changeOrigin Host e Origin combaciano e il cookie `nucs_session` (senza Domain) viene assegnato dal browser a `localhost` (i cookie ignorano la porta) → login da :5173 funziona.
  - **Navbar mobile con icone SVG inline** (home/artists/settings come path stroke) invece di emoji: vincolo "niente emoji oltre 🎵 login" (il mockup non esiste, vedi sotto).
  - **FRONTEND_DIST relativo a `backend/`**: default `../frontend/dist` → `/repo/frontend/dist`; path assoluti (es. `/app/static` del Dockerfile fase 11) usati come sono.
  - **Tema: vince il server** (settings.theme da `/auth/me`) se diverso dal locale, e aggiorna localStorage (prompt task 3); il toggle navbar aggiorna solo il locale finché la PUT /settings arriverà in fase 09.
  - **Typescript 5.9.3** (linea 5.x stabile; la 7.0.2 "latest" è la nuova toolchain, non ancora adottata per evitare sorprese con il template).
- Ambiguità riscontrate (interpretazione scelta):
  - **Mockup in `piano/mockup/` non esistono** (solo `piano/mockup-opendesign.md` senza output generati): riferimento visivo = specifica §11 (layout/voci indicati nel prompt e riprodotti).
  - `data.theme` da `/auth/me` arriva come `'dark'|'light'` (settings `theme` stringa): tipato in `Me` e allineato a `Theme` di theme.ts.
  - 404 non-`/api` senza dist presente (dev senza build): ritorna JSON 404 invece di HTML (accettabile, il dev server Vite copre il caso normale).
- Deviazioni dalle specifiche (approvate da chi): **@types dev-dependencies** (sopra, necessarie al typecheck §13; nessuna dipendenza runtime extra).
- Test: frontend — `npx tsc --noEmit` pulito e `npm run build` ok (ripetuti da `npm ci` fresco, lock committato); `grep -rn "#[0-9a-fA-F]\{3,8\}"` su src/index.html/vite.config.ts/package.json → **zero risultati** (hex solo in tailwind.config.js, 18 token). Backend — **231 passed** (nessuna regressione dalla modifica a main.py; 3 test 429 falliti alla prima versione dell'exception handler perché perdeva `Retry-After`, fixato), ruff check + format OK.
- Esito verifica (comandi eseguiti e risultato):
  - `cd frontend && npm ci && npx tsc --noEmit && npm run build` → exit 0; `dist/` con index.html + assets (js 219 kB / gzip 69.6 kB, css 10.9 kB).
  - Backend integrato (`DATA_DIR=/tmp/nucs-d7 FRONTEND_DIST=../frontend/dist ADMIN_USERNAME=admin ADMIN_PASSWORD=test-password-lunga-1 uvicorn :18099`): `/` → HTML con `<div id="root">`; `/qualcosa/di/spa` → stesso index.html (fallback SPA); `/api/health` → `{"status":"ok","version":"1.0.0"}`; `/api/v1/auth/me` senza cookie → **401**; asset `/assets/index-*.js` → 200 `text/javascript`; header `Content-Security-Policy` presente su `/`; `/api/v1/nessuna` → 404 JSON (non index.html); asset inesistente → fallback SPA (nessun 404 rotto).
  - **Flusso login E2E (curl)**: POST login con X-Requested-With+Origin → **204 + Set-Cookie nucs_session (HttpOnly, Secure, SameSite=Lax, Max-Age)**; login senza X-Requested-With → **403**; `/me` con cookie → `{"username":"admin","theme":"dark"}`; logout → 204; `/me` dopo logout → 401.
  - **Dev-mode**: uvicorn :8080 + `npm run dev` → `/` da :5173 ok; proxy `/api/health` → JSON; **login da :5173 → 204** e `/me` → 200 (senza changeOrigin, vedi decisioni).
  - Verifica visiva browser (bg #0F0F0F, card #181818, bottone #1DB954, toggle tema persistente al reload): **non eseguibile in questo ambiente** (no browser) — da confermare manualmente in fase 08/12; le classi corrispondono ai token verificati via build CSS (10.9 kB con le utilities generate).
- Esito review (modello economico): **eseguita (2026-08-04) — 0 ALTA, 0 MEDIA, 3 BASSA** (vedi sotto).
  Check: X-Requested-With su tutte le mutazioni (apiFetch + fetch raw login), 401 handling senza
  loop di redirect (assign una tantum + Navigate; nessuna query attiva su /login), catch-all SPA
  che non inghiotte /api (JSON 404 sotto /api, /api/health ok, verificato anche `/apix` dopo fix),
  zero `dangerouslySetInnerHTML`, zero hex fuori token, anti-flash a livello modulo in main.tsx
  (prima del render, CSP-safe), package-lock committati (frontend + e2e), `npm ls` senza
  dipendenze extra, versioni pinnate (incl. @types 18.x). Checklist sicurezza: B5/B6/B7/C1/C2/E1/E2/F1 ✅
  (nota C1: la password default di `e2e/` è un fixture di test documentato, mai usato in runtime).
- **Fix dei findings BASSA (post-review, 2026-08-04)** — commit `fix(frontend): phase-07 review findings`:
  - **BASSA 1 (colore fuori token)** — `pages/Login.tsx`: bottone login `text-white` → `text-light-bg`
    (stesso #FFFFFF ma token §11.1); unico colore named non-token della fase.
  - **BASSA 2 (edge fallback SPA)** — `main.py`: `path.startswith("/api")` troppo largo (un path
    tipo `/apix` riceveva JSON 404 invece del fallback SPA) → ora `path == "/api" or path.startswith("/api/")`;
    verificato: `/apix` → index.html, `/api` e `/api/nessuna` → JSON 404.
  - **BASSA 3 (mutation senza onError, ACCETTATO con motivazione)** — `Navbar.tsx`: `logout`/`saveTheme`
    senza `onError` → un fallimento di rete del logout riabilita solo il bottone (nessun messaggio) e una
    PUT theme fallita lascia il tema locale attivo finché il server non vince al reload. Non corretto:
    comportamento accettabile e documentato per app single-user; nessun unhandled rejection (react-query
    assorbe l'errore); la fase 13 ha la voce manuale dedicata (offline/retry).
  - Re-verifica post-fix: pytest **231 passed**, ruff OK, `tsc --noEmit` + build OK, `e2e:07` **21/21 PASS**,
    curl su `/`, `/qualcosa/di/spa`, `/api/health`, `/api`, `/apix` coerenti.
- **Fix post-verifica browser (2026-08-04, trovati dal testing manuale dell'utente)** — commit `fix(frontend): theme toggle...`:
  - **BUG toggle tema (non tornava scuro)**: `Navbar` calcolava il tema successivo dal prop `theme` (la settings server, sempre `dark`) invece che dal tema effettivo → il secondo click ri-applicava `light`. Fix: stato locale `useState(() => getStoredTheme() ?? theme)` + `useEffect` di sync quando cambia il prop server; l'icona riflette il tema reale.
  - **Persistenza del tema al reload**: §11.1 vuole il toggle "persistito in settings (via API)". Aggiunto `saveTheme` mutation → `PUT /api/v1/settings {theme}` (endpoint esistente fase 06) + `invalidateQueries(['me'])`; la sincronizzazione server-wins di RequireAuth ora resta coerente (al reload il server restituisce il tema scelto dall'utente, non più `dark` fisso). Il toggle funziona in entrambe le direzioni e persiste al reload.
  - **Favicon 404** (`GET /favicon.ico` in console): aggiunto `<link rel="icon" href="data:," />` in index.html (nessuna dipendenza, CSP-safe).
  - **Nota dev importantissima (non è un bug)**: su `http://` il cookie di sessione `Secure` viene salvato ma **mai rinviato** dal browser → login "invisibilmente rotto" (204 + cookie scartato → `/me` 401 → bounce su /login). In dev locale serve `DEV_INSECURE_COOKIES=true` (§5.2, flag previsto apposta). Aggiornati i comandi dev sotto.
  - **Verifica browser reale (puppeteer + Chrome headless in cartella temporanea, fuori dal repo — zero dipendenze aggiunte)**: **21/21 PASS** — login page dark (#0F0F0F verificato su computed style), "Invalid credentials" inline rosso #E5484D senza redirect, login corretto → `/` con navbar completa, toggle sole→chiaro→scuro in entrambe le direzioni (bg #FFFFFF / #0F0F0F), tema chiaro E scuro persistenti dopo reload, logout → /login, `/` senza sessione → redirect /login, **zero violazioni CSP**, zero errori script, zero richieste fallite (favicon risolta). I soli 401 in console sono i flussi intenzionali (password errata, `/me` post-logout).
- Problemi noti / debito tecnico:
  - Niente mockup (assenti); il toggle tema non persiste ancora lato server (fase 09: PUT /settings + sincronizzazione già predisposta).
  - `server: uvicorn` visibile in dev (fix fase 11) e warning httpx2 noti da fasi precedenti.
  - `.gitkeep` in frontend/src/{pages,components,api} restano (inerti, ora con file reali accanto).
- Istruzioni avvio dev (fase 07):
  ```bash
  # backend (da backend/) — DEV_INSECURE_COOKIES=true è OBBLIGATORIO su http:// locale
  DATA_DIR=/tmp/nucs-d7b DEV_INSECURE_COOKIES=true ADMIN_USERNAME=admin \
    ADMIN_PASSWORD='password-lunga-12' .venv/bin/uvicorn app.main:app --reload --port 8080
  # frontend (da frontend/, dopo npm ci)
  npm run dev                                     # http://localhost:5173 (proxy /api → :8080)
  # build statica servita dal backend: FRONTEND_DIST=../frontend/dist + npm run build
  ```

---

## FASE 06 — Link esterni (Spotify/YTM/Deezer/Google) e cache copertine — 2026-08-04
- Branch: fase-06-link-e-cover
- Cosa è stato fatto:
  - `backend/app/services/links.py` (nuovo, PURO): `build_search_links(primary_artist, title, type)` → `{spotify_search, ytm, deezer_search, google}` con gli URL ESATTI di §9 e `urllib.parse.quote(safe='')` (spazi→%20, &→%26); la query Google include il type (§9). Nessun I/O.
  - `backend/app/services/deezer.py` (nuovo): `resolve_album(artist, title)` → `GET https://api.deezer.com/search/album?q=artist:"{a}" album:"{t}"&limit=1` (httpx condiviso, timeout 10s, retry tenacity x3 su 429/5xx/transport); hit solo se `normalize_name(title)` == `normalize_name(title risposta)`; ritorna `(deezer_url_diretto, cover_xl)` o `(None, None)`; **rate limit gentile 2 req/s** (token bucket 0.5s, condiviso); `download(url)` per le cover (stesso limiter); `close_client()`/`reset_for_tests()`. Nessuna chiave.
  - `backend/app/services/spotify.py` (nuovo, OPZIONALE): client credentials con token cached in memoria + scadenza (margine 60s), base `https://api.spotify.com/v1`, POST token su `accounts.spotify.com`; `resolve_album(db, artist, title)` → search `artist:X album:Y` type=album limit=5 → match normalizzato → `https://open.spotify.com/album/{id}`; **rate limit 5 req/s** (0.2s); credenziali assenti o errore auth → **modulo inerte**: log INFO **una tantum**, nessuna eccezione; `invalidate_token()` chiamata dal PUT /settings quando cambiano le credenziali; `close_client()`/`reset_for_tests()`.
  - `backend/app/services/musicbrainz.py`: nuovo `get_cover_art_front(rgid, size=500)` su `https://coverartarchive.org/release-group/{rgid}/front-{size}` con **lo stesso rate limiter globale 1 req/s e la stessa retry policy** (§7); `_request` ora usa `follow_redirects=True` (CAA risponde 302 verso archive.org); 404 → `HTTPStatusError` immediato (segnale "nessuna cover" per il fallback).
  - `backend/app/services/covers.py` (nuovo): `fetch_cover(db, release)` nell'ordine §8.4: a) CAA front-500 via il client MB condiviso; b) `deezer.resolve_album` → `cover_xl`; c) altrimenti `cover_path` resta NULL (placeholder nel frontend). Salvataggio in `COVERS_DIR/{rgid}.jpg` **atomico** (tmp con pid + `os.replace`), validazione `content-type image/*` e dimensione < 5 MB (header Content-Length + body), altrimenti scartata (e si passa al fallback successivo). Aggiorna `releases.cover_url` (URL sorgente) e `cover_path` (nome file). `RGID_RE` strict `^[a-f0-9]{8}-...-{12}$` + `valid_rgid` usati anche dall'endpoint (B3): il nome file esiste solo da rgid validato. **Return value documentato**: `fetch_cover` ritorna l'URL Deezer diretto quando Deezer ha risolto (anche se la cover non è stata salvata) così la pipeline di link riusa la STESSA chiamata Deezer (mai due search per release).
  - **Pipeline §8.4** in `backend/app/services/discovery.py`: i rgid delle release NUOVE vengono raccolti durante l'upsert (`new_rgids` list threadata in `_process_release_group`/`_level1*`/`_level2*`; le release già esistenti NON vengono mai ri-arricchite) e, dopo i livelli, processati da `_enrich_new_releases` con **concurrency limitata a 2** (`asyncio.Semaphore(2)`), ogni release in un task con sessione propria; `_enrich_release` (per-release try/except + `pipeline_errors`, mai fa fallire il run): cover (con riuso del risultato Deezer) + 4 link (`spotify_url` diretto o search, `ytm_url`, `deezer_url` diretto o search, `google_url`); i rate limiter di ciascun servizio restano rispettati (il cap 2 limita solo i download in volo). Stats aggiunte: `covers_fetched`, `links_resolved` (numero di colonne link valorizzate: 4 per release processata), `pipeline_errors`. Cancellation graceful: `CancelledError` propagata → run status=error (come fase 05).
  - **Backfill**: `backfill_links_covers(db, limit=200)` in discovery.py — seleziona le release incomplete (una qualsiasi colonna cover/link NULL) ordinate per id, limit; esegue la stessa pipeline via `asyncio.run`; CLI `python -m app.cli backfill-links [--limit N]` (stampa covers_fetched/links_resolved/errors).
  - `backend/app/api/covers.py` (nuovo, `require_user`): `GET /api/v1/covers/{rgid}` → rgid non conforme a `RGID_RE` → **400** `{"detail":"Invalid release group id"}`; file assente → 404; altrimenti `FileResponse` con `media_type="image/jpeg"` e `Cache-Control: public, max-age=604800` (§10).
  - `backend/app/api/settings.py` (nuovo, COMPLETO — non esisteva): `GET /settings` → tutte le chiavi whitelisted NON segrete + flag `spotify_client_id_set`/`spotify_client_secret_set` (i segreti Spotify **mai** restituiti, §5.8); `PUT /settings` → solo le 12 chiavi whitelisted del prompt (sconosciute → 422), validazioni: `discovery_from_date` ISO `YYYY-MM-DD` reale, `scan_*_time` HH:MM 24h strict, `feat_scan_weekday` in mon..sun, `feat_scan_enabled`/`notify_enabled` booleani (accetta anche bool JSON → `"true"/"false"`), `theme` dark|light, `release_types` CSV ⊆ album,single,ep,other (dedup), `notify_urls` con scheme `scheme://` per ogni riga e **non vuoto se notify_enabled** (cross-field), `mb_contact_email` email valida o vuota, credenziali Spotify max 256 char; audit `settings_change` con **solo i nomi delle chiavi** (mai valori); su cambio credenziali Spotify → `spotify.invalidate_token()`.
  - `main.py`: router settings + covers registrati; shutdown chiude anche `deezer.close_client()` e `spotify.close_client()`. `cli.py`: comando `backfill-links`.
  - Release API (fase 05) già conforme: lista include `cover_path`, dettaglio include `cover_path` + `cover_url` + i 4 link (nessuna modifica necessaria).
- Decisioni prese (e perché):
  - **`fetch_cover` ritorna l'URL Deezer** (quando Deezer risolve) come segnale di riuso per il link Deezer: con CAA in cache la pipeline fa 1 sola chiamata Deezer per release invece di 2 (il rate limit non è mai superato, si risparmia latenza).
  - **`links_resolved` = numero di colonne link valorizzate** (sempre 4 dopo l'arricchimento, perché i link search sono sempre presenti per §9 "Google fallback: sempre presente"): è il contatore più semplice coerente con il nome; documentato qui.
  - **Rilettura dei coverless a ogni backfill**: una release senza cover su CAA/Deezer viene ritentata a ogni `backfill-links` (bounded da limit); comportamento voluto (il backfill è manuale), annotato qui.
  - **Spotify inerte senza credenziali** (log INFO una tantum per processo, resettato da `invalidate_token`/reset): nessun errore, nessuna eccezione (spec 8.3).
  - **File sempre `{rgid}.jpg`** anche se i byte sono PNG (spec: "Salva in COVERS_DIR/{rgid}.jpg"); servito come `image/jpeg`. Il validatore accetta qualsiasi `image/*` (CAA serve JPEG/PNG). Rischio noto minimo con `nosniff` (documentato sotto): il 99% delle cover CAA sono JPEG.
  - `PUT /settings` accetta valori `str | bool` e normalizza i booleani in stringhe (la UI potrà mandare checkbox booleani); risposta = stesso body del GET (mai segreti).
- Ambiguità riscontrate (interpretazione scelta):
  - §10 "flag `*_set` per le segrete": il prompt chiede esplicitamente solo `spotify_client_secret_set`, ma il client id è anch'esso write-only (mai restituito) → esposto **anche** `spotify_client_id_set` (la verifica del prompt resta soddisfatta).
  - La query Deezer con virgolette nel nome artista/titolo viene escaped (`\"`) come la search MB di fase 04 (nessuna rottura di sintassi Lucene).
  - Il regex rgid strict usa la forma UUID con trattini (`8-4-4-4-12`), sottoinsieme di `[a-f0-9-]{36}` del prompt: rifiuta anche `36` caratteri hex senza trattini (test dedicato).
- Deviazioni dalle specifiche (approvate da chi): nessuna.
- Test (nuovi): `test_links.py` (8), `test_covers.py` (18: deezer hit/miss/network-error, query esatta via stub transport, rate limit 2/s con sleep mockato, pipeline CAA 404→Deezer, CAA ok senza toccare Deezer, entrambe mancanti → cover NULL, content-type errato scartata, troppo grande scartata, rgid invalido mai scrive file, endpoint 401/400/404/200+cache header, regex), `test_spotify.py` (8: inerte senza credenziali senza alcuna chiamata, hit con Bearer token e query esatta, match normalizzato, miss, token cached (1 sola POST), auth error → inerte una tantum, invalidate_token, rate limit 5/s), `test_settings_api.py` (15: auth, GET non-segreti+flag, PUT segreto write-only, PUT whitelist, chiave sconosciuta, date/times/weekday/boolean/theme/release_types/email invalidi → 422, notify senza url → 422, url senza scheme → 422, notify disabilitato con url ok, audit senza valori, invalidate token cache) e 10 test pipeline in `test_discovery.py` (enrich con cover+link e stats, riuso risultato Deezer (zero doppie chiamate), failure isolata per-release con run ok, release esistenti mai ri-arricchite, concurrency ≤ 2, backfill selettivo/limit/CLI). **Fixtures**: l'autouse `_no_real_musicbrainz` ora sostituisce anche `discovery.fetch_cover` con no-op e `discovery.deezer`/`discovery.spotify` con stand-in inerti (le chiamate dirette a `deezer.resolve_album` nei test dedicati restano possibili perché il modulo reale non è toccato); `conftest._reset_state` resetta anche deezer/spotify.
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/ruff check .` + `ruff format --check .` → OK; anche invocazione CI da root (`backend/.venv/bin/ruff check backend/ --config backend/pyproject.toml`) → OK.
  - `cd backend && .venv/bin/python -m pytest -q` → **224 passed** (erano 167; +57 nuovi) in ~19s, 1 warning noto (httpx2). Coverage TOTAL **94%** (target ≥70%): `services/links.py` 100%, `services/covers.py` 92%, `services/deezer.py` 87%, `services/spotify.py` 94%, `services/discovery.py` 92%, `api/settings.py` 98%, `api/covers.py` (in api/…, nel totale).
  - **Reale (rete) backfill su DB fase 05** (`/tmp/nucs-f05/data/app.db`, 10 release reali): `python -m app.cli backfill-links --limit 10` → **covers_fetched=8 links_resolved=40 errors=0** in ~12s (rate limit 1 req/s rispettato). `SELECT COUNT(*) WHERE cover_path IS NOT NULL` → 8; i 4 link valorizzati su tutte le release (es. Beyoncé "MORNING DEW (DONK)" → `spotify_url` search con `%C3%A9`/`%28DONK%29`, `deezer_url` **diretta** `https://www.deezer.com/album/1020773921`); `file` su ogni cover → JPEG 500x500 valido, tutte < 5 MB.
  - **API reale** (uvicorn 8110 sul DB f05): `GET /api/v1/releases/1` → cover_path + 4 link presenti; `GET /api/v1/covers/{rgid}` → **200** `content-type: image/jpeg` + `cache-control: public, max-age=604800`, byte identici al file cache; rgid invalido → **400**; `..%2F..%2Fetc%2Fpasswd` → **404** (mai 200); uuid inesistente → 404; senza cookie → 401.
  - **Settings reali**: PUT `{"spotify_client_id":"cid-x","spotify_client_secret":"secret-x"}` → 200 con flag `*_set=true`; GET → `secret-x` **assente** dal body; data `2024-13-01` → 422; chiave sconosciuta → 422 `Unknown setting(s): evil_key`; `notify_enabled:true` senza urls → 422; audit_log: `{"keys": ["spotify_client_id", "spotify_client_secret"]}` (mai valori).
  - **E2E pipeline reale** (DB fresco `/tmp/nucs-f06-e2e`, 13 artisti matchati via API): `POST /scans/releases` con `discovery_from_date=2026-03-01` → run ok: `releases_new 14, api_calls 11, covers_fetched 12, links_resolved 56 (=14×4), pipeline_errors 0, duration_s 37.7`; 12 file .jpg validi su disco; dedup confermato (seconda run → releases_new 0 e stats con le nuove chiavi).
- Esito review (modello economico): **eseguita (2026-08-04) — 0 ALTA, 0 MEDIA, 6 BASSA risolti** (vedi sotto). Check: B3/B5/C3/C4/F2 ✅; URL §9 esatti verificati su URL reali; rate limit MB/CAA 1 req/s, Deezer 2 req/s, Spotify 5 req/s tutti testati con sleep mockato + E2E reale; scrittura cover atomica; failure per-release isolate; nessuna regressione su /releases.
- **Fix dei findings BASSA (post-review, 2026-08-04)**:
  - **BASSA 1 (body illimitato prima del cap 5 MB)** — `services/covers.py`: `_size_ok` sostituita da `_read_limited(response)` che streamma il body con cap duro (Content-Length check prima di leggere; senza header, contatore su `aiter_bytes`, abort ≥ 5 MB con `aclose()`). Regression test: body > 5 MB senza Content-Length → scartata, nessun file né tmp.
  - **BASSA 2 (campi risposta Deezer non validati)** — `services/deezer.py`: `album_id` deve essere numerico (`str(id).isdigit()`, gestisce sia int che str) altrimenti `(None, None)`; `cover_xl` non-https → cover scartata (l'URL album resta). Verificato live: id `../../etc/passwd` + cover http → `(None, None)`.
  - **BASSA 3 (cache token Spotify a metà)** — `services/spotify.py::_fetch_token`: `expires_at` calcolata PRIMA di assegnare `_token`/`_token_expires_at`; un `ValueError` su `expires_in` non lascia più stato parziale. Regression test con `expires_in: "garbage"` → `_token is None`.
  - **BASSA 4 (lunghezze illimitate in PUT /settings)** — `api/settings.py`: cap `notify_urls` ≤ 4000, `mb_contact_email` ≤ 254, `release_types` ≤ 100; payload con più chiavi della whitelist (12) → 422 "Too many settings in request" (blocca anche error-detail giganti). Test dedicati.
  - **BASSA 5 (audit settings senza IP)** — `api/settings.py`: `update_settings` usa `Depends(get_client_ip)` e `log_event(..., client_ip, ...)` come gli eventi auth (F3).
  - **BASSA 6 (follow_redirects globale)** — `services/musicbrainz.py::_request`: parametro per-call `follow_redirects` (default False); attivo solo su `get_cover_art_front` (CAA→archive.org). Test del client reale con stub transport: 302 seguito dentro UNA chiamata rate-limited, 404 → `HTTPStatusError` immediato, UA su entrambe le richieste fisiche.
  - Suite post-fix: **231 passed** (erano 224; +7 test di regressione), coverage TOTAL **94%**, ruff OK.
- Problemi noti / debito tecnico:
  - Cover PNG salvate con estensione `.jpg` e servite come `image/jpeg` (scelta spec-driven, sopra): con `X-Content-Type-Options: nosniff` un rarissimo PNG servito come jpeg potrebbe non renderizzare in browser molto severi — accettato (la stragrande maggioranza delle cover sono JPEG; alternativa valutata — salvare con estensione reale — devierebbe dal formato esatto `{rgid}.jpg` del prompt).
  - Backfill ritenta le release senza cover a ogni invocazione (bounded da `--limit`; documentato sopra).
  - Spotify attivo solo con credenziali; senza credenziali il feed avrà sempre link di ricerca Spotify (come da §8.3).
  - Server `:8110`/`:8111` di verifica arrestati; DB di verifica in `/tmp/nucs-f05` e `/tmp/nucs-f06-e2e` (fase 05/06).
  - Warning httpx2 e `server: uvicorn` (noti, fix in fase 11).

---

## FASE 05 — Motore di discovery release (proprie + featuring) e API release — 2026-08-03
- Branch: fase-05-discovery-release
- Cosa è stato fatto:
  - `backend/app/services/dates.py` (nuovo): `parse_mb_date(s)` → `(start, end)` per §7 — date MB parziali allargate al primo/ultimo giorno possibile (`2024` → `2024-01-01`/`2024-12-31`, `2024-05` → primo/ultimo del mese con `calendar.monthrange`, anno esattamente 4 cifre, input invalidi → None); `release_in_range(mb_date, from_date)` → intersezione intervallo release ∩ `[from, oggi]`.
  - `backend/app/services/musicbrainz.py`: nuovi metodi sul client con lo stesso galateo §7 (rate limit globale, UA, retry): `search_release_groups(mbid, from_date, limit=100, offset=0)` con la query ESATTA §8.1 (`arid:{mbid} AND firstreleasedate:[{from} TO *]`); `browse_artist_recordings`; `get_recording_with_releases(recording_mbid)` (lookup con `inc=releases`); `get_release(release_id)` (lookup con `inc=release-groups`); `get_release_group(rgid)` (lookup con `inc=artist-credits`).
  - `backend/app/services/discovery.py` (nuovo): `run_discovery(db, feat_scan=False)` → stats; **LIVELLO 1** (§8.1): per ogni artista `ignored=0 AND mbid NOT NULL`, `from` = max(`discovery_from_date`, ultimo giorno possibile di `last_release_check` − 7 gg), paginazione completa (offset += 100 finché < count), filtro tipo (`Album/Single/EP` → `album|single|ep`, altro → `other`, incluso solo se in `release_types`), filtro data client-side (`release_in_range`, esclude le date future che "TO *" della query MB farebbe passare), **skip senza data** (§8.5: log + `skipped_no_date`), upsert per `rgid` che aggiorna **solo i campi vuoti** e non tocca MAI `cover_*`/`spotify_url`/`deezer_url`/`ytm_url`/`google_url`/`discovered_at` (fase 06), ruolo §8.1 (`primary` se la artist-credit-phrase inizia col nome artista, altrimenti `featured`), `release_artists` inserita se assente (ON CONFLICT DO NOTHING atomico), cursore `last_release_check` = max stringa delle date viste. **LIVELLO 2** (§8.2, solo `feat_scan=True` E settings `feat_scan_enabled=true`): browse recording paginato; per recording non in `seen_recordings` (nuova tabella): lookup recording → release → gruppo incorporato → filtro data/tipo come sopra → upsert con role `featured`; recording marcata seen solo a lavoro completato (fallimento → ritentata la settimana dopo); **cap 2000 recording/artista** con log (limite documentato sotto); progressi loggati ogni 10 pagine (INFO). `scan_runs` (type `releases`/`feat`) con stats complete `{artists_processed, release_groups_found, releases_new, releases_updated, skipped_no_date, skipped_type, api_calls, duration_s, (+feat) recordings_pages}` + audit `scan_run`; su eccezione fatale status `error`; su `MBError` l'artista corrente è saltato e il batch continua (come fase 04). Lock asyncio per tipo (`start_releases_scan`/`start_feat_scan`/`running_scans`/`reset_state`), worker con sessione propria, lock rilasciato anche su eccezione.
  - `backend/app/models.py` + migration Alembic `d3a09182f69b` (catena da `f78ca2bec293`): tabella `seen_recordings(recording_mbid TEXT PK, artist_id INT, first_seen TEXT)`.
  - `backend/app/api/releases.py` (nuovo, protetto da `require_user`), esattamente §10: `GET /releases` con filtri `from`/`to` (ISO, parziali accettate), `type` CSV (validato vs album/single/ep/other), `artist_id`, `seen` (default all), `favorite`, `hidden` (default no → hidden=0), `q` (max 200, ILIKE con escape `\`/`%`/`_` su title/primary_artist), sort `date_desc`/`date_asc` con **date vuote/NULL sempre in fondo** (`nullif("")` + `nulls_last`), paginazione §10; item con `matched_artists:[{id,name,role}]` caricati **con una sola query per pagina** (no N+1); `GET /releases/{id}` dettaglio completo + side-effect `seen=true, seen_at=now` (documentato, accettato in fase 02), 404 `{"detail":"Not found"}`; `POST /releases/{id}/state` merge parziale (crea la riga state se assente, `seen_at=now` su seen=true, `seen_at=None` su seen=false); `POST /releases/seen-all` con range opzionale → marca viste solo le non-hidden non-ancora-viste → `{"updated": n}`. Schema `ReleaseStatePatch` (extra=forbid) e `SeenAllRequest` (alias `from`) in `schemas.py`.
  - `backend/app/api/scans.py`: `POST /scans/releases` e `POST /scans/feat` (stesso pattern lock/409; feat → **400** se `feat_scan_enabled=false`); `GET /scans/status` ora fonde gli scan in corso di library + discovery. Router releases registrato in `main.py`; `conftest.py` resetta anche lo stato del discovery.
- Ambiguità riscontrate (interpretazione scelta, come richiesto dal prompt):
  - **`inc=releases` NON è un parametro valido sul browse recording** (verificato contro l'API reale: `400 "releases is not a valid inc parameter for the recording resource"`). Implementazione: browse senza `inc`; le release di ogni recording arrivano dal lookup `GET /recording/{id}?inc=releases`; il release-group di ogni release arriva da `GET /release/{id}?inc=release-groups` che lo incorpora già completo (id, primary-type, secondary-types, first-release-date) → una sola chiamata per release invece di due (interpretazione "più semplice conforme al testo": "get_release_group della release" = ottenere il gruppo della release; `get_release_group(rgid)` resta disponibile sul client con test).
  - **`artist-credit-phrase` non è mai restituito** dalle API MB (search e lookup, verificato a runtime): la frase è ricostruita esattamente come MB la compone concatenando `name` + `joinphrase` della lista `artist-credit` (usata sia per `primary_artist` sia per l'euristica ruolo).
  - **Il count del browse recording è `recording-count`** (non `count`, usato dalla search): il paginatore livello 2 legge `recording-count` (fallback `count`).
  - **Cursore con data parziale**: `last_release_check` è salvato come restituito da MB (formato parziale compreso — il confronto stringa è cronologico perché zero-padded); il `from` della run successiva usa **l'ultimo giorno possibile** della data parziale meno 7 giorni (mai si perdono release per il trim). Nota: MB indicizza le date parziali al primo giorno (`2026` → `2026-01-01`), quindi con cursori molto avanti una release parziale può non essere ri-queryata — le sue righe restano nel DB (dedup per rgid) e il −7 gg copre il caso comune (verificato a runtime: 14 gruppi al primo run, 13 al secondo per la release "2026" di Daft Punk).
  - **Release senza data**: NON inserite, loggate e contate in `skipped_no_date` (il prompt di fase prevale sulla frase di §8.5 che le avrebbe inserite per escluderle solo dal feed).
  - **`release_groups_found`** conta ogni release-group con rgid incontrato (prima dei filtri); **`releases_updated`** conta ogni upsert su riga esistente; **`api_calls`** conta i tentativi (incrementato prima della chiamata).
  - **Livello 2: commit per artista** — se interrotto, l'artista corrente riparte da zero la settimana dopo (spec §8.2: "se fallisce, riparte la settimana dopo"; le recording già viste di artisti completati non vengono rivisitate grazie a `seen_recordings`).
  - **`release_in_range` applicata anche al livello 1**: la query MB `TO *` include le date future; §7 limita a `[from, oggi]` → filtrate client-side.
- Decisioni prese (e perché):
  - Sort feed con `nullif(first_release_date, "")` + `nulls_last()`: la colonna ha default `""` (non NULL), ma "data NULL sempre in fondo" vale anche per le date vuote.
  - Upsert `release_artists` con `ON CONFLICT DO NOTHING` (atomico, nessuna race su PK composta); upsert release con flush + rollback/re-select difensivo su `IntegrityError` (race impossibile con i lock per tipo, gestita comunque).
  - `seen-all` aggiorna `seen_at=now` solo sulle righe effettivamente non-viste; `GET /releases/{id}` rinfresca `seen_at` a ogni vista.
  - Cap livello 2 a **2000 recording per artista** (spec: "costo alto per artisti prolifici"): con il rate limit 1 req/s e 1-3 chiamate per recording, un artista molto prolifico impiegherebbe ore; oltre il cap si logga e si passa all'artista successivo.
- Deviazioni dalle specifiche (approvate da chi): nessuna (le divergenze sopra sono interpretazioni registrate; la UI resta da fare in fase 08).
- Test: `backend/tests/test_dates.py` (10), `test_discovery.py` (22), `test_releases_api.py` (10), + 4 test client in `test_mb_matching.py` (query §8.1 esatta, browse senza inc, lookup recording/release con inc giusti). **Strategia rate limit (come fase 04)**: il percorso reale del client è esercitato con trasporto stub e `asyncio.sleep` monkeypatchato — 3 chiamate sequenziali → 2 sleep ≈ 1.0 s; in tutti gli altri test il client è sostituito da un fake scriptato (`_FakeClient`) che registra ogni chiamata (assert su query `from`, offset, `recording-count`, nessuna chiamata extra per recording già viste). Nessun test tocca musicbrainz.org.
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/python -m pytest -q` → **160 passed** (erano 112; +37 nuovi fase 05, +4 client, +7 altri) in ~15 s, 1 warning noto (httpx2).
  - `ruff check .` + `ruff format --check .` da `backend/` e da root (invocazione CI) → OK.
  - Coverage: TOTAL **94%** (target §13 ≥70%): `services/discovery.py` 90%, `services/dates.py` 97%, `api/releases.py` 98%, `api/scans.py` 94%, `services/musicbrainz.py` 95%.
  - Smoke reale (rete): search release-group di Daft Punk → `count` presente, credit phrase ricostruita "Daft Punk", tipi/secondary/date parziali ("2026") confermati; browse → `recording-count` 1886; catena livello 2 (lookup recording → lookup release → release-group con primary-type/first-release-date) verificata end-to-end.
  - E2E reale (uvicorn su 8101, DB nuovo, `MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test`): scan libreria → 13 artisti, 11 matchati; `discovery_from_date` = 90 gg fa; `POST /scans/releases` → **stats: artists_processed 11, release_groups_found 14, releases_new 10, skipped_type 4, api_calls 11, duration_s 21.3** → **durata ≥ api_calls − 1** (prova rate limit reale). `SELECT type, COUNT(*)` → album 2, ep 1, single 7; `role='featured'` → **4** (Streets Is Watching / Dear Summer / Free to Love / Dancing Without You — i feat. del livello 1). Data parziale conservata ("2026" Daft Punk). `GET /releases` → total 10, matched_artists popolati; `GET /releases/1` → seen=1 + seen_at, poi `?seen=no` → total 9 senza id 1; state merge ok; 404 ok; `seen-all` → `{"updated":9}` → `?seen=no` → 0. **Dedup**: secondo `POST /scans/releases` → **releases_new 0**, nessun errore UNIQUE, cursori aggiornati (es. Beyoncé 2026-07-04). `POST /scans/feat` → 202, chiamate reali livello 2 in log (browse → recording lookup → release lookup) con **retry reale su 503** (backoff → 200, visibile nei log), ~1 req/s; kill del server a metà artista → al riavvio `running: null` (nessun lock bloccato), feat scan rilanciabile (202); la run interrotta non scrive riga `scan_runs` (la riga è scritta a fine run).
- Esito review (modello avanzato): **da eseguire** (fase 05 richiede review avanzata obbligatoria prima del merge su main).
- **Fix dei findings di review (2026-08-03, post-verifica)** — 2 MEDIA + 3 BASSA risolti:
  - **MEDIA 1 (livello 2 perde release future/senza data)** — `services/discovery.py`: una recording veniva marcata `seen_recordings` anche quando tutte le sue release erano skippate (data futura, senza data, tipo escluso) → la release non sarebbe MAI più stata rivisitata quando MB completa la data. Fix: la recording è marcata seen **solo se non ha release o se almeno una release-group è stata accettata**; le altre vengono riesaminate settimanalmente (costo bounded dal cap 2000, documentato). Regression test: release futura → non seen → al run successivo con data completata → release inserita + seen.
  - **MEDIA 2 (scan concorrenti: race/rollback per-artista e "database is locked")** — nuovo `services/scan_locks.py`: **un solo lock globale** condiviso da library/releases/feat (SQLite ammette un solo writer; le transazioni lunghe superavano il busy_timeout 5 s facendo abortire la run concorrente; la race UNIQUE su rgid faceva rollback dell'intero lavoro per-artista — nel livello 2 migliaia di seen_recordings). Ora: qualunque scan in corso → 409 per qualunque altro tipo (decisione registrata; `/scans/status` torna single-valued, risolve anche il BASSA 3). `library_scan` e `discovery` delegano a `scan_locks`; `cancel_all` rilascia il lock globale; `reset_state` nei test resetta il lock condiviso. E2E reale: POST `/scans/releases` 202 → POST `/scans/library` **409** → POST `/scans/feat` **409** → a fine run `/scans/library` 202.
  - **BASSA 1 (count mancante)** — livello 1: `count or 0` fermava la paginazione dopo la prima pagina se MB omettesse `count`; ora break solo se `count is not None and offset >= count` (come il livello 2). Test: pagina piena senza count → paginazione completa.
  - **BASSA 2 (filtri data non padded)** — `_validate_date_param` normalizza `2024-5` → `2024-05` via `parse_mb_date` prima del confronto stringa con le date padded del DB. Test API dedicato.
  - **BASSA 3 (running multiplo)** — risolto dal lock globale (vedi MEDIA 2).
  - Esito: suite **167 passed** (erano 162; +5 test di regressione), ruff OK, E2E reale cross-type 409 verificato. Commit: `fix(discovery): review findings — level-2 seen gating, global scan lock, date filter normalization`.
- **Verifica di fase (post-implementazione, 2026-08-03)**: PASS su tutti i punti — vedi report di verifica. Due fix emersi durante la verifica:
  - **Fix 1 (graceful shutdown)**: uvicorn, su SIGTERM, non cancella i task in background → una run interrotta non scriveva NESSUNA riga `scan_runs` (o, se cancellata, poteva finire con status "ok" parziale). Ora: `run_discovery` cattura `asyncio.CancelledError` → status `error` + stats parziali persistiti; `discovery.cancel_all()` (registro `_tasks`) chiamato nello shutdown del lifespan (`main.py`) cancella i task in volo e forza il rilascio di lock/`_running` anche per task cancellati **prima di partire** (un task mai avviato non esegue mai il suo `finally` — comportamento asyncio verificato). Verificato E2E: kill a metà feat scan → riga `feat|error|started_at|finished_at` con `artists_processed 11, api_calls 3, recordings_pages 1`; al riavvio `running: null`, nessun lock bloccato, scan rilanciabile. +2 test (`test_run_discovery_cancelled_mid_run_records_error_status`, `test_cancel_all_persists_error_run_and_releases_locks`).
  - **Nota di procedura (non è un bug dell'app)**: il CLI `sqlite3` ha `foreign_keys=OFF` di default → un `DELETE FROM releases` manuale NON fa cascata su `release_artists`/`release_state`, lasciando righe orfane che si riagganciano ai nuovi id (rowid reuse) e "congelano" ruolo/seen precedenti (l'app, correttamente, non sovrascrive mai righe esistenti). Per wipe manuali usare `PRAGMA foreign_keys=ON` o cancellare i figli prima.
- Problemi noti / debito tecnico:
  - `server: uvicorn` esposto in dev (fix in fase 11) e warning httpx2 (noti da fasi precedenti).
  - Livello 2 con artisti molto prolifici può impiegare decine di minuti (bounded dal cap 2000/artista); il progresso di un artista interrotto si perde (spec-sanctioned, "riparte la settimana dopo"); con lo shutdown graceful ora l'interruzione lascia comunque una riga `scan_runs` status=error con le stats parziali.
  - `release_groups_found` al secondo run può essere < del primo per le date parziali indicizzate da MB al primo giorno (documentato sopra, nessuna perdita di righe).

---

## FASE 04 — Abbinamento artisti → MusicBrainz ID (+ split morbidi) — 2026-08-03
- Branch: fase-04-matching-artisti
- Cosa è stato fatto:
  - `backend/requirements.txt`: aggiunti `httpx==0.28.1` (client HTTP async per MusicBrainz, spec 7) e `tenacity==9.1.4` (retry con backoff esponenziale, spec 7), versioni esatte con commento inline. Installati e verificati su Python 3.12.13.
  - `backend/app/services/musicbrainz.py`: client async con galateo §7 esatto — base URL `https://musicbrainz.org/ws/2/`, User-Agent `nucs/1.0 ( <email> )` con email letta dalla settings `mb_contact_email` (fallback `nucs/1.0 ( selfhosted )`, via `build_user_agent`); **rate limiter globale** a livello modulo (token bucket 1 req/s: `asyncio.Lock` + timestamp `time.monotonic()` dell'ultima richiesta, condiviso da tutti i job, anche futuri cover-art); `GET` helper con `fmt=json` e timeout 15 s; retry tenacity su 429/5xx/network error (`retry_if_exception` su `HTTPStatusError` 429/≥500 e `TransportError`) con backoff esponenziale 1 s→2 s→4 s→8 s e max 5 tentativi, poi `MBError` custom; status non-retryable (es. 404) → `MBError` immediato; nessuna cache in questa fase; `search_artist(name, limit=5)` → `[{mbid, name, score}]` con escaping delle virgolette nel query (robustezza nomi da tag); singleton `get_client(email)` (pool di connessioni riusato, ricostruito solo se cambia la email); `reset_for_tests()` per l'isolamento dei test.
  - `backend/app/services/mb_matching.py`: `match_artist(db, row)` — **match-first** (§6.4.4): `search_artist(nome intero)`, best score ≥ 90 → salva `mbid` + `mb_match_score` e ritorna True (salva "Earth, Wind & Fire", "AC/DC"); altrimenti **soft-split** (§6.4.3) su ` featuring `, ` feat. `, ` ft. `, ` & `, `, `, ` vs `, ` with `, ` con ` (case-insensitive, spazi obbligatori, split sul **primo** separatore presente, parti trimmate, ogni parte ≥2 char, parti trivial droppate e split valido solo con ≥2 parti non-trivial — decisione: "A & Various Artists" non si splitta); per ogni parte: search MB, score ≥ 85 → upsert riga figlia (`normalized_name` dedup, `source` ereditata dal padre, mbid aggiornato **solo se assente**); ≥1 parte matchata → padre `ignored=1` + `mb_match_score=NULL`, ritorna True; nessuna parte matcha → padre resta senza mbid ("non abbinato" in UI), ritorna False; guard: artista già con mbid → True senza nuove ricerche (rematch su già abbinato). `match_all_pending(db, limit=100)` — artisti con `mbid IS NULL` e `ignored=0`, ordinati per id, stats `{processed, matched, split, unmatched}`; su `MBError` l'artista conta come unmatched e il batch continua (decisione: un fallimento di rete non blocca gli altri).
  - `backend/app/api/artists.py` (protetto da `require_user`): `GET /api/v1/artists?ignored=all|yes|no&q=&page=&page_size=` (q max 200, page_size max 100) → `{items, total, page, page_size}` con item `{id, name, source, mbid, mb_match_score, ignored, releases_count}` (releases_count=0, popolato in fase 05), ordinamento `name ASC`; `POST /api/v1/artists {name}` → 400 se trivial (is_trivial_artist/normalize) o duplicato su `normalized_name`, crea con `source="manual"` e lancia il match in **background task** (202 + artista, non blocca la risposta; task con sessione propria, errori loggati); `PATCH /api/v1/artists/{id} {ignored}` → 200 artista aggiornato, 404 se manca; `POST /api/v1/artists/{id}/rematch` → riesegue `match_artist` (rispetta il rate limit globale, è awaitato) → `{matched: bool, mbid}`. Schema pydantic `ArtistCreate`/`ArtistPatch` in `app/schemas.py`; router registrato in `main.py`.
  - **Integrazione scan (DECISIONE registrata come richiesto dal prompt)**: il match NON è un nuovo tipo di scan (i tipi ammessi da §10 restano `library|releases|feat`); viene eseguito **automaticamente alla fine dello scan libreria** (dentro `_run_scan_task`, dopo `scan_library_sync`, solo artisti pending, cap 100/run, con sessione propria; stats di match loggate con le stats dello scan) **e** manualmente via `POST /artists/{id}/rematch`. Il CLI `scan-library` resta sync senza match automatico (decisione: il CLI è strumento operativo, il rematch manuale copre il caso; annotato qui).
  - Test: `backend/tests/test_mb_matching.py` (25 test). **Strategia di test rate limit (decisione, come richiesto dal vincolo)**: il codice di produzione rispetta §7 con sleep reali; i test **non aspettano mai**: il rate limiter viene testato direttamente mockando `asyncio.sleep` e asserendo le sleep richieste (~1.0 s tra le chiamate; 3 chiamate → 2 sleep ≈ 1.0, totale ≥ 1.9 s) e il backoff tenacity ([1.0, 2.0, 4.0, 8.0] esatto con `asyncio.sleep` mockato); in tutti gli altri test il rate limiter è disattivato e/o il trasporto è un `_StubTransport` in-memory (`httpx.AsyncBaseTransport`) con risposte scriptate — **nessun test tocca musicbrainz.org**. Guardia in `conftest.py`: fixture autouse che sostituisce `mb_matching.match_all_pending` con un no-op veloce (lo scan post-library dei test esistenti non fa mai rete); i test di matching riabilitano esplicitamente la funzione reale. Coperti: match diretto ≥90, split feat con padre ignored + figli con source ereditata, **"Earth, Wind & Fire" match intero → NESSUNO split** (caso chiave), nessun match → mbid NULL, split senza parti ≥85 → padre invariato, figlio esistente che riceve mbid senza perdere identità, match_all_pending stats (matched/split/unmatched) e limit, UA sempre presente (formato esatto email e fallback), fmt=json sulla richiesta, retry 429→successo (3 tentativi), retry esausto → MBError (5 tentativi), network error retry, 404 immediato, API (401, lista/filtri/paginazione/ordinamento, POST duplicato/trivial 400, POST 202 + match in background, PATCH + riflesso nel GET, rematch 404, rematch con esito), auto-match post-scan con cap 100.
- Versioni dipendenze introdotte: httpx 0.28.1, tenacity 9.1.4 (esatte, `==`).
- Decisioni prese (e perché):
  - Split soft a **un solo livello sul primo separatore presente** (non ricorsivo): semplice e coerente con §6.4.3; il caso multi-separatore ("X feat. Y vs Z") produce parti intermedie che vengono matchate come nomi interi su MB.
  - Split valido solo con **≥2 parti non-trivial di ≥2 char**: "A, BC", "AA & Various Artists" non si splittano (restano "non abbinati").
  - `match_artist` su artista **già abbinato** ritorna True senza nuove ricerche: il rematch non re-splitta mai un artista con mbid.
  - `match_all_pending` continua il batch su `MBError` (conta unmatched e logga warning): un fallimento di rete non blocca gli altri artisti.
  - Uscita 202 su `POST /artists` con match in background (coerente con `POST /scans/library` 202; il prompt richiede esplicitamente di non bloccare la risposta).
  - CLI senza auto-match (documentato sopra).
- Deviazioni dalle specifiche (approvate da chi): nessuna. Nota di perimetro: `GET /artists` implementa i filtri del prompt di fase (`ignored`, `q`, `page`, `page_size`); il filtro `source` di §10 è rimandato (non richiesto dal prompt; minimi cambi).
- Ambiguità riscontrate (interpretazione scelta):
  - §7 "email da settings mb_contact_email": la chiave non è nei default di `seed_settings_if_empty` (§4 non la elenca); letta via `get_setting` con fallback `selfhosted` — la chiave potrà essere settata dalla UI impostazioni (fase 09) senza cambi di codice.
  - "3 chiamate impiegano ≥2s": implementato come verifica delle sleep richieste dal rate limiter (2 sleep ≈ 1.0 s) con clock mockato, come suggerito dal prompt; il timing reale è verificato nella verifica manuale (5 rematch = 12.99 s ≥ 4 s).
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && /tmp/nucs-venv/bin/pip install -r requirements.txt -q && ruff check . && python -m pytest -q` → **verde**: ruff OK, **107 passed** (erano 81; +25 nuovi test fase 04, +1 dal conteggio precedente) in ~8 s, 1 warning noto (httpx2).
  - `ruff check .` + `ruff format --check .` da `backend/` e da root (invocazione CI con `--config backend/pyproject.toml`) → OK.
  - Coverage: TOTAL **95%** (target §13 ≥70%): `services/mb_matching.py` 95%, `services/musicbrainz.py` 97%, `api/artists.py` 96%.
  - Smoke reale (rete, 1 richiesta): `search_artist("Earth, Wind & Fire")` → `535afeda-2538-435d-9dd1-5e10be586774` score 100 (MBID reale verificato).
  - E2E reale (uvicorn su 8098 con `DATA_DIR=/tmp/nucs-f04/data`, `MUSIC_LIBRARY_PATH=/tmp/nucs-lib-test`, login admin): `POST /scans/library?full=true` → 202; a fine scan (auto-match con rate limit reale): **13 artisti totali, 11 matched, 2 unmatched** (Pianista Nera id 4 — artista oscuro senza hit ≥90/85; "Artista Sconosciuto" id 10 — banale non filtrato dai tag di prova), ~84.6% di match su libreria mainstream mista. `SELECT name, mbid, mb_match_score FROM artists WHERE mbid IS NOT NULL LIMIT 5` + verifica a mano su https://musicbrainz.org (curl + User-Agent corretto): **Beyoncé** `859d0860-d480-4efd-970c-c05d5f1776b8`, **Daft Punk** `056e4f3e-d505-4dad-8ec1-d04f521cbb56`, **AC/DC** `66c662b6-6e2f-4930-8610-912e24c63ed1`, **Pharrell Williams** `149f91ef-1287-46da-9a8e-87fee02f1471`, **Radiohead** `a74b1b7f-71a5-4011-9441-d0b5e4122711` (quest'ultimo da POST manuale + match in background) → tutti corretti. Nessun padre `ignored=1` nella libreria di prova (i multi-artisti di prova erano già splittati da `;` in fase 03 e il feat era già estratto dal titolo): i casi soft-split sono coperti dagli unit test.
  - API via curl (cookie autenticato): `GET /artists?q=daft` → 1 hit filtrato con shape completa; `PATCH /artists/7 {"ignored":1}` → 200 e riflesso in `GET /artists?ignored=yes`; `POST /artists {"name":"Radiohead"}` → **202** con `source=manual`, mbid valorizzato in background dopo ~6 s; `POST` duplicato → **400** "Artist already exists"; `POST /artists/9999/rematch` → **404** "Not found"; rematch su artista non abbinato → `{"matched":false,"mbid":null}` coerente; senza cookie → 401.
  - **Timing rate limit reale**: `time` su 5 rematch consecutivi di un artista non abbinato → **12.99 s totali** ≥ 4 s (rate limit 1 req/s rispettato, con latenza).
- Esito review (modello economico, 2026-08-03): **0 ALTA, 0 MEDIA, 4 BASSA — nessun finding bloccante** (checklist sicurezza: B1/B2 ok, rate limit presente su TUTTI i percorsi di rete, match-first/soft-split/upsert/retry/timeout verificati, nessuna chiamata MB bloccante nell'event loop, input API validati). **I 4 BASSA sono stati fixati subito dopo la review** (commit `fix(artists): resolve phase-04 review findings...`, vedi sotto): catch `IntegrityError` sull'upsert, `MBError` → 503 su rematch, chiusura `AsyncClient` (rebuild + shutdown), escape wildcard LIKE su `q`.
- Fix dei findings BASSA (post-review, 2026-08-03, commit su main):
  - **BASSA 1 (upsert race)** — `_upsert_child` ora fluscha con try/except `IntegrityError`: su duplicato concorrente rollback completo e ritorna `False`; `match_artist` abbandona l'artista corrente e l'upsert idempotente viene ritentato alla run successiva (nessun duplicato di `normalized_name`, nessuno stato parziale persistito; il savepoint `begin_nested` di SQLAlchemy 2.0 è stato scartato: lascia la sessione in pending-rollback). `POST /artists` gestisce `IntegrityError` su commit → 400 "Artist already exists".
  - **BASSA 2 (MBError su rematch)** — `POST /artists/{id}/rematch` cattura `MBError` → **503** `{"detail":"MusicBrainz is unavailable"}`; `search_artist` usa `artist.get("id")` e salta gli hit senza id (mai più KeyError).
  - **BASSA 3 (chiusura client)** — `get_client` è ora async e chiude (`aclose()`) il vecchio `AsyncClient` al rebuild; nuovo `close_client()` chiamato nello shutdown del lifespan (`main.py`); metodo pubblico `MusicBrainzClient.aclose()`.
  - **BASSA 4 (wildcard LIKE)** — `q` in `GET /artists` escaperà `\`, `%`, `_` prima dell'`ilike` (con `escape="\\"`): la ricerca è letterale.
  - Nuovi test di regressione (5): `test_search_artist_skips_entries_without_id`, `test_api_rematch_503_when_musicbrainz_down`, `test_api_artists_q_escapes_like_wildcards`, `test_upsert_child_concurrent_duplicate_handled`, `test_close_client_noop_and_clears_singleton` → totale suite **112 passed**, coverage TOTAL **95%**.

---

## FASE 03 — Scansione libreria musicale ed estrazione artisti — 2026-08-03
- Branch: fase-03-scan-libreria
- Cosa è stato fatto:
  - `backend/requirements.txt`: aggiunto `mutagen==1.48.1` (commento inline: lettura tag audio, spec 6). Installato e verificato su Python 3.12.13.
  - `backend/app/models.py`: nuova tabella `ScanFile(path PK, mtime INTEGER (st_mtime_ns), size INTEGER)` (§6.5) + migration Alembic `f78ca2bec293_add_scan_files_table` (catena lineare da `9cb782c0d8f5`).
  - `backend/app/services/names.py`: `normalize_name` esattamente §6.3 (NFKD → strip combining → lower → `[^\w\s]`→spazio + `_`→spazio → collapse spazi); `extract_feat_from_title` (regex case-insensitive su gruppi `(...)`/`[...]` con keyword `feat.|ft.|featuring|con`, split interno su `,`/`&`/` e `; **solo parentesi**, il suffisso `" - feat. X"` senza parentesi NON è gestito — documentato nel docstring, per fase 04); `is_trivial_artist` (varianti lower/raw + normalizzate di "various artists", "aa.vv.", "unknown artist", "unknown", nomi < 2 char, §6.4.6).
  - `backend/app/services/library_scan.py`: `scan_library_sync(full=False)` — `os.walk(followlinks=False)` di `MUSIC_LIBRARY_PATH` (estensioni .mp3/.flac/.m4a/.mp4/.ogg/.opus case-insensitive); lettura tag con `mutagen.File(easy=False)` con mappatura §6.2 per ID3 (TPE1/TPE2/TIT2/TIPL/TMCL), Vorbis/FLAC/Ogg (ARTIST+ARTISTS/ALBUMARTIST/TITLE/PERFORMER/COMPOSER/REMIXER), MP4 (©ART/aART/©nam, `©wrt` best-effort come compositore); split SOLO su `;` (decisione operativa §6.4) + trim + dedup; feat dal titolo → `tag_feat`; upsert su `normalized_name` con regola source forte/debole (tag_artist/tag_albumartist sovrascrive tag_feat/tag_contrib, mai il contrario, mai il nome visualizzato); incrementale via `scan_files` (mtime_ns+size, `full=True` svuota scan_files); `scan_runs` con stats JSON {files_seen, files_parsed, files_skipped, files_error, artists_new, artists_total, duration_s} e status ok/error; audit event `scan_run` (nuovo `EVENT_SCAN_RUN` in `app/services/audit.py`). Errori di lettura → warning + contatore, mai eccezioni; eccezione fatale (es. libreria inesistente) → status error su scan_runs. **Nessuna write sulla libreria**: grep su open/write/unlink/mkdir in library_scan.py → zero risultati; verificato anche a runtime confrontando mtime.
  - `backend/app/api/scans.py` (protetto da `require_user`): `POST /api/v1/scans/library?full=` → 202, 409 `{"detail":"Scan already in progress"}` se già attivo; `GET /api/v1/scans/status` → `{running: null|{type,since}, last_runs: [ultimi 10 scan_runs con stats parsato]}`. Router registrato in `main.py`.
  - Lock asyncio globale per tipo di scan (dict `_locks`, esposto `start_library_scan`/`running_scans`/`reset_state`); worker sync eseguito in `asyncio.to_thread` (l'event loop non viene mai bloccato — mutagen è sync).
  - `backend/app/cli.py`: `python -m app.cli scan-library [--full]` → migrazioni + scan sync + stampa stats; libreria inesistente → errore su stderr + exit 2.
  - Test: `backend/tests/test_library_scan.py` (16 test) + fixture audio reali: `tests/fixtures/audio/s.{flac,ogg,opus,m4a,mp4,mp3}` (skeleton validi generati una volta con ffmpeg — silenzio 10ms; mutagen 1.48 non permette più di costruire file da costruttore vuoto, "FileType constructor requires a filename" — i test copiano lo skeleton in tmp_path, taggano con mutagen e salvano in place). FLAC minimale 42-byte via struct → NO (scartato: save in place ok ma ~1.2KB vs 8KB skeleton ffmpeg, alla fine usati gli skeleton ffmpeg per tutti). Nota: la build Homebrew di ffmpeg manca di libvorbis → il fixture `.ogg` contiene Opus (letto come `OggOpus`, stessa code path di OggVorbis via `OggFileType`).
  - `backend/tests/conftest.py`: `_reset_state()` ora chiama anche `library_scan.reset_state()` (locks/running per isolamento test).
- Decisione operativa §6.4 (registrata come richiesto dal prompt di fase): **split duro SOLO su `;`** (separatore sicuro dei tagger per valori multipli) + featuring dal titolo (parentesi/quadre). Gli split morbidi (` feat. `, ` & `, `, `, ` vs `, ` with `, ` con `) NON implementati: rimandati alla fase 04, da eseguire **dopo** il match-first MusicBrainz del nome intero (score ≥ 90 → nome intero come singolo artista, salva "Earth, Wind & Fire" e "AC/DC").
- Decisioni prese (e perché):
  - `scan_files.mtime` salvato come `st_mtime_ns` INTEGER (precisione sub-secondo; file riscritti nello stesso secondo vengono rilevati).
  - File corrotti/illeggibili NON vengono inseriti in `scan_files` → ritentati a ogni scan (files_error costante finché non si sistemano). Comportamento voluto (spec: contati e loggati, mai bloccanti).
  - Gli artisti non vengono mai cancellati dallo scan (spec non lo prevede): un artista non più presente in libreria resta in `artists` (test dedicato `test_scan_detects_changed_file` documenta il comportamento).
  - `POST /scans/library` restituisce **202** (accettato, scan in background) invece di 200.
  - `TIPL/TMCL.people` in mutagen 1.48 è una lista di coppie `[role, name]` (non lista piatta): scanner e test usano le coppie.
  - Feat regex: `\b` finale **solo** dopo `featuring`/`con`, NON dopo `feat.`/`ft.` (il punto è seguito da spazio → `\b` dopo il punto non matcherebbe mai, bug trovato in fase di test).
- Deviazioni dalle specifiche (approvate da chi): nessuna.
- Ambiguità riscontrate (interpretazione scelta):
  - Il prompt chiedeva test con "artist multiplo 'A; B'", ma §6.4.6 filtra i nomi < 2 char → nei test il multi-artista usa "AA; BB" e il filtro <2 char è verificato a parte.
  - `OggOpus` NON è sottoclasse di `OggVorbis` in mutagen 1.48 (fratelli, entrambi da `OggFileType`): lo scanner usa `OggFileType` per coprire ogg/opus.
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/python -m pytest -q` → **81 passed** (erano 58 alla fine fase 02; +16 nuovi scan, +7 altri da fix fase 02)
  - `ruff check .` + `ruff format --check .` → OK; anche invocazione CI da root (`ruff check backend/ --config backend/pyproject.toml`) → OK
  - Coverage: TOTAL **95%** (target §13 ≥70%): `services/names.py` 100%, `services/library_scan.py` 89%, `api/scans.py` 100%, `security.py` 99%
  - Scan reale su libreria di prova (`/tmp/nucs-lib-test`: 7 file — FLAC con artist multiplo "Beyoncé; Jay-Z" + album artist + feat + PERFORMER; FLAC "Daft Punk" con "(feat. Pharrell Williams & Nile Rodgers)" + COMPOSER; MP3 "AC/DC" + remixer TIPL; M4A "Vasco Rossi (con Elisa)"; OGG con "Various Artists" (trivial) + feat; file corrotto): `scan-library --full` → files_seen=7 files_parsed=6 files_skipped=0 files_error=1 artists_new=13 artists_total=13; `SELECT source, COUNT(*)` → tag_artist 5, tag_albumartist 1, tag_feat 4, tag_contrib 3; campione verificato (beyonce, the carters, travis scott tag_feat, pianista nera tag_contrib, jay z); "Various Artists" assente (trivial filtrato); "Nile Rodgers" dedupato feat+composer → un solo row tag_contrib.
  - Rilancio `scan-library` SENZA `--full` → files_seen=7 files_parsed=0 files_skipped=6 files_error=1 artists_new=0 (il corrotto è ritentato, vedi decisioni)
  - Read-only libreria: `stat -f %m` su tutti i file prima/dopo due scan → **identici**; grep write-calls in library_scan.py → nessuno
  - Via API (uvicorn su porta 8099, login admin con cookie, DEV_INSECURE_COOKIES=true): POST `/api/v1/scans/library` con X-Requested-With+Origin → **202**; GET `/api/v1/scans/status` → `running: null` + last_runs (3 righe) con stats coerenti; status senza cookie → **401**
  - Concorrenza 409: coperto dal test automatico `test_api_scan_conflict_409` (worker monkeypatch-ato lento → secondo POST → 409 "Scan already in progress")
- Esito review: la voce precedente ("non ancora eseguita") era in contraddizione con il riepilogo ("fase-03 mergiata su main dopo review") e con il merge git `6ce6fb5`; **allineata in fase 04**: la review della fase 03 è stata eseguita prima del merge su main (dettaglio dei findings non trascritto in questa sezione — non bloccante, la fase è chiusa).
- Problemi noti / debito tecnico:
  - File corrotti ritentati a ogni scan (mai cache-ati): comportamento voluto, annotato sopra.
  - `server: uvicorn` esposto in dev (livello server, non middleware): aggiungere `--no-server-header` al CMD in fase 11.
  - Warning deprecazione Starlette TestClient/httpx2 (già noto da fase 01).
  - `backend/tests/fixtures/audio/*` sono binari generati con ffmpeg: se si rigenerano, assicurarsi che restino piccoli e validi (mutagen 1.48).
  - Il test API end-to-end usa polling (`_wait_until_idle`, 5s timeout): robusto ma leggermente lento.

---

## FASE 02 — Autenticazione, sessioni, rate limiting, header di sicurezza — 2026-08-03
- Branch: fase-02 (il prompt diceva "lavora sul branch corrente (fase-02)" ma il branch corrente era `main`: creato `fase-02` da `main` — interpretazione annotata)
- Cosa è stato fatto:
  - `backend/requirements.txt`: aggiunti `argon2-cffi==25.1.0` e `python-multipart==0.0.32` (commento inline: richiesto da FastAPI per endpoint form). Installate e verificate su Python 3.12.13.
  - `backend/app/security.py`: hash/verify argon2id (parametri default argon2-cffi: time=3, mem=64MiB ≥ floor 32MiB, par=4); `DUMMY_HASH` precalcolato a modulo per verifica a tempo costante su username inesistente; sessioni opache (`secrets.token_urlsafe(32)`, nel DB solo sha256 hex 64 char, `expires_at`=now+7gg, rolling renewal se <3gg); `revoke_session`/`revoke_other_sessions`/`cleanup_expired_sessions`/`list_active_sessions`; `LoginRateLimiter` in-memoria (finestra scorrevole 5 tentativi/5min per IP; 10 fallimenti consecutivi globali → blocco 15min con Retry-After; reset su successo); `parse_trusted_networks`/`resolve_client_ip` (X-Forwarded-For solo da proxy fidati, ultimo IP della lista); helpers `get_setting`/`set_setting`/`create_admin_user`.
  - `backend/app/services/audit.py`: `log_event(db, event, ip, detail)` con redazione difensiva delle chiavi sensibili (password/token/secret/cookie/authorization → `[redacted]`) prima del persist JSON; costanti evento (`login_ok`, `login_fail`, `logout`, `password_change`, `settings_change`).
  - `backend/app/deps.py`: `require_user` (cookie `nucs_session` → `verify_session`, 401 `{"detail":"Not authenticated"}`, aggiorna `last_seen_at`) esportata per i router futuri; `get_client_ip` (legge `request.state.client_ip` dal middleware).
  - `backend/app/api/auth.py` (prefix `/api/v1/auth`): POST `/login` (rate limit 429+Retry-After → dummy verify → 401 generico "Invalid credentials"; successo → audit `login_ok`, 204 + Set-Cookie HttpOnly/SameSite=Lax/Path=/Secure-salvo-DEV_INSECURE_COOKIES/Max-Age=604800, nessun Domain), POST `/logout` (revoca + cancella cookie + audit), GET `/me` (`{username, theme}` da settings), POST `/password` (verifica attuale → 400 "Current password is incorrect", policy ≥12 via pydantic, re-hash, revoca altre sessioni, audit `password_change`), GET `/sessions` (id=hash troncato 8 char, ip, user_agent, last_seen_at, current), POST `/sessions/revoke-others`.
  - `backend/app/main.py`: `SecurityHeadersMiddleware` (CSP §5.5, nosniff, DENY, Referrer-Policy, Permissions-Policy, X-Robots-Tag: noindex, HSTS solo se scheme=https, rimozione Server/X-Powered-By a livello app), `OriginCheckMiddleware` (POST/PUT/PATCH/DELETE richiedono X-Requested-With: XMLHttpRequest E Origin/Referer con netloc == Host → 403 `{"detail":"Forbidden"}`, nessuna eccezione), `ClientIPMiddleware` (risolve IP effettivo con `ipaddress` + TRUSTED_PROXY_CIDRS in `request.state.client_ip`); ordine: headers outermost. `ensure_admin_exists()` al boot (manca admin → da env con policy check + log "admin created from env", altrimenti `sys.exit(1)` con messaggio che indica il comando CLI); job asyncio orario di cleanup sessioni scadute nel lifespan; route `/robots.txt` ("User-agent: *\nDisallow: /"); auth router incluso.
  - `backend/app/cli.py`: `python -m app.cli create-admin <username> <password>` (argparse) con policy ≥12 (exit 2 + stderr), migrazioni applicate prima della creazione.
  - `backend/app/schemas.py`: `LoginRequest`, `PasswordChangeRequest` (pydantic, lunghezze max; `new_password` min 12).
  - Test: `tests/test_security.py` (24 unit test: hashing, dummy hash, sessioni CRUD/rolling/scadenza, rate limiter window/slide/reset/lockout/expiry, CIDR parsing, XFF trust, redazione audit) e `tests/test_auth.py` (26 test API con httpx AsyncClient + ASGITransport: login ok/ko identico messaggio, dummy-verify su utente ignoto, cookie flags ± DEV_INSECURE_COOKIES, 6° tentativo → 429 + Retry-After, reset contatori su successo, lockout globale, 401 senza cookie su tutti gli endpoint, 403 senza X-Requested-With/Origin/Referer o con Origin estraneo, Referer valido accettato, logout/revoca, cambio password che revoca altre sessioni, lista sessioni + revoke-others, header sicurezza, HSTS solo https, robots.txt, XFF fidato/non fidato, boot senza admin → SystemExit, boot con password corta → SystemExit, CLI create-admin).
- Versioni dipendenze introdotte: argon2-cffi 25.1.0, python-multipart 0.0.32 (esatte, `==`).
- Decisioni prese (e perché):
  - Cookie di test: fixture `make_client` usa base_url `https://testserver` perché httpx non rispedisce cookie `Secure` su http; test dedicato per `DEV_INSECURE_COOKIES=true`.
  - ASGITransport non esegue il lifespan FastAPI: le fixture eseguono esplicitamente `run_migrations()`/`seed_settings_if_empty()`/`ensure_admin_exists()` (documentato in conftest).
  - Contatore globale del rate limiter azzerato allo scattare del blocco (dopo i 15 min si riparte da zero): interpretazione semplice di "i contatori si resettano" estesa al lockout; commento nel codice.
  - `pyproject.toml`: `testpaths` da `backend/tests` a `tests` (il prompt di verifica di fase 02 esegue `python -m pytest -q` da `backend/`; con il valore precedente non trovava i test), aggiunto `asyncio_mode = "auto"` (pytest-asyncio), `extend-immutable-calls` per `fastapi.Depends` (B008), per-file-ignores S105/S106 su `tests/**` con doppia glob (`tests/**` e `backend/tests/**`) perché la CI invoca ruff da root.
  - `.coverage` aggiunto a `.gitignore` (artefatto pytest-cov).
- Deviazioni dalle specifiche (approvate da chi): nessuna.
- Ambiguità riscontrate (interpretazione scelta):
  - §5.5 "Nessun header Server esposto": il middleware ASGI rimuove header app-level, ma **uvicorn aggiunge `server: uvicorn` a livello protocollo**, fuori portata del middleware (verificato con curl: header presente). Fix = `--no-server-header` nel CMD uvicorn del Dockerfile → **rimandato alla fase 11** (annotato qui e nei problemi aperti).
  - "Lavora sul branch corrente (fase-02)": il branch corrente era `main`; creato `fase-02` (come da nome nel prompt, non `fase-02-auth` dell'header del file di fase).
- Esito verifica (comandi eseguiti e risultato):
  - `cd backend && .venv/bin/python -m pytest -q` → **58 passed** (4.0s)
  - `.venv/bin/ruff check .` + `ruff format --check .` → OK; anche invocazione CI da root (`ruff check backend/ --config backend/pyproject.toml`) → OK
  - Coverage: `app/security.py` **100%**, `app/services/audit.py` **100%**, TOTAL 98% (target §13 ≥70% superato)
  - Boot senza admin: `DATA_DIR=/tmp/nucs-d2a uvicorn ...` → processo esce (code 3) con msg "no admin user configured: set ADMIN_USERNAME and ADMIN_PASSWORD ... python -m app.cli create-admin <username> <password>"
  - Boot con env: log "admin created from env"; login sbagliato → 401 `{"detail":"Invalid credentials"}`; login giusto → 204 + `Set-Cookie: nucs_session=...; HttpOnly; Max-Age=604800; Path=/; SameSite=lax; Secure`; `/me` senza cookie → 401, con cookie → 200 `{"username":"admin","theme":"dark"}`; login senza X-Requested-With → 403; 6° tentativo → 429 `Retry-After: 300`; header sicurezza tutti presenti su `/api/health`; `/robots.txt` → `Disallow: /`
  - DB reale ispezionato: `sessions.id_hash` solo hex 64 char, token in chiaro assente (assert su token noto); audit_log con eventi `login_ok`/`login_fail` e detail `{"username":"admin"}` (nessun segreto)
  - CLI: `create-admin cliuser 'cli-password-lunga-1'` → creato (`$argon2id$` nel DB); password corta → exit 2 + stderr
  - Grep segreti: `grep -rniE "(logger\.(info|warning|error|exception|debug)|logging\.|print\()" backend/app --include="*.py" | grep -iE "password|token|secret|cookie"` → **nessun risultato** (il grep più ampio del prompt di verifica matcha solo un import e file .pyc binari: nessun log statement contiene segreti)
- Esito review (modello avanzato, 2026-08-03): 3 findings **MEDIA** + 6 BASSA, tutti risolti con fix minimi:
  - **MEDIA** — `POST /auth/password` senza rate limit né audit sui fallimenti → limiter dedicato (chiave `IP|id_sessione`, 5/5min, 429+Retry-After) + evento audit `password_fail` (`app/api/auth.py`).
  - **MEDIA** — HSTS mai emesso dietro cloudflared/tailscale (l'origin vede sempre scheme http) → HSTS emesso anche con `X-Forwarded-Proto: https`, ma **solo** da peer in `TRUSTED_PROXY_CIDRS` (`is_trusted_peer` in `app/security.py`, middleware in `app/main.py`).
  - **MEDIA** — `LoginRateLimiter`: crescita memoria illimitata → rimozione chiavi vuote dopo pruning + cap `max_tracked_ips` (default 100k) con eviction.
  - **BASSA** — origin check confrontava Host con porta non normalizzata → `_strip_default_port` (:80/:443 e IPv6 normalizzati, porte non-default restano significative).
  - **BASSA** — redazione audit non ricorsiva → `_sanitize_value` ricorsivo su dict/list (`app/services/audit.py`).
  - **BASSA** — tentativi 429 non auditati → evento `login_blocked` con debounce 60s/IP (niente flood del trail).
  - **BASSA** — password admin come argv CLI → argomento opzionale + `getpass` quando omesso (`app/cli.py`).
  - **BASSA** — digest/timestamp corrotti nel DB → 500: `verify_password` catch `Exception`, `verify_session` guarda `fromisoformat`.
  - **BASSA** — side-effect `seen=true` su `GET /releases/{id}` (spec §10): impatto minimo (SameSite=Lax), da valutare deroga spec in fase 05 (endpoint non ancora implementato in fase 02).
- Esito review: **fase 02 APPROVATA** (0 findings ALTA/MEDIA residui).
- Re-verifica dopo fix (tutti i comandi): `pytest` → **68 passed**; `ruff check` + `ruff format --check` OK da `backend/` e da root (invocazione CI); coverage TOTAL **97%** (security.py 99%, audit.py 100%); boot reale + curl: login 204+Set-Cookie (HttpOnly/Secure/SameSite=Lax), /me 401 senza cookie, 5 login errati → 401 e 6° → 429 Retry-After, cambio password rate-limitato (6° con password corretta → 429), HSTS via X-Forwarded-Proto solo da peer fidato, audit `login_ok/login_fail/login_blocked/password_fail` senza segreti, `sessions.id_hash` solo sha256 hex 64 char.
- Nuovi test per i fix (10): `test_auth.py` (password change rate limit, login_blocked auditato, HSTS XFP fidato/non fidato, origin con porta default/non-default), `test_security.py` (release empty IP slots, cap tracked IPs, timestamp corrotto, `verify_password` su input corrotti, sanitize ricorsivo). Fixture: reset di `password_change_limiter` e `_block_logged_at`.
- Problemi noti / debito tecnico:
  - `server: uvicorn` esposto in dev (livello server, non middleware): aggiungere `--no-server-header` al CMD in fase 11.
  - Warning deprecazione Starlette TestClient/httpx2 (già noto da fase 01).
  - Rate limiter in-memoria: contatori persi al restart (accettato, spec 5.3 "in memoria"; il blocco globale riparte da zero dopo restart).

---

## FASE 01 — Backend base: FastAPI, config, SQLite, migrazioni, health — 2026-08-03
- Branch: fase-01
- Cosa è stato fatto:
  - `backend/requirements.txt` con versioni pinnate (`==`): fastapi 0.141.1, uvicorn[standard] 0.52.1, sqlalchemy 2.0.51, alembic 1.18.5, pydantic 2.13.4, pydantic-settings 2.14.2 — verificate installabili e funzionanti su Python 3.12.13 (venv `backend/.venv`)
  - `backend/requirements-dev.txt`: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1, pytest-cov 7.1.0, ruff 0.16.1
  - `backend/app/config.py`: `Settings` (pydantic-settings, legge env + `.env`) con ADMIN_USERNAME, ADMIN_PASSWORD (default vuota), DATA_DIR (default `./data`), COVERS_DIR (default `{DATA_DIR}/covers`), MUSIC_LIBRARY_PATH (default `./music`), TZ, LOG_LEVEL, DEV_INSECURE_COOKIES (bool, default False), TRUSTED_PROXY_CIDRS (str). Validatori che creano DATA_DIR e COVERS_DIR (mkdir parents=True, exist_ok=True). `get_settings()` con lru_cache.
  - `backend/app/db.py`: engine SQLite su `{DATA_DIR}/app.db`, PRAGMA journal_mode=WAL, foreign_keys=ON, busy_timeout=5000 via event listener `connect`; session factory e dependency FastAPI `get_db`.
  - `backend/app/models.py`: tutte le 9 tabelle di §4 (artists, releases, release_artists, release_state, settings, sessions, audit_log, scan_runs) con colonne/tipi/PK/UNIQUE/indici come da specifica (timestamps UTC ISO-8601 TEXT); `artists` include `last_release_check TEXT NULL` (cursore discovery §8.1). Indici: releases(first_release_date), release_artists(artist_id), sessions(expires_at), audit_log(ts).
  - Alembic: `backend/alembic.ini` + `backend/alembic/` (env.py puntato a `app.models.Base.metadata`, URL DB derivato da settings); prima migration autogenerate `9cb782c0d8f5_initial_schema` che crea l'intero schema. All'avvio (lifespan) `alembic upgrade head` programmatico via `alembic.command.upgrade`.
  - Seed settings (§4): se tabella `settings` vuota, inseriti i default; `discovery_from_date` = oggi − 30 giorni calcolato a runtime.
  - `backend/app/main.py`: `create_app()` con lifespan (dirs via config, migrazioni, seed, log avvio), `GET /api/health` → `{"status":"ok","version":"1.0.0"}`, logging key=value su stdout con livello da LOG_LEVEL, handler globale eccezioni → 500 `{"detail":"Internal error"}` + traceback completo lato server.
  - Test: `backend/tests/conftest.py` (fixture `app_env` con DATA_DIR in tmp_path + monkeypatch env + reset engine/session cached), `tests/test_health.py`, `tests/test_db.py` (WAL mode, foreign_keys ON, tutte le tabelle dopo migrazione, seed settings).
  - `backend/pyproject.toml`: aggiunta config isort `src=["app"]` + `known-first-party=["app"]` per ordinamento import consistente tra CI (root) e dev (backend/).
- Versioni dipendenze scelte (fase 01): elencate sopra; tutte installate e verificate con Python 3.12.13.
- Decisioni prese (e perché):
  - `pytest-asyncio` incluso in dev requirements (richiesto dal piano), anche se in fase 01 non ci sono test async.
  - Config `Settings` valida dati ma NON crea `MUSIC_LIBRARY_PATH` (fase 03) né applica `TZ` (usato in fasi successive).
  - `_set_pragmas` applicato via event listener `connect` (WAL/foreign_keys/busy_timeout a ogni nuova connessione).
  - In `alembic/env.py` **non** viene chiamato `logging.config.fileConfig()`: altrimenti il file di logging di alembic.ini resetta il root logger e rompe il formato key=value dell'app (bug trovato e corretto).
  - `dev_insecure_cookies` è dichiarata in config ma non usata (fase 02): presente per non rompere l'env da fase 00.
- Deviazioni dalle specifiche (approvate da chi):
  - **Prompt di fase 01 chiedeva** 500 `{"detail":"Errore interno"}`; le specifiche (§5.7 e §10) impongono messaggi d'errore per l'utente in inglese e mostrano `500 {"detail":"Internal error"}`. Applicato **`Internal error`** (le specifiche vincono, regola README §4.1). Annotata come ambiguità risolta.
  - Aggiunto `backend/alembic/README` e `script.py.mako` (generati da `alembic init`), coerenza con struttura §3.
- Esito verifica (comandi eseguiti e risultato):
  - `pytest tests/` (da `backend/`) → **6 passed** (health 200 + shape ×2, WAL, foreign_keys, tutte le tabelle, seed settings)
  - `ruff check backend/ --config backend/pyproject.toml` (invocazione CI da root) → **All checks passed!**
  - `ruff format --check backend/ --config backend/pyproject.toml` → OK (9 file formattati)
  - Boot reale: `uvicorn app.main:app --host 127.0.0.1 --port 8099` → `GET /api/health` → 200 `{"status":"ok","version":"1.0.0"}`; log key=value su stdout; migrazione + seed eseguiti; `data/app.db` (+ `-wal`/`-shm`) e `data/covers` creati.
- Esito review (findings risolti / accettati):
  - Non applicabile (nessuna review formale per fase 01 economico)
- Problemi noti / debito tecnico:
  - Warning deprecazione Starlette: "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead". Non bloccante; da valutare in fase 12 (il passaggio a `httpx2` dipende dal supporto fastapi/starlette).
  - `backend/app` è un namespace package (niente `__init__.py`): funziona, ma in fase 12 valutare se aggiungere gli `__init__.py`.
  - Access log HTTP non ancora filtrati per `/api/health` (richiede middleware, previsto in fase 02 per §5.7).
- Istruzioni avvio dev (fase 01):
  ```bash
  cd backend
  python3.12 -m venv .venv            # oppure riusare backend/.venv già creato
  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
  .venv/bin/uvicorn app.main:app --reload
  # health: http://127.0.0.1:8000/api/health
  # test:   .venv/bin/python -m pytest tests/ -v
  # lint:   ruff check . --config pyproject.toml
  ```
  Variabili in `.env` nella stessa dir da cui parte uvicorn (es. `backend/.env`); DATA_DIR default `./data`.

---

## FASE 00 — Scaffolding repo, convenzioni, CI minima — 2026-08-03
- Branch: main (non serve branch separato, scaffolding iniziale)
- Cosa è stato fatto:
  - Creata struttura directory completa come da §3: backend/app/{api,services}, backend/tests, backend/alembic/versions, frontend/src/{pages,components,api}, docker/, deploy/tailscale/, .github/workflows/
  - Directory vuote tracciate con .gitkeep
  - Creato .gitignore con pattern per Python, Node, env, data, OS
  - Creato .env.example copiando esattamente le variabili da §12.3
  - Creato backend/pyproject.toml con config ruff (py312, line-length 110, regole E/F/I/UP/B/S + ignore documentati) e pytest (testpaths=backend/tests)
  - Creati backend/requirements.txt e backend/requirements-dev.txt (vuoti con commento direzionale)
  - Creato .github/workflows/ci.yml: trigger push/PR su main, job lint con ruff check backend/
  - Creato README.md radice (titolo, scopo, stato, rimando a piano/)
  - Creato .dockerignore radice (.git, node_modules, data, piano, .env)
- Decisioni prese (e perché):
  - Ruff ignore rules: S101 (assert), S104 (bind all), S301 (pickle), S403/S404 (subprocess), S603/S607 (shell). Scelte per pragmatismo in fase iniziale; da rivalutare in hardening (fase 12)
  - CI esegue ruff config dal file backend/pyproject.toml per coerenza col setup locale
- Deviazioni dalle specifiche (approvate da chi):
  - Nessuna
- Versioni dipendenze introdotte:
  - ruff (nessuna versione pinnata in CI, install latest; sarà pinnata in requirements-dev.txt in fase 01)
- Esito verifica (comandi eseguiti e risultato):
  - `ruff check backend/ --config backend/pyproject.toml` → All checks passed! (exit 0)
  - Verifica newline finale su tutti i file creati → tutti OK
  - Verifica directory creata tramite `find` → struttura conforme a §3
- Esito review (findings risolti / accettati):
  - Non applicabile (fase 00, nessuna review formale)
- Problemi noti / debito tecnico:
  - Nessuno
