# Fase 15 — Correzioni dal feedback manuale (bugfix)

File: `piano/fasi/fase-15-correzioni-utente.md`

## 1. Contesto e obiettivi

Correzione dei 15 finding emersi dall'uso manuale dell'app. Verifica automatica: backend `pytest` + `ruff` + frontend `tsc --noEmit`/`npm run build`, **più lo scenario browser `e2e:15`** (`e2e/scenarios/fase-15.js`, introdotto dopo la fase — automatizza le voci deterministiche della checklist §7); la verifica funzionale residua la fa l'utente a mano (checklist §7 aggiornata).

## 2. Decisioni utente (registrate)

1. **Artisti non matchati dopo lo scan restano attivi** (non auto-ignorati). Miglioro il matching (articolo "The") e chiarisco la UI (badge "Split" per i padri splittati).
2. **Sync nel feed resta solo release scan**, ma in assenza di artisti tracciati mostra un messaggio guida (link a Impostazioni per la scansione libreria).
3. **Discovery cross-provider** per gli artisti tracciati su MB: oltre alle release MB, cerca release su Deezer/iTunes/Discogs usando nome + fino a 2 alias non-triviali (es. "Ye" → alias "Kanye West" → Deezer 230 → "BULLY - DELUXE").

## 3. Semantica unificata: stato di match di un artista

| Stato | Condizione |
|---|---|
| Matched su MusicBrainz | `mbid IS NOT NULL` |
| Matched su provider | `provider != 'manual'` (deezer/itunes/discogs/soundcloud/beatport), anche senza `mbid` |
| Unmatched (attivo) | `mbid IS NULL AND provider == 'manual' AND ignored == 0` |
| Split (padre risolto) | `mbid IS NULL AND ignored == 1` (padre di un soft-split) |

Helper backend `is_matched(row)` = `mbid is not None or provider != "manual"`.

## 4. Work items

### WI-1 — Semantica "matched" multi-provider (F1, F3, F5, F7, F8, F11, F13b)

**Backend — `app/services/mb_matching.py`**
- `match_all_pending`: seleziona solo `Artist.provider == "manual" AND Artist.mbid.is_(None) AND Artist.ignored == 0` (non forzare match MB su artisti già linkati a un provider).
- `match_artist`: nuovo fallback **articolo**: se `search_artist(nome)` non ha hit, riprova con il nome senza articolo iniziale ("The ", "A ", "An ", case-insensitive) → "The Levellers" trova "Levellers" (score 100 verificato). Applicare il fallback sia al match-full sia alle parti dello split.

**Backend — `app/api/artists.py`**
- `list_artists`: `matched=no` → `mbid IS NULL AND provider == 'manual'`.
- `_artist_item`: `source_files` valorizzati solo per artisti unmatched (come oggi, ma con il nuovo predicato).
- `rematch`:
  - guard: se `row.ignored == 1 and row.mbid is None` → risposta immediata `{matched: false, mbid: null, resolved_split: true, split: [], candidates}` (nessuna ricerca MB ripetuta su un padre splittato).
  - semantica esplicita nella risposta: `matched` true **solo se** `row.mbid` valorizzato; `split_parts` = parti dello split appena eseguito (padre ignorato).
- `link_artist`: invariato (già corretto); verificare che `external_url` venga salvato quando il picker passa `url`.

**Frontend — `src/pages/Artists.tsx`**
- Colonna "MB match" → **"Match"** con 4 render:
  1. `mbid` set → "MB" + score + link a `https://musicbrainz.org/artist/{mbid}`.
  2. `provider != manual` → label provider (`PROVIDER_LABEL`) + link a `external_url` (o URL costruito da provider/provider_id).
  3. unmatched attivo → "Unmatched" + Retry.
  4. split (`ignored=1` senza mbid) → "Split" senza Retry.
