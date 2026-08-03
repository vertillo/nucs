# STATO DEL PROGETTO — diario di avanzamento

> Questo file viene aggiornato dal modello alla fine di ogni fase.
> Ogni prompt di fase inizia leggendo questo file + `piano/00-specifiche.md`.
> Formato: una sezione per fase completata, più recente in cima.

## Riepilogo rapido

- Fase corrente: **01 (completata)** → prossima: 02
- Fasi completate: 00, 01
- Branch attivo: `fase-01` (da merge su main dopo review)
- Problemi aperti: warning deprecazione `httpx2` da `fastapi.testclient` (non bloccante)
- Idee emerse ma rimandate (v2): nessuna

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
