# FASE 13 — Verifica manuale completa: happy path + azioni non convenzionali

- **Esecuzione**: **UMANO** (l'operatore esegue la checklist; il modello prepara il template di segnalazione e fa triage dei finding)
- **Review**: modello **AVANZATO** (triage dei finding)
- **Dipende da**: fase 12 (v1.0.0) — può essere eseguita prima come sanity check
- **Branch**: `git checkout -b fase-13-verifica-manuale`

---

## 1. Obiettivo

Complemento manuale ai test E2E automatici (`e2e/`): una checklist **esaustiva e super
dettagliata** che l'operatore esegue a mano per validare l'esperienza reale e far emergere
errori che l'automazione non vede (timing reali, device, browser veri, azioni umane).
Include **deliberatamente azioni non convenzionali / adversarial** progettate per
provocare errori e produrre **nuovi finding** (anche su aree già "verificate").

Il prodotto della fase NON è codice: è la **checklist compilata** con ✅/❌ + evidenza e i
**finding registrati** in `piano/STATO.md` (sezione "Finding verifica manuale (fase 13)").

## 2. Prerequisiti

- Installazione funzionante: dev mode (uvicorn + vite/build) **oppure** produzione
  (docker compose con profili cloudflare + tailscale, vedi fase 11).
- **DB di test**, non di produzione (clone o `DATA_DIR` dedicato), con dati reali
  (≥ 10 release con cover, ≥ 5 artisti di cui ≥ 1 non abbinato).
- Credenziali admin note; una **seconda sessione** (finestra incognita o secondo browser).
- Chrome o Firefox con DevTools; terminale con `curl` e `sqlite3`.
- (Opzionale) URL Apprise reale per l'area Notifiche; (opzionale) strumento di contrasto
  (es. axe DevTools) per l'area accessibilità.

## 3. Regole di segnalazione (leggere PRIMA di iniziare)

Ogni anomalia → **finding** con questo template (una riga per campo):

```
FINDING-13-<NN> | <area>
- Severità: ALTA | MEDIA | BASSA
- Passo: <rif. checklist, es. C7>
- Azione esatta: <cosa hai fatto, click per click>
- Atteso: <dalla checklist o dal buon senso>
- Reale: <cosa è successo, compreso errore esatto>
- Evidenza: <screenshot, testo console, status code, output curl>
- Causa probabile / file (se noto): <file:riga>
```

- **ALTA**: dati persi, sicurezza (auth/CSP), crash, blocco totale di una funzione.
- **MEDIA**: funzionalità rotta ma aggirabile, stato incoerente, UX gravemente sbagliata.
- **BASSA**: cosmetica, a11y minore, messaggio poco chiaro, comportamento documentato ma sorprendente.
- Prima di segnalare, verifica che **non sia un comportamento già documentato** in STATO.md.
- Regola di chiusura: **zero ALTA/MEDIA aperti** (o ciascuno con decisione scritta: fix in
  fase successiva con issue, o accettato con motivazione); i BASSA possono restare documentati.
- I fix che emergono vanno fatti **in un commit separato** con test, non "dentro" la checklist.

## 4. CHECKLIST MANUALE COMPLETA

### Area A — Autenticazione e sessioni

- [ ] **A1.** Login con credenziali corrette da browser 1 e da browser 2 (incognito) → entrambi a `/`.
- [ ] **A2.** Password errata → messaggio inline rosso "Invalid credentials", si resta su `/login`.
- [ ] **A3.** 5 tentativi errati in < 5 min → 6° tentativo → 429; in DevTools verifica header `Retry-After`; riprova dopo l'intervallo → login funziona.
- [ ] **A4.** Lockout globale: 10 fallimenti consecutivi (anche su browser/incognito) → blocco; un login corretto durante il blocco → 429; dopo ~15 min → funziona. (In dev l'IP è sempre loopback: il limiter globale è condiviso — comportamento atteso.)
- [ ] **A5.** Costanza temporale: con `curl -w '%{time_total}'` misura 5 login con utente inesistente e 5 con password errata → tempi simili (differenza < ~100 ms); stesso messaggio 401.
- [ ] **A6.** Input limite su login: username vuoto, solo spazi, 500+ caratteri, emoji/unicode; password con caratteri speciali → nessun crash, errori puliti, mai 500.
- [ ] **A7.** Doppio click rapido su "Log in" → una sola sessione attiva coerente (le sessioni in `/auth/sessions` non si moltiplicano in modo anomalo).
- [ ] **A8.** Premi Enter dal campo password → submit avviene.
- [ ] **A9.** Logout → `/login`; poi tasto **Back** del browser → non torni al feed (redirect a `/login`).
- [ ] **A10.** Due tab loggate: logout dalla tab A → in tab B un refresh → `/login`.
- [ ] **A11.** Cookie: in DevTools rimuovi `nucs_session` → refresh → `/login`; sostituisci il valore con uno inventato → refresh → 401 → `/login`; imposta una scadenza passata → stessa cosa.
- [ ] **A12.** Cambio password (Impostazioni → Security): con attuale errata → errore; corretta → "Password updated"; la vecchia password non logga più; la nuova sì; la **seconda sessione** (incognito) → 401 al refresh.

### Area B — Tema

- [ ] **B1.** Toggle dark→light→dark **×10 rapidi** → a ogni click il tema cambia, mai "bloccato" su un tema.
- [ ] **B2.** Toggle e **subito reload** (F5 entro ~1 s dal click) → nessuno stato corrotto; al reload il tema è coerente (locale o server).
- [ ] **B3.** Reload in chiaro → resta chiaro; reload in scuro → resta scuro.
- [ ] **B4.** DevTools → Application → localStorage: rimuovi `nucs-theme` → refresh → **default dark**; imposta `"purple"` → refresh → **default dark** (fallback).
- [ ] **B5.** Due tab: toggle in tab A → refresh tab B → stesso tema (sync server via settings).
- [ ] **B6.** Su `/login` dopo logout il tema è coerente con l'ultimo scelto.
- [ ] **B7.** Con preferenza OS chiara (`prefers-color-scheme: light`) → nessun flash del tema sbagliato al primo load.
- [ ] **B8.** Zoom 200% in tema chiaro → contrasto e leggibilità accettabili.

### Area C — Feed e dettaglio release (fase 08)

- [ ] **C1.** Feed popolato: copertine, badge tipo (Album/Single/EP), date in formato ISO (le parziali `2024` / `2024-05` mostrate **così come sono**).
- [ ] **C2.** Chip filtri All / Albums / Singles / EPs → i conteggi visibili corrispondono al DB (`?type=...` via API).
- [ ] **C3.** Combinazione: Singles + "Unseen only" + testo di ricerca → risultato coerente.
- [ ] **C4.** Ricerca con caratteri speciali: `%`, `_`, `\`, `"`, `'` → nessun errore, risultati letterali; stringa inesistente → empty state.
- [ ] **C5.** Empty state corretto: **"No new releases"** + hint + link a Settings (con artisti tracciati); con **zero artisti tracciati** (post-reset) → **"No tracked artists"** + hint "Run a library scan from Settings" + link a `/settings` (fase 15, WI-8). *(C5-no-tracked automatizzato da e2e:15)*
- [ ] **C6.** "Load more" fino alla fine → bottone sparisce/disabilitato; **conta le card**: nessun duplicato con `total`.
- [ ] **C7.** "Mark all as seen": clicca **Annulla** nel confirm → nulla cambia; poi **OK** → pallini spariti; "Unseen only" → empty state.
- [ ] **C8.** Card → dettaglio → **Back del browser** → la card non ha più il pallino (seen).
- [ ] **C9.** URL diretto a `/releases/999999` → "Release not found" + link al feed.
- [ ] **C10.** I 4 bottoni link (Spotify / YouTube Music / Deezer / Search on Google): click, **click medio** e **Ctrl+click** → nuova tab; ispeziona il DOM: `rel="noopener noreferrer"` presente; se un link è `null` (release senza dato) → bottone disabilitato.
- [ ] **C11.** Favorite: toggle → cuore pieno → reload → persiste.
- [ ] **C12.** Hide: dal dettaglio → torni al feed → la release non c'è (hidden escluso di default); `GET /releases?hidden=yes` → c'è con badge "Hidden" e bottone "Restore".
- [ ] **C13.** Copertina rotta (forza un rgid senza file via API o rinomina un file in `covers/`) → placeholder, nessun layout rotto.
- [ ] **C14.** Throttle Slow 3G in DevTools → skeleton visibile, poi card; se una richiesta fallisce → messaggio + "Retry".
- [ ] **C15.** "Load more" con rete lenta → nessuna card duplicata per doppio trigger.
- [ ] **C16.** **Purge release orfane** (fase 15, WI-7): cancella un artista con release → le sue release **restano nel feed** (documentato); bottone "Remove releases without artists" → **Annulla** nel confirm → nulla cambia; **OK** → toast "Removed N releases without artists" (o "No releases without artists" se 0) e le release orfane spariscono dal feed (verifica con API `GET /releases/{id}` → 404); ripeti il purge → 0 rimosse (idempotente); audit log ha eventi `releases_purged`. *(automatizzato da e2e:15)*
- [ ] **C17.** **Filtri feed nei query param** (fase 15, WI-9): imposta ricerca + tipo + "Unseen only" → l'URL mostra `?q=…&type=…&unseen=1`; vai su Artisti e torna (back del browser) → input e filtri ripristinati; back/forward mantengono i filtri. *(automatizzato da e2e:15)*
- [ ] **C18.** **Race debounce filtri** (fase 15, review): digita nel campo ricerca e **entro ~300 ms** cambia il filtro tipo → al debounce il filtro tipo resta attivo (URL con entrambi i parametri), non viene sovrascritto. *(automatizzato da e2e:15)*

### Area D — Artisti (fase 09 + fase 15)

- [ ] **D1.** Lista popolata: badge sorgente corretti (Artist / Album artist / Featuring / Contributor / Remixer / Manual). Colonna **"Match"** (fase 15, WI-1) con 4 stati: **(a)** mbid → ✅ + score + link "MusicBrainz ↗"; **(b)** provider ≠ manual → ✅ + label provider (Deezer/Apple Music/Discogs/…) + link "open ↗"; **(c)** attivo senza match → ⚠️ "Unmatched" + bottone Retry; **(d)** ignorato senza mbid (padre splittato) → ✂️ "Split" **senza Retry**. Nome artista **cliccabile** (nuova tab) solo quando matched → pagina del match (MB o provider) (WI-1, F11). *(render 4 stati + link nome automatizzati da e2e:15)*
- [ ] **D2.** Search: nome completo, frammento, caratteri speciali, inesistente → filtro corretto, nessun errore.
- [ ] **D3.** Filtro All / Active / Ignored coerente; filtro "Unmatched only" → solo righe Unmatched **o Split** (mai provider/MB) (fase 15: `matched=no` = mbid null **e** provider manual). *(automatizzato da e2e:15)*
- [ ] **D4.** "+ Add artist" (fase 15, WI-4/WI-5): **(a)** ricerca nome → righe candidate per provider → **click sul candidato → pannello "Dettaglio match"** (nome, disambiguation/alias/genere/paese, conteggio album per Deezer, link pagina esterna, bottone "Track this artist"; "← Back" torna alla lista); **(b)** "Add artist" con solo nome → creato e matchato in background; **(c)** campo "Track by URL (opzionale)": URL Deezer locale (`/it/artist/…`) → artista creato **già linkato** con nome risolto dal provider; URL non supportato → errore inline; nome vuoto con URL di un provider senza risoluzione (SoundCloud/Discogs/Beatport) → errore chiaro; URL **+** coppia provider/id → 422; **(d)** duplicato (anche case-insensitive) → errore inline; nome vuoto / banale (`a`, `Various Artists`) → errore; nome con virgolette/unicode → ok o errore pulito. *(pannello candidato + add-by-URL + errori automatizzati da e2e:15)*
- [ ] **D5.** Match in background: dopo ~5-10 s un reload → l'artista ha `mbid` (o "Unmatched") — mai errore bloccante.
- [ ] **D6.** "Retry" su un Unmatched (fase 15, WI-1/WI-6): **(a)** "Search again by name" su un nome non matchabile → **nessun** toast falso "Matched on MusicBrainz", la modale resta aperta; **(b)** su un nome che matcha → toast "Matched on MusicBrainz" e modale chiusa; **(c)** su un nome splittabile → toast "Name split into X + Y (artist ignored)"; **(d)** la UI non offre Retry sulle righe "Split" (il toast "Artist already resolved via split" del backend è verificabile via API `POST /artists/{id}/rematch` → `resolved_split: true` — *(automatizzato da e2e:15, API)*); **(e)** ricerca libera "Search a name (not necessarily the artist's own)" → righe candidate → click → pannello dettaglio → "Link artist" → toast "Artist matched" e `external_url` salvato (verifica API); **(f)** "Track by URL" nel modal (stessi formati di D4c); **(g)** Retry due volte di fila → nessun errore. *(a/e/g automatizzati da e2e:15)*
- [ ] **D7.** Toggle "Ignore" **×5 rapido** → stato finale coerente col server (verifica con reload e con API).
- [ ] **D8.** Ignora un artista che ha release: nessun errore; **la riga passa allo stato "Split"** (ignorato senza mbid, fase 15) e le release esistenti restano nel feed (la discovery futura non le aggiorna più — comportamento atteso); se le release restano orfane (artista **cancellato**) → pulizia con "Remove releases without artists" (vedi C16).
- [ ] **D9.** Paginazione "Load more" senza duplicati.
- [ ] **D10.** Mobile 375px: la tabella diventa lista di card usabile.
- [ ] **D11.** **Sort per nome** (fase 15, WI-2): click sull'header "Name" (freccia ▲/▼, `aria-sort`) → alterna asc/desc; ordine coerente con `GET /artists?sort=name_desc`; accanto al filtro c'è il **badge "{N} unmatched"** coerente con `unmatched_total` dell'API. *(automatizzato da e2e:15)*
- [ ] **D12.** **Add by URL end-to-end**: `https://www.deezer.com/it/artist/265213582` → artista creato, colonna Match = "Deezer", nome linkato a `deezer.com/artist/265213582`; stesso flusso con un URL MusicBrainz (mbid). *(automatizzato da e2e:15, con skip-note se Deezer giù)*
- [ ] **D13.** **Nome artista linkato** (fase 15, F11): per un artista matched, il nome nella tabella è un link `target="_blank"` con `rel="noreferrer"` verso la pagina del match (MB per gli mbid, provider per gli altri); per gli Unmatched/Split il nome NON è linkato. *(automatizzato da e2e:15)*
- [ ] **D14.** **Split reale da scan**: la riga del padre splittato (es. "Deniz Koyu & Amba Shepherd") mostra "Split"; i figli sono tracciati e matchati (vedi fase 15 §7 voce 9 — manuale, richiede la libreria reale).

### Area E — Impostazioni (fase 09)

- [ ] **E1.** Discovery: cambia data → Save → reload → data persistita.
- [ ] **E2.** Deseleziona tutti i tipi → errore inline, Save bloccato.
- [ ] **E3.** Data futura o non valida (scrivila a mano nell'input) → errore.
- [ ] **E4.** Scans: "Scan library now" → bottone disabilitato + spinner; **secondo click** durante la run → "Scan already in progress" (409).
- [ ] **E5.** Durante uno scan: naviga su un'altra pagina, torna → il polling riprende e la tabella "Recent scans" si aggiorna a fine run.
- [ ] **E6.** Tabella Recent scans: tipo, inizio, durata, esito, statistiche presenti.
- [ ] **E7.** Notifications: `notify_enabled` senza URL → errore; URL senza scheme (`telegram-bot`) → errore; test con URL finto → errore chiaro, mai crash.
- [ ] **E8.** Integrations: scrivi un secret finto → Save → reload → campo con placeholder, **mai il valore**; in DevTools Network verifica che `GET /settings` non contenga il secret.
- [ ] **E9.** Appearance: radio Light → tema cambia subito; logout → login → resta chiaro.
- [ ] **E10.** Security: nuova password < 12 char → errore; le due nuove non coincidono → errore; attuale errata → errore; corretta → "Password updated".
- [ ] **E11.** Active sessions: mostra browser, IP, ultimo accesso; la sessione corrente ha badge "Current".
- [ ] **E12.** "Revoke other sessions" → la sessione incognito al refresh → 401.
- [ ] **E13.** About: versione (`/api/health`), conteggi artisti e release coerenti col DB.
- [ ] **E14.** Save con rete **offline** (DevTools) → messaggio di errore, nessuno stato UI corrotto.

### Area F — Responsive e accessibilità

- [ ] **F1.** Viewport 320 / 375 / 768 / 1280 px: **nessuno scroll orizzontale**; griglie e navbar compatte corrette.
- [ ] **F2.** Zoom browser 200%: layout utilizzabile senza perdita di funzioni.
- [ ] **F3.** Solo tastiera: Tab in ordine logico, focus visibile (ring accent), Enter/Space attivano bottoni e switch.
- [ ] **F4.** Screen reader (VoiceOver su macOS / NVDA su Windows): label sensate su input, switch, toggle tema, icon-button.
- [ ] **F5.** Contrasto: testo `textDim` su `surface` in entrambi i temi ≥ AA (verifica con axe o calcolo manuale).
- [ ] **F6.** `prefers-reduced-motion` attivo: spinner/skeleton non fastidiosi (se non gestito → finding BASSA).
- [ ] **F7.** Autofill del password manager: username/password precompilati e il form funziona (niente hacks che lo rompono).
- [ ] **F8.** DevTools → toolbar dispositivo 375px: navbar compatta usabile, testo link nascosto, icone cliccabili.

### Area G — Network, console e resilienza

- [ ] **G1.** Console DevTools pulita in ogni flusso sopra (gli unici errori ammessi sono i 401 intenzionali dei flussi auth).
- [ ] **G2.** CSP: nessuna violazione in console; Network: **nessuna immagine/risorsa da domini esterni** (tranne i 4 link aperti a mano che vanno in nuova tab).
- [ ] **G3.** Modalità offline (DevTools): ogni azione mutante → errore inline + Retry disponibile; nessun crash.
- [ ] **G4.** Riavvia il backend con l'app aperta: comportamento documentato (sessione scaduta → 401 → `/login` o ripristino) — segnala come finding se il comportamento è incoerente.
- [ ] **G5.** Avvia il backend con `TZ` diversa → le date mostrate restano coerenti (le API sono UTC).
- [ ] **G6.** Doppio click su "Save" di una sezione → una sola richiesta sensata, nessun duplicato/errore.
- [ ] **G7.** Primo load su rete normale < ~3 s; Lighthouse (se disponibile) → annota i punteggi principali.
- [ ] **G8.** Verifica che **non** ci siano funzioni fuori scope (riproduzione audio, PWA, ecc.): non testare, solo assicurarsi che non compaiano.

### Area H — API adversarial (terminal, curl)

- [ ] **H1.** `POST /api/v1/auth/login` **senza** `X-Requested-With` → 403.
- [ ] **H2.** Con `X-Requested-With` ma `Origin` estraneo (`http://evil.example`) → 403; senza `Origin`/`Referer` → 403; `Origin` == Host → ok.
- [ ] **H3.** Body JSON malformato → 422; JSON valido con **campi sconosciuti** → 422.
- [ ] **H4.** `GET /api/v1/releases/0`, `/-1`, `/999999999` → 404/422, mai 500.
- [ ] **H5.** `GET /api/v1/covers/..%2F..%2Fetc%2Fpasswd` → 400/404, mai 200.
- [ ] **H6.** `?q=<10k caratteri>` → 422; `?page_size=0` → 422; `?page=999999` → lista vuota coerente.
- [ ] **H7.** `PUT /api/v1/settings` con chiave fuori whitelist → 422.
- [ ] **H8.** `PUT /api/v1/settings {"theme":"purple"}` → 422.
- [ ] **H9.** 12 login errati rapidi → 429 con `Retry-After`; poi un login corretto dopo il blocco → funziona.
- [ ] **H10.** `GET /api/health` sotto carico (loop curl) → sempre JSON veloce, nessun rallentamento anomalo.
- [ ] **H11.** Header di sicurezza su ogni risposta (anche statiche): `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `X-Robots-Tag`.
- [ ] **H12.** `GET /robots.txt` → `Disallow: /`; nessun header `Server`/`X-Powered-By` esposto.

### Area I — Concorrenza e stato

- [ ] **I1.** Due tab sul feed: "Mark all as seen" in tab A → refresh in tab B → anche B aggiornato (o comportamento documentato).
- [ ] **I2.** Due tab sullo **stesso dettaglio** → nessun errore; il side-effect seen non produce stato incoerente.
- [ ] **I3.** Toggle tema "simultaneo" da due tab → al reload il tema è un valore valido (uno dei due), mai rotto.
- [ ] **I4.** Avvia uno scan e fai logout nel frattempo → nessun errore, logout ok, scan prosegue (job di background).
- [ ] **I5.** Doppio click rapido su "Load more" → nessuna card duplicata.
- [ ] **I6.** "+ Add artist" con doppio submit → un solo artista creato.

### Area J — Post-deploy (solo se l'app gira in produzione via fase 11)

- [ ] **J1.** Accesso via tunnel Cloudflare: HTTPS valido, pagina login, header HSTS presente.
- [ ] **J2.** Accesso via Tailscale (`https://nucs.<tailnet>.ts.net`) → login ok.
- [ ] **J3.** Audit log: `login_ok`/`login_fail` registrati con IP reale (o edge documentato), mai segreti.
- [ ] **J4.** `docker stats --no-stream` a riposo → app < 300 MB RAM, CPU ~0.
- [ ] **J5.** Backup: file in `/data/backups/`, `sqlite3 <file> "PRAGMA integrity_check;"` → ok.
- [ ] **J6.** `git pull && docker compose build && docker compose up -d` → dati persistiti (login, release, impostazioni).

## 5. PROMPT DI VERIFICA (copia-incolla — il modello controlla il lavoro dell'operatore)

```text
Verifica la fase 13 di nucs (verifica manuale).
1. Leggi la checklist compilata (sezione "FASE 13" di piano/STATO.md): ogni voce deve
   avere esito ✅/❌ con evidenza (output, screenshot, status code). Le voci senza evidenza
   vanno marcate ❌ "non eseguita".
2. Elenca i finding registrati (FINDING-13-*) e verifica: template completo, severità
   coerente con le regole della fase, riproducibilità descritta, distinzione tra bug reale
   e comportamento documentato (confronta con STATO.md).
3. Per ogni finding ALTA/MEDIA: esiste una decisione scritta (fix fatto con test / issue
   pianificata / accettato con motivazione)? Se no, la fase NON è chiusa.
4. Output: tabella finale "area | PASS/FAIL/N.A. | evidenza" + elenco findings con esito.
```

## 6. PROMPT DI REVIEW (copia-incolla — modello avanzato)

```text
Fai la review della fase 13 di nucs (triage dei finding della verifica manuale).
1. Leggi piano/00-specifiche.md (§5, §11.3), piano/checklist-sicurezza.md, STATO.md
   (fase 13 + debiti storici).
2. Per ogni FINDING-13-*: severità corretta? È un bug vero o comportamento documentato?
   Il fix proposto (se fatto) è minimo e coperto da test? Non c'è scope creep (nessuna
   funzionalità nuova spacciata per fix)?
3. Controlla che la checklist non abbia aree saltate senza motivazione.
4. Output: tabella findings (ALTA/MEDIA/BASSA | finding | problema | decisione) +
   VERDETTO: "FASE 13 CHIUSA" oppure "NON CHIUSA: <motivi>".
```

## 7. Criteri di completamento

- [ ] Checklist eseguita al 100% con evidenza (❌ solo con motivazione scritta).
- [ ] Zero findings ALTA/MEDIA aperti senza decisione; tutti i BASSA documentati.
- [ ] Eventuali fix in commit separati con test.
- [ ] STATO.md aggiornato (sezione fase 13 con checklist compilata + findings).
- [ ] Commit: `docs(plan): fase 13 manual verification completed` (o `fix(...): ...` per i fix emersi).

## 8. Prossimo step (vita dopo la fase 13)

1. Se la checklist produce ALTA/MEDIA: apri una mini-fase di fix con la stessa metodologia
   (prompt di implementazione → verifica → review) prima di considerare l'app stabile.
2. La checklist resta **riusabile**: riesegui le aree toccate da ogni futura feature.
3. Idee v2 (vedi §1.1 specifiche): ogni nuova feature parte con la sua fase, e la fase 13
   viene ri-eseguita parzialmente (aree impattate) prima del rilascio.