- Nome artista cliccabile (`<a target="_blank">`) quando matched → pagina del match (F11).
- `handlePickCandidate`: passare `url: candidate.url` (F11: oggi `external_url` resta null).
- `RetryModal.handleRetry` (F1):
  - `res.mbid` set → toast "Matched on MusicBrainz", chiudi.
  - `res.split_parts.length > 0` → toast "Nome splittato in X + Y (artista ignorato)", chiudi.
  - altrimenti resta aperto con messaggio "Nessun match — scegli un candidato o linka un URL".
  - mostrare `resolved_split` (se l'artista era già un padre splittato: "Artista già risolto via split").

### WI-2 — Tabella artisti: ordinamento + conteggio unmatched (F2)

**Backend — `app/api/artists.py`**
- Nuovo param `sort` con pattern `^(name_asc|name_desc)$`, default `name_asc`; `ORDER BY Artist.name ASC/DESC`.
- Risposta: `unmatched_total` = count con i filtri `q`/`ignored` attivi E predicato unmatched (stessa subquery del filtro `matched=no`).

**Frontend — `src/pages/Artists.tsx` + `src/api/artists.ts`**
- `ArtistFilters.sort`; header "Name" cliccabile con freccia ▲/▼ e `aria-sort`.
- Badge accanto al filtro "Unmatched only": "N unmatched" (da `page[0].unmatched_total`).

### WI-3 — URL parsing con prefisso locale (F9)

**Backend — `app/services/providers/__init__.py`**
- Prima del match sul path, normalizzare: se il primo segmento è un locale (`/it/artist/…`, `/de/artist/…`, `/[a-z]{2}(-[A-Z]{2})?/…`) rimuoverlo, per `deezer.com` e per `itunes.apple.com`/`music.apple.com`.
- Es.: `https://www.deezer.com/it/artist/265213582` → `("deezer", "265213582")`; `https://itunes.apple.com/it/artist/1714710847` → `("itunes", "1714710847")`.

**Test**: estendere `test_phase12b.py::test_parse_track_url_accepts_provider_pages` (casi con locale) + casi di rifiuto invariati.

### WI-4 — Add Artist via URL (F6)

**Backend**
- `app/schemas.py`: `ArtistCreate` + `url: str | None = Field(default=None, max_length=500)`.
- `app/api/artists.py` `add_artist`:
  - se `payload.url` presente → `parse_track_url` (già locale-aware dopo WI-3); se `None` → 422 "Unsupported URL: …" (stesso messaggio del link).
  - se `name` vuoto → risoluzione nome dal provider (best-effort): mb (`get_artist`), deezer (`api.deezer.com/artist/{id}`), itunes (`lookup`); per gli altri provider → 422 "Inserisci un nome artista per questo provider".
  - crea l'artista già linkato (provider, provider_id, external_url, mbid se mb) — riuso della logica esistente di `add_artist` con provider.
- `app/services/musicbrainz.py`: nuovo `MusicBrainzClient.get_artist(mbid, inc="aliases") -> dict`.
- Adapter: metodo `resolve_artist_name(provider_id)` su provider mb/deezer/itunes.

**Frontend — `src/pages/Artists.tsx` (AddArtistModal)**
- Campo "Track by URL (opzionale)" sotto il nome; bottone unico "Add": se URL presente e nome vuoto → invia `{url}`; se entrambi → `{name, url}`. Errore 422 mostrato inline.

### WI-5 — Pannello dettaglio candidato (F4)

**Backend — `app/api/artists.py`**
- `GET /api/v1/artists/lookup?provider=&provider_id=`:
  - `mb`: `get_artist(inc="aliases")` → `{name, disambiguation, type, country, begin, end, aliases}`.
  - `deezer`: `_search(f"artist/{id}")` → `{name, nb_album, nb_fan, picture, link}`.
  - `itunes`: `lookup` → `{artistName, primaryGenreName, artistLinkUrl}`.
  - `discogs`: solo con token (`artists/{id}`), altrimenti 422 "Dettagli non disponibili per questo provider".
  - Failure-tolerant: errori di rete → 422/proxy con messaggio.

**Frontend — AddArtistModal + RetryModal**
- Click sul candidato → pannello "Dettaglio match": nome, provider, disambiguation/alias/genere/paese (+ conteggio album per Deezer), link alla pagina esterna, pulsante "Track this artist"/"Link". Le altre righe candidate restano visibili per tornare indietro.

### WI-6 — Retry con ricerca libera per nome (F10)

**Frontend — `RetryModal`**
- Input di ricerca (riusa `useArtistSearch` da `api/artists.ts`); click sul risultato → `onPickCandidate` (link con `url`). Mantenere "Search again by name" (rematch, con toast corretti di WI-1) e "Link by URL".

### WI-7 — Feed: rimozione release orfane

**Backend — `app/api/releases.py`**
- `POST /api/v1/releases/purge-orphans` → release senza alcuna riga `release_artists` (`NOT EXISTS`); `release_state`/`release_tracks` in cascata; risposta `{removed: N}`; audit `log_event`.

**Frontend — `src/pages/Feed.tsx` + `src/api/releases.ts`**
- Bottone "Remove releases of deleted artists" (nel toolbar, accanto a "Mark all as seen"), con `window.confirm` e toast "N release rimosse" (0 → "Nessuna release orfana").

### WI-8 — Feed post-reset: messaggio guida (F13)

**Frontend — `src/pages/Feed.tsx`**
- Se `useTrackedArtistsCount()` == 0 → `EmptyState` dedicato: "Nessun artista tracciato — esegui una scansione libreria dalle Impostazioni prima di usare Sync." con link a `/settings`. Sync resta release-scan.

### WI-9 — Persistenza ricerca feed (F14)

**Frontend — `src/pages/Feed.tsx`**
- Filtri (`q` debounced, `type`, `unseenOnly`) letti/scritti nei query param URL (`/` → `?q=…&type=single&unseen=1`) con `useSearchParams`; debounce invariato (300 ms). Navigazione artisti→feed e back/forward preservano i filtri.

### WI-10 — Discovery MB: reissue + default lookback (F15a/b)

**Backend — `app/services/discovery.py`**
- Default `discovery_from_date` (fallback in `_discovery_from_date`) → `date.today().replace(month=1, day=1)` (inizio anno corrente) invece di oggi − 30 gg.
- MB level-1 (`providers/musicbrainz.py::fetch_releases`): finestra query allargata `firstreleasedate:[(from − 730 gg) TO *]`.
- `_process_candidate`: per i gruppi MB nuovi con official filter ON (dettagli già fetchati):
  - se il gruppo ha almeno una release **official** con data ≥ `from` → accetta anche se `first-release-date` del gruppo è prima di `from`;
  - `first_release_date` del row = data della prima release officiale (≥ from) del gruppo (es. BULLY → 2026-03-24 invece di 2025-03-24); `mb_release_id` = earliest official (già calcolato).
  - se official filter OFF: per i gruppi con first-release-date < `from`, fetch dei dettagli solo per questo check (best-effort, failure-tolerant).

**Test**: `test_discovery.py` — gruppo con first-date vecchio + release officiali in finestra → accettato con data officiale; gruppo senza release officiali in finestra → skippato.

### WI-11 — Discovery cross-provider (F15c)

**Backend — `app/services/discovery.py`**
- In `_level1_artist` per artisti `provider == mb` con `mbid`:
  1. query-names = `[artist.name] + fino a 2 alias non-triviali` (da `get_artist(inc="aliases")`, esclusi alias con normalize duplicato).
  2. Per ogni provider in (deezer, itunes, discogs-se-token): `search_artist(q)` per ogni query-name → miglior candidato per normalize-match (fallback Deezer: primo risultato); `fetch_releases` con quel provider_id e `from_date`; candidati processati con `role=ROLE_PRIMARY` forzato.
  3. Dedup automatico via `_find_existing_release` (rgid/provider/titolo+artista+finestra data).
- Stats: nuovo contatore `cross_provider_candidates`.
- Failure-tolerant (ogni chiamata già isolata); la run è più lenta per il rate limit (accettato).

**Test**: stub provider → artist "Ye" + alias "Kanye West" → Deezer restituisce "BULLY - DELUXE" → release creata con provider deezer e ruolo primary.

### WI-12 — Verifica Amba Shepherd (F12)

- **Repro** (manuale, DB temporaneo `DATA_DIR=/tmp/...`): scan libreria reale + matching → verificare creazione figli "Deniz Koyu" e "Amba Shepherd" (MB score 100, verificato) e padre "Deniz Koyu & Amba Shepherd" → ignored. Se non riprodotto (es. MBError a metà split), correggere: lo split è già idempotente e ripetuto alla run successiva — documentare.
- **Test di regressione**: `test_mb_matching.py` — `split_soft("Deniz Koyu & Amba Shepherd")` → entrambe le parti; `match_artist` con stub MB crea entrambi i figli e marca il padre ignored.

## 5. Test automatici (pytest + e2e:15)

**Aggiornamenti a test esistenti** (nuova semantica matched):
- `test_phase12b.py`: `test_artists_unmatched_filter_and_source_files` (predicato `provider='manual'`), `test_rematch_returns_candidates_and_split` (nuova shape risposta), `test_parse_track_url_accepts_provider_pages` (casi locale).
- `test_mb_matching.py`: `test_match_all_pending_stats` (esclusione provider-linked), `test_api_rematch_*` (guard + shape).
- `test_discovery.py`: `test_official_filter_skips_unofficial_release_groups` (invariato o esteso per la data officiale).

**Nuovi test backend (pytest)**:
- `parse_track_url` con locale deezer/itunes (`/it/artist/…`).
- `GET /artists?sort=name_desc` ordinamento; `unmatched_total` coerente con filtri.
- `POST /artists` con `url` (creazione linkata), con url+name, con url non supportato → 422, con name vuoto + provider senza risoluzione → 422; risoluzione nome per deezer.
- `GET /artists/lookup` per mb (aliases) e deezer; 422 su provider non supportato.
- `rematch` su padre splittato → `resolved_split` senza chiamate MB (mock).
- `match_artist` fallback articolo: "The Levellers" → mbid di "Levellers".
- `POST /releases/purge-orphans`: rimuove solo release senza artisti, lascia le altre, conteggio corretto, audit.
- Discovery reissue: gruppo first-date < from + release officiale in finestra → accettato con data officiale.
- Discovery cross-provider: mock alias → Deezer → release creata con ruolo primary; dedup con release MB esistente.
- Default `discovery_from_date` → inizio anno.

**Frontend**: `tsc --noEmit` + `npm run build`.

**Esecuzione**: `cd backend && .venv/bin/python -m pytest` (suite completa), `ruff check` + `ruff format --check`; `cd frontend && npx tsc --noEmit && npm run build`.

## 6. Ordine di esecuzione

1. Scrittura di questo file (`piano/fasi/fase-15-correzioni-utente.md`).
2. WI-1 (semantica matched: backend) + aggiornamento test esistenti → pytest verde.
3. WI-1 frontend (colonna Match, toast, link nome, url nel picker).
4. WI-3 (URL locale) + test.
5. WI-4 (Add via URL) + test.
6. WI-5 (lookup + pannello dettaglio) + test.
7. WI-6 (retry ricerca libera).
8. WI-2 (sort + conteggio) + test.
9. WI-7 (purge orfane) + test.
10. WI-8 (messaggio guida feed).
11. WI-9 (query param feed).
12. WI-10 (reissue MB + default lookback) + test.
13. WI-11 (cross-provider) + test.
14. WI-12 (verifica Amba Shepherd + test regressione).
15. Suite completa + tsc/build + checklist manuale (in accordo con te).

## 7. Checklist verifica manuale (a cura dell'utente)

> **Aggiornata dopo l'introduzione di `e2e:15`** (nuovo scenario `e2e/scenarios/fase-15.js`,
> 2026-08-08): le voci marcate **"AUTOMATICO"** sono verificate dallo scenario (tabella in
> `e2e/artifacts/fase-15-results.md`, da incollare in STATO.md) e NON vanno rieseguite a
> mano; le voci senza marcatura restano manuali (richiedono dati reali/provider live non
> deterministici). La checklist manuale completa aggiornata ai nuovi flussi è la **fase 13**
> (`piano/fasi/fase-13-verifica-manuale-completa.md`, aree C e D: C16-C18, D1, D3-D4, D6,
> D8, D11-D14).

