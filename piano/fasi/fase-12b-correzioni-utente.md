# FASE 12b — Correzioni richieste dall'utente (pre-fase 13): discovery multi-fonte, criteri tag, UX feed/artisti, errori, reset

- **Implementazione**: modello economico (esecuzione controlli) + **modello AVANZATO** (security review)
- **Review**: **modello AVANZATO obbligatorio**
- **Dipende da**: fase 12 (v1.0.0) — si esegue PRIMA della fase 13 (verifica manuale)
- **Branch**: `git checkout -b fase-12b-correzioni-utente`

---

## 1. Obiettivo

Eseguire le correzioni richieste dall'utente prima della verifica manuale (fase 13):

1. Feed: infinite scroll al posto di "Load more" (vale anche per Artisti); release raggruppate per giorno; bottone "seen" sulla card senza aprire la release.
2. Discovery: MusicBrainz con filtro "solo release ufficiali" (esclude bootleg/remix non ufficiali tipo "Yeezus (Andre's Rework)") + nuove fonti Deezer e Apple Music/iTunes (catalogo ufficiale, keyless); Discogs/SoundCloud/Beatport come fonti opzionali via URL; Tidal/Qobuz/YouTube Music solo come link di ricerca sulla pagina release.
3. Pagina release: rimozione pulsante Favorite; tracklist completa; info rilevanti; link Qobuz/Tidal/Apple Music.
4. Artisti: flusso add con scelta tra candidati (tutti i provider per nome); retry con candidati + "track by URL"; filtro "unmatched only"; fonte file per gli unmatched; delete artista; tabella ordinata.
5. Criterio di tracciamento dai tag: solo artisti principali, album artist, featuring nel titolo e remixer **solo da tag** (REMIXER / TIPL-TMCL role remixer); nessuna estrazione remixer dal titolo; i vecchi performer/composer vengono ripuliti.
6. Evidenziazione feed coerente: gli artisti tracciati presenti nel credit della release sono evidenziati (name-match normalizzato), anche senza link `release_artists` (fix caso PiKi).
7. Pulsante sync in basso a destra nel feed (solo check nuove release); activity bar globale con progress e fase su tutte le pagine.
8. Pagina errori con formato esportabile (Copy JSON / Download) per la segnalazione al modello.
9. Reset library (svuota tutto, incluse cover su disco) + eliminazione artisti singoli.
10. "Back to feed" dalla release ripristina la posizione di scroll (comportamento browser back).

## 2. Prerequisiti

- Fase 12 mergiata (v1.0.0). DB di test, non produzione.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente:
- piano/00-specifiche.md (§6 tag, §7 galateo MB, §8 discovery, §9 link, §10 API)
- piano/STATO.md (fasi 01-12)
Branch: fase-12b-correzioni-utente. Codice/commenti inglese, docs in italiano.

OBIETTIVO
Eseguire TUTTE le correzioni del §1 senza regressioni (suite test + E2E verdi alla fine).

COMPITI (workstream)
1. CRITERIO TAG (library_scan.py, names.py):
   - Mantieni: tag_artist (TPE1/©ART/ARTIST), tag_albumartist (TPE2/aART/ALBUMARTIST), tag_feat (feat. nel titolo).
   - Contributi: SOLO remixer, SOLO da tag: Vorbis REMIXER + ID3 TIPL/TMCL role remixer. NIENTE dal titolo.
   - Rimuovi performer/composer da ID3, PERFORMER/COMPOSER da Vorbis, ©wrt da MP4.
   - Nuova tabella artist_files(artist_id, path): popolata a ogni scan.
   - Cleanup post-full-scan: artisti tag_contrib/tag_feat/tag_remix orfani (0 file, mbid NULL, 0 release) eliminati.
2. MODELLO + MIGRATION (models.py, alembic): Artist+provider/provider_id/external_url;
   Release rgid nullable + provider/provider_id (unique) + qobuz_url/tidal_url/apple_music_url/discogs_url/beatport_url;
   tabelle release_tracks(position,title,duration_s) e app_errors.
3. PROVIDER (services/providers/): adapter uniformi con rate limit/timeout/retry e tolleranza ai guasti:
   musicbrainz (search artist, filtro official RG con inc=releases, tracce da release ufficiale più vecchia),
   deezer (search artist, albums, tracks), itunes (search artist, lookup album+song, keyless),
   discogs (token da settings, write-only), soundcloud (RSS pubblico), beatport (EXPERIMENTAL, endpoint interno + fallback HTML).
4. DISCOVERY (discovery.py): dispatch per provider dell'artista; dedup cross-provider su
   (titolo normalizzato + artista + data ±7gg) con unione URL; feat scan resta MB-only;
   enrich: cover CAA→Deezer→iTunes, link a 8 servizi, tracklist dal provider sorgente.
   Setting discovery_filter_official (default true).
5. API: GET /artists?matched=no + source_files (unmatched); GET /artists/search?q= (tutti i provider per nome);
   POST /artists {name,provider?,provider_ref?,mbid?}; POST /artists/{id}/rematch → candidates multi-provider + split;
   POST /artists/{id}/link {url} (SOLO parse, MAI fetch → no SSRF; allowlist scheme+host);
   DELETE /artists/{id}; DELETE /api/v1/library (409 se scan in corso; wipe tabelle + cover su disco);
   GET/POST/DELETE /api/v1/errors (scrubbing segreti, auth-only);
   GET /releases/{id} + tracks + nuovi url + source; GET /scans/status + progress {done,total,phase}.
   GET /releases: matched_artists con name-match normalizzato sul credit phrase (fix PiKi), oltre ai link.
