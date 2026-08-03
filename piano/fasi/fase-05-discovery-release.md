# FASE 05 — Motore di discovery release (proprie + featuring) e API release

- **Implementazione**: modello economico (logica già specificata al dettaglio)
- **Review**: **modello AVANZATO obbligatorio** (paginazione, rate limit, dedup, date parziali)
- **Dipende da**: fase 04
- **Branch**: `git checkout -b fase-05-discovery-release`

---

## 1. Obiettivo

Il cuore dell'app: per ogni artista monitorato trova le release pubblicate da `discovery_from_date`
in poi — incluse quelle in cui compare **solo come featuring** — e le salva nel DB con dedup per
release-group. Espone le API `/releases/*` (feed, dettaglio, stato, segna-tutte).

## 2. Prerequisiti

- Fase 04 mergiata: artisti con MBID presenti.
- Rileggi §7 e §8 delle specifiche prima di scrivere il prompt.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §7 (galateo MB), §8 (discovery: livello 1, livello 2, cursore, date parziali,
  dedup, §8.5), §4 (releases, release_artists, release_state), §10 (/releases/*, /scans/releases)
- piano/README.md §4
- piano/STATO.md
Branch: fase-05. Codice/commenti inglese. NON implementare: cover, link esterni, notifiche (fase 06/10).
I campi cover_*/spotify_url/ecc. restano NULL per ora.

OBIETTIVO
Discovery release livello 1 + livello 2 + API /releases/*.

COMPITI
1. Estendi services/musicbrainz.py con metodi:
   - search_release_groups(mbid, from_date, limit=100, offset=0) → query ESATTA §8.1:
     arid:{mbid} AND firstreleasedate:[{from} TO *] — from in formato YYYY-MM-DD.
   - browse_artist_recordings(mbid, limit=100, offset=0) → /ws/2/recording/?artist=...&inc=releases.
   - get_release_group(rgid) → dettaglio (artist-credit, primary-type, secondary-types, first-release-date).
2. backend/app/services/dates.py: parse_mb_date(s) → (start_date, end_date) come §7 (parziale → primo/ultimo
   giorno possibile); release_in_range(mb_date, from_date) → bool (intersezione intervalli, oggi come upper bound).
3. backend/app/services/discovery.py:
   - run_discovery(db, feat_scan=False) → stats.
   - LIVELLO 1 (§8.1) per ogni artista ignored=0 AND mbid NOT NULL:
     from = max(discovery_from_date, last_release_check - 7gg) se last_release_check presente
     (confronto su date ISO; attenzione a date parziali: usa dates.py).
     Pagina TUTTI i risultati (offset+=100 finché < count). Per ogni release-group:
     primary-type → mappa album|single|ep (minuscolo), altro → 'other' (salta se 'other' non in release_types
     di settings; default: salta). Salta se secondary-types contiene solo tipi? NO — salva tutto,
     secondary_types CSV. Salta se SENZA first-release-date (§8.5: log + contatore skipped_no_date).
     Upsert per rgid (se esiste: aggiorna solo campi vuoti, MAI sovrascrivere cover/link futuri).
     Ruolo (§8.1): 'primary' se artist-credit-phrase (lowercase) INIZIA col nome artista (lowercase),
     altrimenti 'featured'. Inserisci in release_artists (release_id, artist_id, role) se assente.
     Aggiorna artists.last_release_check = max(first_release_date viste, formato data completa se possibile).
   - LIVELLO 2 (§8.2, solo se feat_scan=True E settings feat_scan_enabled=true): per ogni artista:
     browse recordings paginato; per recording non già mappata (tabella nuova `seen_recordings`
     (recording_mbid TEXT PK, artist_id INT, first_seen TEXT) — creala con migrazione Alembic):
     per ogni release della recording → get_release_group della release → filtro data/tipo come sopra →
     upsert con role 'featured'. Contatore pages_processed in stats; se un artista ha >2000 recordings,
     fermati a 2000 e logga (limite documentato in STATO.md).
   - Registra scan_runs type='releases' (o 'feat') con stats JSON complete:
     {artists_processed, release_groups_found, releases_new, releases_updated, skipped_no_date,
      skipped_type, api_calls, duration_s, (feat:) recordings_pages}.
4. API backend/app/api/releases.py (require_user), ESATTAMENTE §10:
   - GET /releases con filtri from,to,type(CSV),artist_id,seen(all|yes|no default all),favorite,
     hidden(default no → hidden=0),q (ILIKE su title/primary_artist, max 200 char), sort date_desc|date_asc
     (data NULL sempre in fondo), paginazione §10. Ogni item: id,title,primary_artist,type,first_release_date,
     cover_path(null ok),seen,favorite,hidden, matched_artists:[{id,name,role}].
   - GET /releases/{id} → dettaglio completo + matched_artists; SIDE-EFFECT: seen=true, seen_at=now (§10).
     404 {"detail":"Not found"}.
   - POST /releases/{id}/state {seen?,hidden?,favorite?} → merge, ritorna stato; 404 gestito.
   - POST /releases/seen-all {from?,to?} → segna viste le non-hidden nel range → {"updated": n}.
5. Scans API: estendi scans.py con POST /scans/releases e POST /scans/feat (stesso lock/guard 409;
   feat rifiuta 400 se feat_scan_enabled=false). GET /scans/status già esistente mostra tutto.
6. Migrazione Alembic per tabella seen_recordings.
7. Test (test_discovery.py, test_dates.py, test_releases_api.py) con client MB mockato (fixture JSON):
   - date parziali: "2024" vs from 2024-06-01 → in range; "2023" vs from 2024-01-01 → fuori; "2024-05" ok.
   - livello1: fixture con 1 album (artista primario) + 1 singolo "Altro feat. Mio" (role featured) +
     1 release-group type "Other" (skippato) + 1 senza data (skippato+contato) → asserzioni su righe DB e stats.
   - paginazione: fixture 2 pagine (count>100) → tutte processate.
   - cursore: secondo run con last_release_check → query 'from' aggiornata (asserisci sul mock).
   - livello2: recording nuova → release del gruppo inserita con role featured; recording già vista → skip senza chiamate extra.
   - API: filtri (type, seen, q), paginazione (total corretto), dettaglio setta seen, seen-all, 404.
   - rate limit mai violato: conta le chiamate mock nel tempo (monkeypatch sleep come fase 04).

VINCOLI
- Rispetta SEMPRE §7 (1 req/s globale, UA, retry). Il livello 2 può impiegare minuti: normale, logga progressi ogni 10 pagine (INFO).
- Mai sovrascrivere in update i campi cover_*/spotify_url/deezer_url/ytm_url/google_url (fase 06).
- Tutto in async; nessuna chiamata bloccante nell'event loop.
- Se §8 ti sembra ambiguo, scrivi l'interpretazione in STATO.md e applica la più semplice conforme al testo.

DELIVERABLE
Report + output test + aggiornamento piano/STATO.md (fase 05, con interpretazioni adottate).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 05 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && ruff check . && python -m pytest -q` → verde.
2. Reale (rete, DB con artisti matchati dalle fasi precedenti):
   - Imposta discovery_from_date a 90 giorni fa: UPDATE settings SET value='<data>' WHERE key='discovery_from_date'.
   - Login → POST /api/v1/scans/releases → attendi (polling GET /scans/status) → riporta stats reali
     (artists_processed, releases_new, api_calls, duration_s).
   - Verifica temporale: duration_s deve essere ≥ api_calls - 1 secondi (prova rate limit 1/s).
   - Query: SELECT type, COUNT(*) FROM releases GROUP BY type; SELECT COUNT(*) FROM release_artists WHERE role='featured'
     → se hai artisti mainstream, entrambi > 0 idealmente; riporta i numeri reali comunque.
   - GET /api/v1/releases?page=1&page_size=10 → 10 item, total coerente, matched_artists popolato.
   - GET /api/v1/releases/{id} → poi GET /releases?seen=no → quell'id non deve più comparire.
   - POST /releases/seen-all {} → updated > 0; GET /releases?seen=no → total 0.
3. POST /api/v1/scans/feat → se feat_scan_enabled=true deve partire (puoi interrompere dopo 1 min:
   kill server; verifica che scan_runs registri lo stato coerente e che al riavvio non ci siano lock bloccati).
4. Dedup: rilancia POST /scans/releases → releases_new deve essere 0 (o solo vere novità), nessun errore UNIQUE.
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un reviewer senior (backend Python async + API design). Revisiona la fase 05 di nucs.
1. Leggi piano/00-specifiche.md §7 §8 §10 §4 e piano/checklist-sicurezza.md (B1, B2).
2. Diff: `git diff main...HEAD`. Concentrati su services/discovery.py, dates.py, musicbrainz.py, api/releases.py.
3. Caccia attivamente questi bug tipici:
   - paginazione search/browse MB errata (offset/limit/count, loop infiniti, risultati persi);
   - rate limit 1 req/s violabile in qualche percorso (retry che bypassa il limiter, chiamate parallele);
   - date parziali confrontate come stringhe (bug sottili: "2024" < "2024-06-01"?);
   - cursore last_release_check che fa perdere release (finestra −7gg rispettata?) o riesegue tutto;
   - upsert che sovrascrive dati o viola UNIQUE rgid in concorrenza;
   - role primary/featured errato su artist-credit-phrase con join phrases ("A & B feat. C");
   - query N+1 sull'endpoint lista; filtro q con injection (LIKE escape % _); seen side-effect su GET
     non idempotente verso bot/crawler (accettabile qui, ma conferma che sia documentato);
   - livello 2: memoria esplosa su artisti con migliaia di recording; lock scan non rilasciato su eccezione.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file:riga | problema | fix). Zero → "REVIEW PULITA" + elenco controlli.
```

Follow-up fix identico allo schema della fase 02 (incolla findings al modello implementatore, fix minimi, riverifica completa).

## 6. Criteri di completamento

- [ ] Test verdi (date parziali, paginazione, cursore, livello 2, API).
- [ ] Su dati reali: release trovate, rate limit rispettato (durata ≥ chiamate), dedup confermato al secondo run.
- [ ] Review avanzata: zero ALTA/MEDIA aperti.
- [ ] STATO.md aggiornato; commit e push: `feat(discovery): release discovery engine with featuring detection`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-06-link-e-cover`.
3. Apri `piano/fasi/fase-06-link-e-cover.md`.

> Se vuoi i **link diretti Spotify** (opzionale), crea ORA un'app su https://developer.spotify.com/dashboard
> (Client ID + Client Secret): li inserirai poi dalla pagina Impostazioni. Non serve per completare la fase 06.
