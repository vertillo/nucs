# FASE 02 — Autenticazione, sessioni, rate limiting, header di sicurezza

- **Implementazione**: modello economico (il prompt è molto dettagliato; non deviare)
- **Review**: **modello AVANZATO obbligatorio** (è la fase di sicurezza critica)
- **Dipende da**: fase 01
- **Branch**: `git checkout -b fase-02-auth`

---

## 1. Obiettivo

Sistema di login completo e sicuro come da §5 delle specifiche: utente admin unico, sessioni
opache in cookie, rate limiting anti brute-force, middleware header di sicurezza, protezione
CSRF (Origin check + header custom), audit log, endpoint `/auth/*`, CLI `create-admin`.

## 2. Prerequisiti

- Fase 01 mergiata: DB, models (sessions, audit_log già esistono), config, health funzionanti.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta SENZA ECCEZIONI:
- piano/00-specifiche.md  — in particolare §5 (sicurezza, TUTTA vincolante), §10 (endpoint /auth/*), §4 (sessions, audit_log)
- piano/README.md §4
- piano/STATO.md
Lavora sul branch corrente (fase-02). Codice/commenti inglese. Modifiche minime ai file esistenti.

OBIETTIVO
Implementare autenticazione e protezioni di base esattamente come da §5.

COMPITI
1. Aggiungi a requirements.txt (versioni esatte): argon2-cffi, python-multipart.
2. backend/app/security.py:
   - hash/verify password con argon2id (argon2-cffi, parametri default; memory_cost min 32MB).
   - HASH DUMMY precalcolato a modulo per verifica tempo costante quando lo username non esiste.
   - create_session(db, ip, ua) → token = secrets.token_urlsafe(32); salva SOLO sha256(token)
     in sessions con expires_at = now+7gg; restituisce il token in chiaro (solo per il cookie).
   - verify_session(db, token) → controlla hash, scadenza; rolling: se mancano <3gg rinnova expires_at.
   - revoke_session, revoke_other_sessions, cleanup_expired_sessions.
   - Rate limiter login IN-MEMORIA (finestra scorrevole): max 5 tentativi/5min per IP;
     dopo 10 fallimenti consecutivi globali → blocco TUTTI i login 15 min (HTTP 429 + Retry-After).
     I contatori si resettano su login riuscito.
3. Middleware in main.py (ordine: dopo routing, prima degli handler):
   a. SecurityHeadersMiddleware: applica TUTTI gli header di §5.5 su ogni risposta
      (HSTS solo se request.url.scheme == "https"), più X-Robots-Tag: noindex, rimuovi Server/X-Powered-By.
   b. OriginCheckMiddleware: su POST/PUT/PATCH/DELETE verifica header X-Requested-With == "XMLHttpRequest"
      E (Origin o Referer) con host uguale a request.headers["host"] → altrimenti 403 {"detail":"Forbidden"}.
      Eccezione: nessuna (anche /auth/login la rispetta: il frontend la includerà).
   c. Risoluzione IP client: se request.client.host è dentro TRUSTED_PROXY_CIDRS (ipaddress module),
      usa ultimo IP di X-Forwarded-For; altrimenti request.client.host.
4. backend/app/api/auth.py (prefix /api/v1/auth):
   - POST /login {username,password}: rate limit → 401 generico "Invalid credentials" su fallimento
     (con hash dummy verify); su successo: audit login_ok, 204 con Set-Cookie nucs_session (HttpOnly,
     SameSite=Lax, Path=/, Secure salvo DEV_INSECURE_COOKIES, Max-Age=604800).
   - POST /logout: revoca, cancella cookie, 204. GET /me → {"username": ..., "theme": <da settings>}.
   - POST /password {current_password,new_password}: verifica attuale, policy min 12 char, ri-hash,
     revoca TUTTE le altre sessioni, audit password_change → 204.
   - GET /sessions → lista [{id (hash troncato a 8 char), ip, user_agent, last_seen_at, current: bool}].
   - POST /sessions/revoke-others → 204.
5. backend/app/deps.py: require_user dependency → legge cookie nucs_session, verify_session,
   401 {"detail":"Not authenticated"} se assente/invalida; aggiorna last_seen_at.
6. Proteggi TUTTI i router futuri: per ora crea un router placeholder /api/v1/releases vuoto? NO —
   niente placeholder. Semplicemente esporta require_user pronto all'uso.
7. CLI backend/app/cli.py: comando `create-admin <username> <password>` (argparse) che crea l'utente
   (tabella settings chiave `admin_username` + `admin_password_hash`); al boot, se manca la chiave
   admin_username: se ADMIN_USERNAME+ADMIN_PASSWORD da env sono presenti → crea admin e logga
   "admin created from env"; altrimenti → sys.exit con messaggio chiaro. Policy password anche qui.
8. Audit helper services/audit.py: log_event(db, event, ip, detail:dict) → mai password/token.
9. robots.txt servito su /robots.txt: "User-agent: *\nDisallow: /".
10. Test (backend/tests/test_auth.py + test_security.py): copri TUTTI i punti A1-A8 della
    piano/checklist-sicurezza.md sezione A + B6/B7: login ok/ko identico messaggio, rate limit IP
    (6° tentativo → 429), blocco globale, cookie flags, sessione revocata → 401, cambio password
    revoca altre sessioni, header sicurezza presenti, 403 senza X-Requested-With, 401 senza cookie.
    Usa httpx AsyncClient + ASGITransport.

VINCOLI
- Messaggi di errore UTENTE in inglese (come da §5.3: "Invalid credentials", "Not authenticated", ecc.), codice in inglese.
- Mai loggare password/token/cookie: grep finale di controllo.
- Niente JWT: sessioni opache server-side, come da §5.2. Niente dipendenze extra (no slowapi).
- Se §5 ti sembra ambiguo su un punto, fermati e scrivi il dubbio in STATO.md con l'interpretazione scelta.

DELIVERABLE
Report + output test + grep prova assenza segreti nei log + aggiornamento piano/STATO.md (fase 02).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 02 di nucs. Tabella PASS/FAIL con evidenza per OGNI controllo:
1. `cd backend && /tmp/nucs-venv/bin/pip install -r requirements.txt -q && /tmp/nucs-venv/bin/ruff check . && /tmp/nucs-venv/bin/python -m pytest -q` → tutto verde.
2. Avvio senza admin: `DATA_DIR=/tmp/nucs-d2a /tmp/nucs-venv/bin/uvicorn app.main:app --port 18099 &` →
   il processo deve uscire con messaggio che spiega come creare l'admin (o creare admin da env se forniti). Verifica entrambi i percorsi.
3. Avvio con env ADMIN_USERNAME=admin ADMIN_PASSWORD='una-password-lunga-123':
   - `curl -si -X POST localhost:18099/api/v1/auth/login -H 'Content-Type: application/json' -H 'X-Requested-With: XMLHttpRequest' -H 'Origin: http://localhost:18099' -d '{"username":"admin","password":"sbagliata-lunga-123"}'` → 401, body {"detail":"Invalid credentials"}.
   - stesso comando con password giusta → 204 + Set-Cookie con HttpOnly e SameSite=Lax. Salva il cookie.
   - `curl -s localhost:18099/api/v1/auth/me` SENZA cookie → 401. CON cookie → 200 {"username":"admin",...}.
   - senza header X-Requested-With sul login → 403.
   - 6 tentativi sbagliati consecutivi → il 6° deve dare 429 con header Retry-After.
   - verifica header di sicurezza: `curl -si localhost:18099/api/health | grep -iE 'content-security|x-content-type|x-frame|referrer-policy|x-robots'` → tutti presenti.
   - `curl -s localhost:18099/robots.txt` → Disallow: /.
4. Ispeziona il DB: `SELECT id FROM sessions` → nessun token in chiaro (solo hash esadecimali 64 char).
5. `grep -rniE "log.*(password|token|cookie)" backend/app` → nessun risultato pericoloso.
6. Kill del server. Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un security reviewer senior. Revisiona la fase 02 (autenticazione) del progetto nucs.
1. Leggi: piano/00-specifiche.md §5 e §10, piano/checklist-sicurezza.md (TUTTE le sezioni, focus A/B/C/F).
2. Esamina il diff: `git diff main...HEAD`.
3. Valuta OGNI punto A1-A8, B1-B7, C1-C4, F1-F3 della checklist come ✅/❌/➖ con evidenza (file:riga).
   Cerca attivamente: timing attack sul login, session fixation, token in chiaro, cookie flags errati,
   rate limit aggirabile (es. reset per richiesta), origin check con parse errato del Referer,
   IP spoofing via X-Forwarded-For non fidato, eccezioni che leakano stack trace, password policy
   non applicata al cambio, audit log con dati sensibili.
4. Output: tabella findings (gravità ALTA/MEDIA/BASSA | file:riga | problema | fix concreto).
   Le gravità ALTA/MEDIA sono bloccanti. Se zero findings: "REVIEW PULITA" + elenco controlli eseguiti.
```

Dopo la review, se ci sono findings ALTA/MEDIA, dai questo follow-up al modello implementatore:

```text
La security review della fase 02 ha prodotto questi findings bloccanti: <incolla tabella>.
Applica i fix minimi richiesti, senza toccare altro codice. Riesegui poi l'intera verifica di fase 02
(tutti i comandi) e riporta l'esito.
```

## 6. Criteri di completamento

- [ ] Tutti i punti A1-A8, B6, B7 della checklist risultano ✅ in review.
- [ ] Verifica manuale (curl) tutta PASS.
- [ ] Test pytest verdi (inclusi rate limit e revoca sessioni).
- [ ] Review avanzata: zero ALTA/MEDIA aperti.
- [ ] `piano/STATO.md` aggiornato.
- [ ] Commit e push: `feat(auth): opaque sessions, argon2id login, rate limiting, security headers`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-03-scan-libreria`.
3. Apri `piano/fasi/fase-03-scan-libreria.md`.

> Prima di procedere, se non l'hai già fatto: prepara una **sottocartella di prova** con qualche
> decina di file musicali reali (copie) — servirà per la verifica della fase 03.
