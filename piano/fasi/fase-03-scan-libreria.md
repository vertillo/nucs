# FASE 03 — Scansione libreria musicale ed estrazione artisti

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 02
- **Branch**: `git checkout -b fase-03-scan-libreria`

---

## 1. Obiettivo

Servizio che percorre la cartella musica (read-only), legge i tag con mutagen e popola la tabella
`artists` con: artisti traccia, album artist, featuring (da titolo e tag), contributi
(performer/composer/remixer). Incrementale via tabella `scan_files`. Endpoint per avviare lo scan
e vederne lo stato.

> **Decisione operativa su §6.4** (registrare in STATO.md): in questa fase si splitta **solo**
> sul separatore `;` (sicuro, usato dai tagger per valori multipli) e si estraggono i featuring
> dal titolo. Lo split "morbido" (`feat.`, `&`, `,`…) avviene nella **fase 04** dopo il tentativo
> di match MusicBrainz del nome intero (regola match-first). Così "AC/DC" e "Earth, Wind & Fire"
> non vengono spezzati per errore.

## 2. Prerequisiti

- Fasi 01-02 mergiate.
- Una cartella di prova con file musicali taggati (anche 20-30 file bastano).

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §6 (scansione, TUTTA), §4 (artists, scan_files, scan_runs), §10 (endpoint /scans/*)
- piano/README.md §4
- piano/STATO.md
Branch corrente: fase-03. Codice/commenti inglese. Decisione operativa già approvata su §6.4:
split duro solo su ';' in questa fase + featuring dal titolo; split morbidi rimandati alla fase 04
dopo match-first MusicBrainz. NON implementare i soft-split ora.

OBIETTIVO
Servizio di scansione libreria + estrazione artisti + endpoint scan.

COMPITI
1. Aggiungi a requirements.txt: mutagen (versione esatta).
2. backend/app/services/names.py:
   - normalize_name(s) ESATTAMENTE come §6.3 (NFKD, strip combining, lower, no punteggiatura, collapse spazi).
   - extract_feat_from_title(title) → lista nomi: regex case-insensitive su parentesi tonde/quadre
     contenenti feat.|ft.|featuring|con seguito dai nomi; split dei nomi interni su ',', '&', ' e '.
     Gestisce anche suffisso finale senza parentesi " - feat. X"? NO: solo parentesi (documentato).
   - is_trivial_artist(name): filtra "various artists", "aa.vv.", "unknown artist", "unknown", nomi < 2 char (§6.4.6).
3. backend/app/services/library_scan.py:
   - walk ricorsivo di settings.MUSIC_LIBRARY_PATH (solo estensioni .mp3 .flac .m4a .mp4 .ogg .opus;
     case-insensitive). Segui symlink? NO. Errori lettura file → warning log + contatore, mai eccezione.
   - Per ogni file legge con mutagen (File easy=False): artista traccia, album artist, titolo,
     performer/composer/remixer secondo mappatura §6.2. Valori multipli (lista) → ogni valore è un nome.
     Su ogni campo: split SOLO su ';'. Trim. Scarta trivial.
   - Dal titolo: extract_feat_from_title → source tag_feat.
   - Mappa source: TPE1/ARTIST/©ART → tag_artist; TPE2/ALBUMARTIST/aART → tag_albumartist;
     performer/composer/remixer → tag_contrib; feat da titolo → tag_feat.
   - Upsert in artists su normalized_name: se esiste già NON sovrascrivere source (se nuovo source è
     tag_albumartist o tag_artist e il vecchio era tag_feat/tag_contrib → aggiorna a quello "più forte").
   - Incrementale: tabella scan_files(path, mtime, size); salta file invariati; parametro full=False
     per forzare (cancella scan_files).
   - Registra scan_runs con stats JSON: {files_seen, files_parsed, files_skipped, files_error,
     artists_new, artists_total, duration_s}.
   - La cartella è READ-ONLY: mai scriverci (test automatico che lo provi con dir a permessi 444? no —
     semplicemente non esiste alcuna write su quel path nel codice: assicurarsene).
4. backend/app/api/scans.py (protetto da require_user):
   - POST /api/v1/scans/library → avvia scan in background task asyncio (guard: 409 {"detail":"Scan already in progress"} se attivo).
   - GET /api/v1/scans/status → {running: null|{type,since}, last_runs: [ultimi 10 da scan_runs]}.
   - Il service espone un lock asyncio globale per tipo di scan.
5. CLI: `python -m app.cli scan-library [--full]` per uso da terminale.
6. Test (backend/tests/test_library_scan.py):
   - Crea in tmp_path file SINTETICI con mutagen: mp3? NO — usa FLAC e M4A e OGG (più semplici da
     scrivere programmaticamente; per mp3 usa mutagen.id3): almeno: (a) album artist diverso da artist;
     (b) titolo "Canzone (feat. Qualcuno)"; (c) artist multiplo "A; B"; (d) PERFORMER valorizzato;
     (e) file corrotto (bytes casuali .flac) → contato in files_error senza eccezioni.
   - Asserzioni: artisti attesi presenti con source corretta; re-scan senza modifiche → files_skipped>0;
     normalize_name("Beyoncé") == "beyonce"; extract_feat casi (feat./ft./featuring/con, parentesi quadre);
     trivial filtrati.
7. Aggiorna .env.example se serve (MUSIC_LIBRARY_PATH c'è già).

VINCOLI
- Niente chiamate di rete in questa fase (MusicBrainz è fase 04).
- Niente match/split morbidi: SOLO ';' e feat da titolo.
- Scan in background non deve bloccare l'event loop: mutagen è sync → esegui in asyncio.to_thread / run_in_executor.

DELIVERABLE
Report + output test + aggiornamento piano/STATO.md (fase 03, includi la decisione operativa §6.4).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 03 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && /tmp/nucs-venv/bin/pip install -r requirements.txt -q && ruff check . && python -m pytest -q` → verde.
2. Test su libreria reale di prova: `MUSIC_LIBRARY_PATH=<cartella_prova> DATA_DIR=/tmp/nucs-d3 python -m app.cli create-admin admin 'password-lunga-123' && MUSIC_LIBRARY_PATH=<cartella_prova> DATA_DIR=/tmp/nucs-d3 python -m app.cli scan-library --full`
   → riporta stats (files_seen/parsed/error, artists_new). files_error deve essere 0 su una libreria sana.
3. Query: `SELECT source, COUNT(*) FROM artists GROUP BY source` → mostra conteggi; verifica a campione
   3 artisti noti presenti nei tuoi file e almeno 1 artista con source tag_feat se i tuoi file hanno featuring.
4. Rilancia scan-library SENZA --full → files_skipped ≈ files_seen, artists_new = 0.
5. Via API: avvia server, login (cookie), POST /api/v1/scans/library con header X-Requested-With → 200/202;
   secondo POST immediato → 409; GET /api/v1/scans/status → mostra last_runs popolato.
6. `ls -la <cartella_prova>` prima/dopo → nessun file creato/modificato dall'app (confronta mtime).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 03 di nucs.
1. Leggi piano/00-specifiche.md §6 e §4 e piano/checklist-sicurezza.md (B1-B3, F4).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: regex featuring (falsi positivi/negativi sui casi §6.4), normalize_name conforme §6.3,
   nessuna scrittura sulla libreria (F4), path traversal (B3 — i path arrivano solo da os.walk su una
   root da env, mai da input API), gestione eccezioni mutagen, nessun blocco dell'event loop,
   upsert senza race condition, stats coerenti.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero findings → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Test sintetici verdi (feat, multi-artista, contributi, file corrotto, incrementale).
- [ ] Scan reale su cartella di prova: artisti attesi presenti, zero errori, zero scritture sulla libreria.
- [ ] Endpoint scan + 409 concorrenza funzionanti.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(library): music folder scan with tag parsing and artist extraction`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-04-matching-artisti`.
3. Apri `piano/fasi/fase-04-matching-artisti.md`.
