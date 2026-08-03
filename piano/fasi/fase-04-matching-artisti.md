# FASE 04 — Abbinamento artisti → MusicBrainz ID (+ split morbidi)

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 03
- **Branch**: `git checkout -b fase-04-matching-artisti`

---

## 1. Obiettivo

Client MusicBrainz "educato" (User-Agent, 1 req/s, retry) e servizio che abbina ogni artista al suo
MBID: prima il nome intero (**match-first**, §6.4.4); se non matcha e il nome contiene separatori
"morbidi" (` feat. `, ` ft. `, ` featuring `, ` & `, `, `, ` vs `, ` with `, ` con `) → split e match
delle parti. Espone anche le API `/artists/*` (lista, aggiunta manuale, ignora, rematch).

## 2. Prerequisiti

- Fase 03 mergiata: tabella `artists` popolata dal tuo scan di prova.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §7 (MusicBrainz galateo, TUTTO vincolante), §6.4 (match-first), §10 (/artists/*)
- piano/README.md §4
- piano/STATO.md
Branch: fase-04. Codice/commenti inglese. Modifiche minime.

OBIETTIVO
Client MusicBrainz + matching artisti→MBID con regola match-first + soft-split + API /artists/*.

COMPITI
1. Aggiungi a requirements.txt: httpx, tenacity (versioni esatte).
2. backend/app/services/musicbrainz.py — client async:
   - Base URL e User-Agent ESATTAMENTE come §7 (email da settings mb_contact_email, fallback "selfhosted").
   - Rate limiter GLOBALE: token bucket 1 richiesta/secondo verso musicbrainz.org (asyncio.Lock +
     timestamp ultima richiesta; semplice e corretto).
   - GET helper con fmt=json, retry tenacity su 429/5xx/network error: backoff esponenziale 1s→2s→4s→8s, max 5 tentativi, poi eccezione MBError custom.
   - Metodi: search_artist(name, limit=5), get_artist_release_groups(...) lasciato stub? NO: solo ciò che serve ORA: search_artist.
   - Timeout 15s. Niente cache in questa fase.
3. backend/app/services/mb_matching.py:
   - match_artist(db, artist_row) → search_artist(name); prendi il best score;
     score >= 90 → salva mbid + mb_match_score, ritorna True.
     Altrimenti SOFT-SPLIT (§6.4.3): prova a splittare name sui separatori: " feat. ", " ft. ",
     " featuring ", " & " (solo con spazi), ", " (solo se produce 2+ parti plausibili: ogni parte ≥2 char),
     " vs ", " with ", " con " (tutti case-insensitive, spazi obbligatori).
     Per OGNI parte: is_trivial_artist? skip; cerca su MB (score>=85 → mbid); upsert nuova riga artists
     (normalized_name dedup; source = source del padre; se esiste già, aggiorna solo mbid se assente).
     Se almeno 1 parte matchata → padre: ignored=1 (sostituito dalle parti), mb_match_score=NULL. Ritorna True.
     Se nessuna parte matcha → padre resta senza mbid (verrà mostrato "non abbinato" in UI). Ritorna False.
   - match_all_pending(db, limit=100) → processa artisti con mbid NULL e ignored=0, rispettando il rate limit; stats {processed, matched, split, unmatched}.
4. API backend/app/api/artists.py (require_user):
   - GET /api/v1/artists?ignored=all|yes|no&q=&page=&page_size= → items con {id,name,source,mbid,
     mb_match_score,ignored,releases_count(0 per ora, sarà popolato in fase 05)}; ordinamento name ASC.
   - POST /api/v1/artists {name} → 400 se trivial/duplicato (normalized); crea con source=manual +
     tentativo match immediato (in background task, non bloccare la risposta: 202 con l'artista).
   - PATCH /api/v1/artists/{id} {ignored} → 200 artista aggiornato; 404 se manca.
   - POST /api/v1/artists/{id}/rematch → riesegue match_artist (rispetta rate limit) → {matched: bool, mbid}.
5. Integrazione scan: alla fine di POST /scans/library NON lanciare match automatico (resta manuale via
   POST /scans/{type}? NO — aggiungi POST /api/v1/scans/match? I tipi ammessi da §10 sono library|releases|feat.
   DECISIONE (registrare in STATO.md): il match viene eseguito automaticamente alla fine dello scan libreria
   (solo per artisti pending, cap 100/run) E manualmente via POST /artists/{id}/rematch. Non aggiungere nuovi tipi di scan.
6. Test (test_mb_matching.py): mock di httpx (respx? NO — monkeypatch del metodo GET del client):
   - match diretto score>=90; nome con " feat. " senza match intero → split, parti matchate, padre ignored;
   - "Earth, Wind & Fire" match intero → NESSUNO split (caso chiave!);
   - nessun match → mbid NULL; rate limiter: 3 chiamate impiegano ≥2s (usa clock fake? semplice:
     monkeypatch asyncio.sleep e verifica che sia chiamato con ~1.0); retry su 429.
   - API: lista, filtri, aggiunta manuale duplicato → 400, rematch 404.

VINCOLI
- MAI superare 1 req/s verso MusicBrainz, anche nei test (mockare il transport, non il rate limiter…
  oppure mockare sleep: decidi e documenta; l'importante è che il codice di produzione rispetti §7).
- User-Agent sempre presente (test che lo asserisca).
- Niente modifiche a discovery (fase 05).

DELIVERABLE
Report + output test + aggiornamento piano/STATO.md (fase 04).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 04 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && /tmp/nucs-venv/bin/pip install -r requirements.txt -q && ruff check . && python -m pytest -q` → verde.
2. Reale (richiede rete): avvia app con DB della fase 03 (o riesegui scan su cartella prova), login, poi:
   `POST /api/v1/scans/library` (attendi fine) → poi query `SELECT COUNT(*) total, COUNT(mbid) matched FROM artists WHERE ignored=0`
   → matched deve essere > 0 (su una libreria mainstream, tipicamente >60%). Riporta i numeri reali.
3. Campione: `SELECT name, mbid, mb_match_score FROM artists WHERE mbid IS NOT NULL LIMIT 5` → verifica
   a mano su https://musicbrainz.org che 2 MBID corrispondano davvero all'artista (incolla gli URL MB).
4. Soft-split: trova un artista splittato: `SELECT name, ignored FROM artists WHERE ignored=1` → verifica
   che il padre contenga un separatore e che le parti esistano come righe proprie.
5. API: GET /api/v1/artists?q=<nome> → filtra; PATCH ignored → riflesso nel GET; POST /artists {"name":"Radiohead"} → 202; POST /artists/{id}/rematch su artista non abbinato → risposta coerente.
6. Timing: misura con `time` 5 rematch consecutivi → deve impiegare ≥4 secondi totali (prova rate limit 1/s).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 04 di nucs.
1. Leggi piano/00-specifiche.md §6.4 §7 §10 e piano/checklist-sicurezza.md (B1, B2).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: rispetto rate limit in TUTTI i percorsi (anche errori/exception nel mezzo), regex
   soft-split (nessuno split su "&" senza spazi, niente split di "AC/DC"), match-first rispettato,
   upsert senza duplicare normalized_name, gestione retry/timeout, nessuna chiamata MB bloccante
   nell'event loop (httpx async ok), input API validati.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Test verdi inclusi: caso "Earth, Wind & Fire" (no split), retry 429, rate limit.
- [ ] Su dati reali: >0 artisti abbinati, 2 MBID verificati a mano corretti.
- [ ] API /artists/* funzionanti via curl.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(artists): MusicBrainz matching with match-first and soft-split`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-05-discovery-release`.
3. Apri `piano/fasi/fase-05-discovery-release.md`. **Nota**: review con modello avanzato.
