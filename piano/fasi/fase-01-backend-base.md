# FASE 01 — Backend base: FastAPI, config, SQLite, migrazioni, health

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 00
- **Branch**: `git checkout -b fase-01-backend-base`

---

## 1. Obiettivo

Backend avviabile con: configurazione da env (pydantic-settings), connessione SQLite in WAL,
**tutte le tabelle del modello dati (§4)** create via Alembic, endpoint pubblico `/api/health`,
logging strutturato. Nessuna autenticazione ancora (fase 02).

## 2. Prerequisiti

- Fase 00 completata e mergiata.
- Python 3.12 disponibile in locale per lo sviluppo (`python3.12 -m venv .venv`).

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md  (FONTE DI VERITÀ: stack §2, modello dati §4, API §10 per /api/health,
  struttura §3, env §12.3)
- piano/README.md §4 (regole globali)
- piano/STATO.md
Lavora sul branch corrente (fase-01). Modifiche minime. Codice/commenti in inglese.

OBIETTIVO
Backend FastAPI avviabile con config, DB SQLite+WAL, schema completo via Alembic, /api/health.

COMPITI
1. backend/requirements.txt (versioni ESATTE, prendi le ultime stabili compatibili con py3.12):
   fastapi, uvicorn[standard], sqlalchemy>=2, alembic, pydantic, pydantic-settings.
   requirements-dev.txt: pytest, pytest-asyncio, httpx, pytest-cov, ruff.
   Annota in piano/STATO.md le versioni scelte.
2. backend/app/config.py: classe Settings (pydantic-settings) che legge da env/.env:
   ADMIN_USERNAME, ADMIN_PASSWORD (opzionale, default vuota), DATA_DIR (default ./data),
   COVERS_DIR (default {DATA_DIR}/covers), MUSIC_LIBRARY_PATH (default ./music), TZ, LOG_LEVEL,
   DEV_INSECURE_COOKIES (bool, default False), TRUSTED_PROXY_CIDRS (str).
   Validazioni: DATA_DIR e COVERS_DIR creati se mancanti (mkdir parents=True, exist_ok=True).
3. backend/app/db.py: engine SQLite su {DATA_DIR}/app.db con PRAGMA journal_mode=WAL,
   foreign_keys=ON, busy_timeout=5000; session factory; get_db dependency FastAPI.
4. backend/app/models.py: TUTTE le tabelle di piano/00-specifiche.md §4, con nomi colonne,
   tipi, PK, UNIQUE, indici ESATTAMENTE come specificato (artists, releases, release_artists,
   release_state, settings, sessions, audit_log, scan_runs, scan_files).
   Per artists aggiungi anche la colonna `last_release_check TEXT NULL` (cursore discovery, §8.1).
5. Alembic: alembic init in backend/alembic, env.py puntato ai metadata dei models,
   prima migration autogenerate che crea tutto; in app startup (lifespan) esegui
   `alembic upgrade head` programmaticamente. Inserisci anche i default di `settings` (§4)
   come dati iniziali se la tabella è vuota (discovery_from_date = oggi-30gg calcolato a runtime).
6. backend/app/main.py: create_app() con lifespan (init dirs, alembic upgrade, log avvio),
   router /api/health pubblico → {"status":"ok","version":"1.0.0"}; logging key=value su stdout
   con livello da config; handler eccezioni globale → 500 {"detail":"Errore interno"} (log full traceback server-side).
7. Test backend/tests/test_health.py e test_db.py: health 200 + shape risposta; engine in WAL mode;
   tutte le tabelle §4 esistono dopo migrazione (usa DATA_DIR tmp_path, env override via monkeypatch).
8. Istruzioni di avvio dev: uvicorn app.main:app --reload da backend/ (scrivile in STATO.md).

VINCOLI
- Niente auth, niente middleware di sicurezza: fase 02.
- Niente codice di scan/discovery: fasi successive.
- Non modificare nulla sotto piano/ tranne STATO.md.
- requirements con == (niente >=) dopo aver verificato che l'installazione funziona.

DELIVERABLE
Report file creati/modificati + output dei test + aggiornamento piano/STATO.md (fase 01).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 01 di nucs. Esegui OGNI controllo e riporta tabella PASS/FAIL con evidenza:
1. `cd backend && python3.12 -m venv /tmp/nucs-venv && /tmp/nucs-venv/bin/pip install -r requirements.txt -r requirements-dev.txt -q && echo INSTALL_OK`
2. `/tmp/nucs-venv/bin/ruff check . && /tmp/nucs-venv/bin/ruff format --check .` → exit 0.
3. `/tmp/nucs-venv/bin/python -m pytest -q` → tutti verdi.
4. Avvio reale: `cd backend && DATA_DIR=/tmp/nucs-data /tmp/nucs-venv/bin/uvicorn app.main:app --port 18099 &`
   poi `curl -s http://127.0.0.1:18099/api/health` → deve rispondere {"status":"ok","version":"1.0.0"}.
   Poi kill del processo.
5. `/tmp/nucs-venv/bin/python -c "import sqlite3;c=sqlite3.connect('/tmp/nucs-data/app.db');print(c.execute('PRAGMA journal_mode').fetchone());print(sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"`
   → journal_mode wal; tabelle presenti: artists, releases, release_artists, release_state, settings,
   sessions, audit_log, scan_runs, scan_files, alembic_version.
6. Controlla che in settings ci siano le chiavi default di §4 (query SELECT key FROM settings).
7. `grep -rn "password\|secret\|token" backend/app --include=*.py` → nessun valore hardcoded.
Se FAIL: correggi e riesegui TUTTO da capo (anche l'installazione in venv pulito).
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 01 di nucs.
1. Leggi piano/00-specifiche.md §2 §3 §4 §10 (riga /api/health) e piano/checklist-sicurezza.md (B2, C, E).
2. Esamina il diff della fase (`git diff main...HEAD`).
3. Punti di attenzione: schema DB conforme colonna per colonna a §4 (nomi, unique, indici);
   nessuna query SQL concatenata; versioni pinnate; config senza default insicuri;
   migrazione riproducibile da DB vuoto; niente codice fuori scope (auth, scan, discovery).
4. Output: tabella findings (gravità ALTA/MEDIA/BASSA, file, problema, fix). Se zero: "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Tutti i controlli di verifica PASS.
- [ ] Schema DB conforme a §4 (inclusa `artists.last_release_check`).
- [ ] Review pulita o findings risolti.
- [ ] `piano/STATO.md` aggiornato (con versioni dipendenze).
- [ ] Commit e push: `feat(backend): base app with config, sqlite schema, migrations, health endpoint`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-02-auth`.
3. Apri `piano/fasi/fase-02-auth.md`. **Nota**: la review di quella fase va fatta con un modello avanzato.
