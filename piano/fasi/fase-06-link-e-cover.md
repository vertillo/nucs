# FASE 06 — Link esterni (Spotify/YTM/Deezer/Google) e cache copertine

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 05
- **Branch**: `git checkout -b fase-06-link-e-cover`

---

## 1. Obiettivo

Per ogni release: generare i 4 link esterni (§9) e scaricare la copertina in cache locale
(Cover Art Archive → fallback Deezer → placeholder). Integrazione Spotify opzionale (§8.3) per
link diretti e segnale `appears_on`. Endpoint `/covers/{rgid}` per servire le immagini.

## 2. Prerequisiti

- Fase 05 mergiata: tabella `releases` popolata (almeno qualche riga reale).
- (Opzionale) Credenziali Spotify Developer pronte.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §9 (link, formato ESATTO), §8.3 (Spotify opzionale), §8.4 (pipeline),
  §7 (galateo, vale anche per coverartarchive.org), §10 (/covers/{rgid}, /settings)
- piano/README.md §4
- piano/STATO.md
Branch: fase-06. Codice/commenti inglese. Modifiche minime.

OBIETTIVO
Link esterni + cache copertine + (opzionale) Spotify.

COMPITI
1. backend/app/services/links.py (PURO, niente I/O):
   - build_search_links(primary_artist, title, type) → dict con spotify_search, ytm, deezer_search,
     google: URL ESATTI come §9, query costruita con urllib.parse.quote(safe='').
     google include anche il type nella query (§9).
2. backend/app/services/deezer.py:
   - resolve_album(artist, title) → GET https://api.deezer.com/search/album?q=artist:"{a}" album:"{t}"&limit=1
     (httpx, timeout 10s, retry x3). Match se normalized_name(title) ≈ normalized_name(title risposta)
     (uguaglianza dopo normalize; se diversa → None). Ritorna (deezer_url_diretto, cover_xl_url) o (None, None).
   - Nessuna chiave richiesta. Rate limit gentile: max 2 req/s (semplice delay 0.5s tra chiamate).