1. Retry → "Search again by name" su artista non matchabile → toast corretto, nessun falso "Matched on MusicBrainz"; su padre splittato → "già risolto via split" (UI: i padri splittati non mostrano Retry — il toast è verificabile via API). **AUTOMATICO** (e2e:15 ART 15-12, API 15-6)
2. Tabella artisti: click su "Name" alterna asc/desc; badge conteggio non-matchati. **AUTOMATICO** (e2e:15 ART 15-8/15-9)
3. Scan libreria: "The Levellers" matchato (articolo); "Pepp 'O Red" resta attivo/unmatched; i padri splittati mostrano "Split". **MANUALE** (richiede i file reali in `music/`)
4. Add Artist "KSI": click sul candidato MB → pannello dettaglio (disambiguation/alias) → track del corretto. **AUTOMATICO** (e2e:15 ART 15-16, con skip-note se i provider sono giù)
5. Artista su Deezer → colonna "Match" mostra Deezer (mai "Unmatched"/"MB match"). **AUTOMATICO** (e2e:15 ART 15-17)
6. Add Artist con URL `https://www.deezer.com/it/artist/265213582` → artista creato e linkato (nome risolto). **AUTOMATICO** (e2e:15 ART 15-17 + API 15-3; fallback name+URL se Deezer irraggiungibile)
7. Retry: ricerca libera per nome → link del candidato scelto. **AUTOMATICO** (e2e:15 ART 15-13, con skip-note se i provider sono giù)
8. Nome artista cliccabile → pagina del provider. **AUTOMATICO** (e2e:15 ART 15-7/15-10/15-17)
9. Scan: "Deniz Koyu & Amba Shepherd" splittato → "Amba Shepherd" tracciata e matchata. **MANUALE** (richiede la libreria reale; regressione coperta da pytest `test_mb_matching.py`)
10. Reset libreria → feed con messaggio guida; scan da Impostazioni → feed popolato; Pepp 'O Red (Deezer) mostra "Deezer" e "Panama" appare nel feed. Reset + messaggio guida **AUTOMATICO** (e2e:15 FEED 15-23); scan da Impostazioni e dati reali **MANUALI**
11. Ricerca nel feed → vai su Artisti → torna → input preservato (e back/forward). **AUTOMATICO** (e2e:15 FEED 15-18/15-19/15-20, incl. race del debounce)
12. Ye: "Bully" nel feed (data 2026-03-24, prima release officiale) e "BULLY - DELUXE" via cross-provider Deezer. **MANUALE** (richiede l'artista reale "Ye" in libreria; logica coperta da pytest `test_discovery.py`)

## 8. Prompt per la review (verifica + review finale)

I due prompt seguenti vanno copiati integralmente nel tool di review (o dati a un altro modello/collega) a lavoro completato. Il primo valida la verifica (test automatici + checklist manuale), il secondo è la code review finale. Entrambi sono **read-only**: chi esegue la review non deve modificare codice, ma solo segnalare problemi con riferimento preciso a file:riga.

### 8.1 Prompt — Review della verifica

```
Sei un reviewer QA. Devi validare la verifica della "Fase 15 — Correzioni dal
feedback manuale" dell'app nucs (backend FastAPI + frontend React), descritta
in piano/fasi/fase-15-correzioni-utente.md. Lavora in sola lettura: niente
modifiche, solo analisi e segnalazioni precise.

CONTESTO
- I 15 finding utente sono stati corretti (semantica "matched" multi-provider,
  colonna Match, sort+conteggio unmatched, URL con locale, Add-by-URL,
  lookup candidato, retry con ricerca libera, purge release orfane, messaggio
  guida feed, filtri feed nei query param, reissue MB + default lookback,
  discovery cross-provider, split Amba Shepherd).
- Verifica automatica: pytest (backend), ruff check/format, tsc --noEmit,
  npm run build. NIENTE test E2E browser: la verifica funzionale è la
  checklist manuale del §7, eseguita dall'utente.

COMPITI
1. Controlla che ogni finding (F1..F15) abbia una copertura dichiarata:
   (a) test automatico o (b) punto della checklist manuale §7. Per ogni
   finding riporta: coperto da test? da checklist? nessuno dei due?
2. Verifica che la mappatura sia vera, non solo dichiarata:
   - esegui "pytest -q" in backend/ e "npx tsc --noEmit" + "npm run build"
     in frontend/ e riporta gli esiti esatti;
   - per i test nuovi, apri i file e controlla che le assertion verifichino
     davvero il comportamento dichiarato (niente assert banali o assert che
     passano senza esercitare il codice);
   - per i punti della checklist manuale, indica per ciascuno cosa cercare
     concretamente nella UI e quali dati di prova usare (es. i file reali in
     music/, i nomi "The Levellers", "Pepp 'O Red", "Amba Shepherd", "Ye").
3. Caccia le regressioni: confronta i test modificati (test_phase12b.py,
   test_mb_matching.py, test_discovery.py, test_releases_api.py) con le
   modifiche di produzione corrispondenti e segnala eventuali test indeboliti
   (es. assertion rimosse, fixture semplificate, fakes che mascherano il bug).
4. Verifica i casi limite non coperti da test e rilevanti per i finding:
   ad esempio rematch su artista ignorato manualmente (non solo split),
   URL locale con parametri query, purge-orphans con release condivisa tra
   più artisti, cross-provider con provider down, dedup cross-provider di una
   release con data diversa oltre la finestra di 7 giorni.

OUTPUT (obbligatorio, struttura fissa)
- Tabella: finding | copertura (test/checklist/nessuna) | esito (ok/parziale/ko) | nota.
- Elenco "casi limite non coperti" con gravità (bassa/media/alta).
- Verdetto finale: la verifica è sufficiente per passare alla review finale?
  Sì / Sì con riserve (elencate) / No (con motivazione).
```

### 8.2 Prompt — Review finale del codice

```
Sei un reviewer senior. Fai la code review finale della "Fase 15 — Correzioni
dal feedback manuale" dell'app nucs (backend FastAPI + frontend React).
Lavora in sola lettura: niente modifiche, solo analisi e segnalazioni precise
con riferimento file:riga.

FILE COINVOLTI
- Backend: app/models.py (property is_matched), app/services/mb_matching.py
  (fallback articolo, match_all_pending esclude provider-linked),
  app/services/discovery.py (reissue rescue, default lookback inizio anno,
  cross-provider discovery con alias), app/services/providers/* (parse URL
  con locale, resolve_artist_name, artist_details, finestra MB +730gg),
  app/api/artists.py (filtro matched, sort, unmatched_total, rematch con
  resolved_split/split_parts, add-by-URL, lookup), app/api/releases.py
  (purge-orphans), app/schemas.py, app/main.py (seed discovery_from_date).
- Frontend: src/pages/Artists.tsx (MatchCell, ArtistName, AddArtistModal,
  RetryModal, sort, badge), src/pages/Feed.tsx (query param, purge,
  messaggio guida), src/api/artists.ts, src/api/releases.ts.

COMPITI
1. Correttezza: verifica i flussi chiave leggendo il codice:
   - semantica matched coerente ovunque (list, rematch, match_all_pending,
     source_files, UI) senza eccezioni nascoste;
   - rematch su padri splittati/ignorati: nessuna chiamata MB, shape stabile;
   - add-by-URL: conflitto url+provider, risoluzione nome, SSRF (nessun fetch
     dell'URL utente);
   - parse_track_url: locale stripping solo per deezer/itunes, niente
     regressioni sugli altri provider;
   - reissue: condizioni is_reissue, data officiale, dedup, cursore;
   - cross-provider: scelta candidato per alias, fallback deezer, dedup,
     failure-tolerance, costi rate-limit;
   - purge-orphans: semantica "release senza alcun release_artists",
     integrità (state/tracks in cascata), audit;
   - feed: sincronizzazione input<->query param (loop? back/forward?),
     debounce, validazione dei parametri.
2. Sicurezza: SSRF, validazione input (pattern query, lunghezze),
   nessun segreto nei log, XSS (nessun innerHTML), link con target=_blank
   senza rel="noreferrer".
3. Performance: N+1 (counts/files), query non indicizzate su tabelle grandi
   (unmatched_total, purge), impatto del cross-provider sui rate limit.
4. Convenzioni: stile del repo, nomi, docstring, error handling
   (failure-tolerant dove richiesto), consistenza con piano/STATO.md.
5. Test: i test nuovi sono significativi? Ci sono branch scoperti
   importanti? I fakes riflettono il comportamento reale dei provider?

OUTPUT (obbligatorio, struttura fissa)
- Per ogni area: OK oppure elenco problemi con file:riga, gravità
  (bloccante/alta/media/bassa) e correzione suggerita.
- Elenco riepilogativo "problemi bloccanti" (vuoto se nessuno).
- Verdetto finale: Approvato / Approvato con riserve / Da rivedere.
```

### 8.3 Note per chi esegue la review

- Eseguire i prompt nell'ordine: prima 8.1 (verifica), poi 8.2 (review finale); il verdetto di 8.1 condiziona l'avvio di 8.2.
- Qualsiasi problema segnalato va riportato in questo documento (nuova sezione "Esiti review") prima di considerare la fase chiusa.
- Le correzioni conseguenti alla review NON rientrano in questa fase: vanno pianificate come fase successiva (es. fase 16) se non bloccanti.

## 9. Esiti review della verifica (8.1) e correzioni applicate

**Esiti verifica automatica**: `pytest` **331→336 passed**, `ruff check`/`format` puliti, `tsc --noEmit` + `npm run build` ok. Nessuna regressione nei test modificati (3 sole righe di assert rimosse, tutte sostituzioni legittime documentate sotto).

**Verdetto 8.1**: "Sì con riserve" — copertura ok per F1–F9, F12, F13, F15 (test + checklist); F10/F14 solo checklist (vincolo no-e2e); F11 parziale.

**Casi limite emersi e risolti (fase 15, dopo la review)**:

| # | Problema | Correzione |
|---|---|---|
| 1 | Dedup cross-provider oltre la finestra ±7gg → duplicati | `_find_existing_release(name_only=True)` per i candidati cross-provider: dedup per titolo+artista normalizzati senza finestra data (stesso artista, date regionali). Test: `test_level1_cross_provider_dedups_regardless_of_date`. |
| 2 | Race debounce feed: filtro type/unseen perso se cambiato entro 300ms dalla digitazione | `setSearchParams` con **updater funzionale** `(prev) => next` (merge sull'ultimo stato) sia nel debounce di `q` sia in `updateParam`. Nessun test automatico (frontend), verifica manuale checklist 11. |
| 3 | Fallback Deezer "primo risultato" in `_best_cross_provider_candidate` poteva linkare l'artista sbagliato | **Fallback rimosso**: i candidati cross-provider richiedono ora il match esatto del nome normalizzato (nome o alias); nessun provider contribuisce altrimenti. Deviazione dal piano approvato (documentata). Test: `test_level1_cross_provider_requires_exact_name_match`. |
| 4 | F11: path "link per provider pair + url" senza assertion su `external_url` | `test_link_artist_by_provider_pair_from_picker` ora invia `url` e asserisce `external_url`. |
| 5 | Rematch su artista ignorato manualmente → risposta "già risolto via split" fuorviante | Non correggibile dal modello dati (indistinguibile dal padre splittato); raggiungibile solo via API (la UI non mostra Retry). Documentato, bassa gravità. |
| 6 | Cross-provider con provider down non testato | Test: `test_level1_cross_provider_survives_provider_failure` (provider che lancia → run completa, nessun candidato). |
| 7 | URL locale con parametri query non testato | `test_parse_track_url_accepts_provider_pages` esteso con `?utm_…` e `#page`. |
| 8 | Purge-orphans con release condivisa tra più artisti non testato | Test: `test_api_purge_orphans_keeps_releases_shared_between_artists` (release con ≥1 artista sopravvive). |
| 9 | Recovery split dopo MBError a metà non testato | Test: `test_split_recovery_after_partial_mberror` (run 1: parte 2 fallisce → padre pending, figlio 1 conservato; run 2: split completato, padre ignored). |

**Checklist manuale**: invariata (§7); per il caso 2 aggiungere alla prova 11 anche "cambia filtro tipo entro mezzo secondo dalla digitazione e verifica che il filtro resti attivo".

### 9.1 Esiti review finale (8.2) e correzioni applicate

**Verdetto 8.2**: "Approvato con riserve" — nessun problema bloccante. Correttezza/sicurezza OK (semantica matched coerente, rematch stabile, SSRF assente, validazione input ok); performance e convenzioni con riserve minori.

**Fix applicati (fase 15, dopo la review finale)**:

| # | Problema | Correzione |
|---|---|---|
| A | **Dedup cross-provider per titolo+artista fallisce con credit diversi tra provider** ("Ye" su MB vs "Kanye West" su Deezer, stesso titolo → duplicati). Il test usava artisti identici ("Mio") e non copriva il mismatch. | `_find_existing_release(same_artist=…)`: per i candidati cross-provider il dedup è ora per **titolo normalizzato** tra le sole release collegate all'artista tracciato (join su `ix_release_artists_artist_id`, order by id). Elimina i falsi-positivi tra artisti diversi e il full scan della tabella. Test: `test_level1_cross_provider_dedups_despite_artist_credit_mismatch` (BULLY/Ye vs Kanye West → una riga sola, primary_artist "Ye"). |
| B | **`_best_match` provava sempre la variante senza articolo** → una richiesta MB extra (1 req/s) per ogni nome "The/A/An…" anche con score ≥90 già al primo giro. | Short-circuit: se la variante corrente ha score ≥ `MATCH_FULL_SCORE` la ricerca termina. Test: `test_match_artist_article_variant_not_searched_when_full_name_matches` (1 sola chiamata per "The Weeknd"). |

**Riserve non bloccanti**:
- ~~Audit purge usa `EVENT_SETTINGS_CHANGE`~~ → **risolto**: nuovo evento `EVENT_RELEASES_PURGED` in `audit.py`, usato da `POST /releases/purge-orphans`.
- ~~"Active: X –" con trattino finale in `CandidateDetailsPanel`~~ → **risolto**: "Active: X – present".
- `rematch` guard su artisti ignorati a mano: `candidates` fetchati comunque via API (la UI non li usa) — rimandato, documentato.
- Role `featured` non sovrascritto da `primary` in `_add_release_artist` (solo evidenziazione feed) — rimandato, documentato.
- Costo rate-limit del cross-provider (3 ricerche × provider per artista) e della finestra MB +730gg: accettato e documentato nel piano.
- `piano/STATO.md`: aggiornato con la fase 15 (sezione FASE 15 + riepilogo rapido).

**Verifica finale**: `pytest` **338 passed**, `ruff check`/`format` puliti, `tsc --noEmit` + `npm run build` ok.

**Per chiudere la fase resta** (a cura dell'operatore): la checklist manuale §7 (12 voci) e, su richiesta, il commit delle modifiche (22 file).