6. FRONTEND: Feed (infinite scroll IntersectionObserver, gruppi per giorno, seen per card optimistic,
   sync button in basso a destra → POST /scans/releases, "back to feed" navigate(-1) fallback /);
   ReleaseCard (bottone seen); ReleaseDetail (no Favorite, tracklist, info, 8 link buttons);
   Artists (infinite scroll, filtro unmatched, modale retry multi-provider + URL, delete, source files);
   Settings (Danger zone reset, Discogs token, toggle "solo ufficiali"); Navbar (link /errors con badge);
   App (activity bar globale con progress + fase); nuova pagina Errors (tabella, stack espandibile,
   Copy JSON / Download .json, Clear all); api/* nuovi hook.
7. ERRORI (services/errors.py): record_error() persistente; hook in scan workers, matching, provider,
   unhandled exception handler di main.py, errori client. Scrub: niente token/password/secret.
8. TEST: aggiorna test_library_scan, test_links, test_discovery, test_releases_api, test_artists;
   nuovi: providers (MockTransport), errors API, reset library, search/link/delete, name-match matched_artists.
9. E2E: scenario fase-12b.js (infinite scroll, seen da card, gruppi per giorno, retry candidati, delete artista,
   reset, pagina errori); aggiorna fase-08.js (rimuovi test Load more e Favorite).
10. Indagine caso PiKi sul DB reale: verifica riga artista + link release_artists; il fix è il name-match.

VINCOLI
- Nessun fetch server-side di URL forniti dall'utente (no SSRF).
- I segreti (token Discogs/Spotify, password) non devono MAI apparire in API, log, tabella errori o audit.
- Rate limit gentili e timeout su TUTTI i nuovi client HTTP; nessun segreto nei log.
- La pagina errori non deve esporre dati di sessione/cookie.
- Le modifiche non devono rompere la CSP/header di sicurezza esistenti (verifica con e2e).

DELIVERABLE
Codice + migration + test + E2E + aggiornamento STATO.md (sezione FASE 12b).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 12b di nucs:
1. `cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` verde.
2. `cd frontend && npx tsc --noEmit && npm run build` verde.
3. `cd e2e && npm run e2e:12b` → TUTTI PASS (e `e2e:08` aggiornato PASS).
4. Manuale con backend reale su DB di test:
   - un artista sconosciuto ("Adrenalize & Festuca") → retry mostra candidati multi-provider per nome e campo URL;
   - POST /artists/{id}/link con URL di un provider → artist.provider valorizzato, nessuna richiesta verso l'URL fornito (verifica nei log);
   - DELETE /api/v1/library → tutte le tabelle svuotate e cover cancellate da COVERS_DIR; 409 durante scan;
   - GET /releases/{id} → tracks + apple_music_url/qobuz_url/tidal_url/discogs_url/beatport_url;
   - GET /api/v1/errors e POST /api/v1/errors → persistono; nessun segreto nei campi (grep token/password/secret su un errore indotto);
   - feed: scroll infinito, gruppi per giorno, seen da card, sync button avvia solo POST /scans/releases;
   - release: nessun pulsante Favorite; "back to feed" mantiene lo scroll (navigate(-1)).
5. `pip-audit -r backend/requirements.txt` (nuove dipendenze: feedparser) e `npm audit --omit=dev --prefix frontend` → 0 high/critical (moderate non applicabili giustificate come fase 12).
Tabella finale: controllo | PASS/FAIL | evidenza.
```

## 5. PROMPT DI REVIEW FINALE — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un auditor senior (sicurezza applicativa + architettura). Review della fase 12b di nucs.
1. Leggi piano/STATO.md (sezione FASE 12b + debiti), piano/checklist-sicurezza.md, e il diff completo
   del branch fase-12b-correzioni-utente (git diff main...fase-12b-correzioni-utente).
2. Verifica in particolare:
   - SSRF: /artists/{id}/link non effettua mai fetch lato server dell'URL fornito; allowlist scheme+host;
   - scrubbing errori: nessun segreto persiste in app_errors (indotto: errore con token → grep);
   - token Discogs write-only (GET /settings mai lo restituisce);
   - reset library: auth + CSRF (middleware globale) + 409 con scan in corso;
   - nuovi client HTTP: timeout, rate limit, retry, log senza segreti;
   - CSP/header invariati (nessun unsafe-inline aggiunto, nessun dominio esterno caricato dal frontend);
   - rgid nullable non rompe cover/path traversal (valid_rgid sempre prima dell'uso su disco);
   - pagina errori non espone cookie/sessioni.
3. Verifica correttezza funzionale: dedup cross-provider, filtro official MB, name-match matched_artists
   (nessun falso positivo: artisti ignorati esclusi), progress scans coerente.
4. Verifica che NON ci sia scope creep (nessuna funzionalità non richiesta introdotta).
5. Output: tabella findings ALTA/MEDIA/BASSA con decisione (fix/test o giustificazione) + VERDETTO:
   "FASE 12b CHIUSA" oppure "NON CHIUSA: <motivi>".
```

## 6. Criteri di completamento

- [ ] Tutte le correzioni del §1 implementate e verificate (checklist manuale compilata in STATO.md).
- [ ] Suite backend verde (pytest + ruff), frontend verde (tsc + build), `e2e:12b` + `e2e:08` PASS.
- [ ] Zero findings ALTA/MEDIA aperti senza decisione scritta.
- [ ] STATO.md aggiornato (sezione FASE 12b con checklist + decisioni + deviazioni).
- [ ] Commit: `feat(core): phase 12b user corrections — multi-provider discovery, tag criteria, feed/artists UX, errors, reset`.

## 7. Prossimo step

1. Rieseguire la fase 13 (verifica manuale) sulle aree toccate: la checklist va ri-eseguita sui flussi
   feed/artisti/release/impostazioni modificati.
2. La fase 14 (produzione) resta invariata.