3. backend/app/services/covers.py:
   - fetch_cover(rgid, artist, title) → prova in ordine:
     a. https://coverartarchive.org/release-group/{rgid}/front-500 (client MB di §7: stesso rate limiter!);
     b. deezer resolve_album → cover_xl_url;
     c. None → cover_path resta NULL (il frontend userà placeholder).
   - Salva in COVERS_DIR/{rgid}.jpg (scrittura atomica: tmp + rename; valida content-type image/* e
     dimensione < 5 MB; scarta altrimenti). Aggiorna releases.cover_url (sorgente) e cover_path (nome file).
4. backend/app/services/spotify.py (OPZIONALE, attivo solo se settings spotify_client_id+secret presenti):
   - client credentials: token cached in memoria con scadenza; base https://api.spotify.com/v1.
   - resolve_album(artist, title) → search album → match normalizzato → https://open.spotify.com/album/{id}.
   - Se credenziali assenti/errore auth → modulo inerte (log INFO una tantum), nessuna eccezione.
5. Pipeline (modifica services/discovery.py, punto §8.4): dopo l'inserimento di release NUOVE
   (non quelle già esistenti), per ciascuna in asyncio (concurrency limitata a 2 task, rate limiter
   rispettati): cover + link. Link salvati: spotify_url (diretto se spotify risolve, altrimenti search),
   ytm_url, deezer_url (diretto o search), google_url. Aggiungi a stats: covers_fetched, links_resolved.
   IMPORTANTE: il job non deve fallire se una singola cover/link fallisce (try/except per-release, contatore errori).
6. Backfill: funzione backfill_links_covers(db, limit=200) richiamabile da CLI
   `python -m app.cli backfill-links` per le release già presenti dalle fasi precedenti.
7. Endpoint GET /api/v1/covers/{rgid} (require_user): serve COVERS_DIR/{rgid}.jpg se esiste
   (FileResponse, Cache-Control: public, max-age=604800) altrimenti 404. Valida rgid: solo [a-f0-9-]{36}
   (regex strict) → 400 altrimenti (anti path traversal, B3).
8. GET /releases* (fase 05): includi ora cover_path e i 4 link nel dettaglio; nella lista basta cover_path.
9. Settings: spotify_client_id/spotify_client_secret scrivibili via PUT /settings ma MAI restituiti
   (GET → spotify_client_secret_set: bool, §5.8). Whitelist chiavi PUT aggiornata: discovery_from_date,
   release_types, feat_scan_enabled, theme, scan_library_time, scan_releases_time, feat_scan_weekday,
   notify_enabled, notify_urls, spotify_client_id, spotify_client_secret, mb_contact_email.
   Validazioni: date ISO, time HH:MM, weekday in mon..sun, booleans, URLs apprise non vuoti se enabled.
   (Se GET/PUT /settings non esistono ancora → implementa ORA api/settings.py completo.)
10. Test (test_links.py, test_covers.py, test_settings_api.py):
    - build_search_links: encoding corretto (spazi→%20, & → %26), tutti e 4 gli URL presenti e §9-conformi.
    - deezer resolve: mock hit/miss; cover pipeline: mock CAA 404 → fallback deezer; content-type errato → scartata.
    - /covers: 400 su rgid invalido (../../etc), 404 mancante, 200 con cache header su esistente.
    - settings: PUT segreto non rileggibile; validazioni (data errata → 422/400).

VINCOLI
- Mai superare i rate limit (§7 per CAA/MB; 2/s Deezer; Spotify default gentile 5/s).
- Niente hotlink verso il browser: la UI userà SOLO /api/v1/covers/... (CSP §5.5).
- Scrittura file solo dentro COVERS_DIR, nomi file = rgid validato.

DELIVERABLE
Report + output test + aggiornamento piano/STATO.md (fase 06).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 06 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && ruff check . && python -m pytest -q` → verde.
2. Reale (rete): `DATA_DIR=<db_fasi_prec> python -m app.cli backfill-links` → riporta stats
   (covers_fetched, links_resolved, errori). Poi:
   - SELECT COUNT(*) FROM releases WHERE cover_path IS NOT NULL → >0 (su release recenti mainstream).
   - SELECT spotify_url, deezer_url, ytm_url, google_url FROM releases LIMIT 3 → tutti i 4 valorizzati;
     apri 2 URL a mano nel browser: portano alla release o a una ricerca coerente.
   - ls $COVERS_DIR → file .jpg presenti; file < 5MB; `file` conferma JPEG/PNG.
3. API: login → GET /api/v1/releases/{id} → contiene i 4 link; GET /api/v1/covers/{rgid} → 200 image/*;
   GET /api/v1/covers/../../etc/passwd (rgid malformato) → 400/404, mai 200.
4. Settings: PUT /settings {"spotify_client_secret":"x"} → GET /settings → NON contiene "x" ma spotify_client_secret_set:true.
5. Rilancia discovery (POST /scans/releases) → stats includono covers_fetched/links_resolved senza errori bloccanti.
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 06 di nucs.
1. Leggi piano/00-specifiche.md §9 §8.3 §8.4 §7 §5.8 e piano/checklist-sicurezza.md (B3, B5, C3, F2).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: URL §9 esatti (encoding!), path traversal su /covers e su scrittura file (B3),
   segreti Spotify mai esposti né loggati (C3), rate limit rispettati su tutti i servizi,
   atomicità scrittura cover, failure isolati per-release, nessuna regressione su /releases.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Test verdi; link §9-conformi verificati a mano su 2 release reali.
- [ ] Copertine scaricate localmente e servite da /covers con cache header.
- [ ] Segreti settings write-only.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(links): external links, local cover cache, optional spotify integration`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-07-frontend-base`.
3. Apri `piano/fasi/fase-07-frontend-base.md`.

> Dalla prossima fase si lavora sul frontend: assicurati di avere **Node 20** installato in locale
> (o usa `nvm install 20`). Il backend continua a girare su :8080 in dev.
