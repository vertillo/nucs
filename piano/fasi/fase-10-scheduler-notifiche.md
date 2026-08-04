# FASE 10 — Scheduler automatico, backup DB, notifiche Apprise

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 09b
- **Branch**: `git checkout -b fase-10-scheduler-notifiche`

---

## 1. Obiettivo

L'app diventa autonoma: scan libreria e discovery partono da soli agli orari configurati
(APScheduler), il DB viene backuppato ogni notte (retention 7), e — se abilitato — arriva una
notifica Apprise aggregata quando vengono scoperte nuove release.

## 2. Prerequisiti

- Fase 09b mergiata. (Opzionale) URL Apprise reale per il test: da fase 09b può essere
  fornito al **primo avvio** del backend di test con `NOTIFY_URLS` (vedi `.env.example`),
  senza reinserimenti manuali via UI (il seed env vale solo su DB vuoto, §5.1).

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §2 (APScheduler), §4 (settings orari), §8.4.3 (notifica aggregata),
  §1.2 (backup retention 7), §10 (/settings/notify-test)
- piano/README.md §4
- piano/STATO.md
Branch: fase-10. Codice/commenti inglese.

OBIETTIVO
Scheduler + backup + notifiche.

COMPITI
1. requirements.txt: aggiungi apscheduler>=3,<4 (versione esatta), apprise (versione esatta).
2. backend/app/scheduler.py:
   - AsyncIOScheduler timezone=settings.TZ; avviato nel lifespan di main.py (dopo migrazioni),
     shutdown pulito all'uscita.
   - Job (coalesce=True, max_instances=1, misfire_grace_time=3600):
     * library_scan: CronTrigger daily HH:MM da settings.scan_library_time → services.library_scan
       (+ match pending come fase 04).
     * releases_scan: CronTrigger daily da settings.scan_releases_time → discovery livello 1.
     * feat_scan: CronTrigger weekly (weekday da feat_scan_weekday) SOLO se feat_scan_enabled → livello 2.
     * backup_db: daily 02:30 → services/backup.py.
     * cleanup_sessions: hourly → security.cleanup_expired_sessions.
   - Reschedule: su PUT /settings che tocca orari/weekday/feat_enabled → rileggi e rischedula
     (funzione refresh_jobs(scheduler, db) chiamata dall'endpoint).
   - I job riusano gli STESSI lock asyncio degli scan manuali (niente doppia esecuzione; se occupato:
     log INFO "skipped, already running").
3. backend/app/services/backup.py:
   - backup_now(db_path, backup_dir={DATA_DIR}/backups): usa sqlite3 backup API (connessione sorgente
     in lettura) → file app-YYYYMMDD-HHMMSS.db; retention: tieni gli ultimi 7, cancella i più vecchi.
   - CLI: `python -m app.cli backup-now`. Log dimensione e percorso. Mai bloccare l'event loop (to_thread).
4. backend/app/services/notify.py:
   - send_notification(title, body) → se notify_enabled e notify_urls: apprise.Apprise(), add ogni URL
     (split CSV, strip, salta vuoti), notify async? apprise è sync → to_thread; ritorna (ok: bool, errore: str).
   - Hook in discovery (fine run releases/feat): se stats.releases_new > 0 → notifica AGGREGATA
     (§8.4.3): title "nucs: {n} new releases", body con le prime 5 "Artist – Title (type, date)"
     + "…and {k} more". Mai una notifica per release.
   - Endpoint POST /api/v1/settings/notify-test (require_user) → send_notification("nucs",
     "Test notification") → {"sent": true} oppure 400 {"detail": errore in inglese} (es. nessun URL configurato).
5. Test (test_backup.py, test_notify.py, test_scheduler.py):
   - backup: crea file, retention 7 (crea 9 backup fake con nomi datati → dopo cleanup ne restano 7);
     DB backuppato apribile e integro (PRAGMA integrity_check).
   - notify: disabled → nessuna chiamata; enabled con URL finto → apprise chiamato (monkeypatch);
     aggregazione: releases_new=8 → 1 sola notifica con 5+1 righe.
   - scheduler: refresh_jobs cambia i trigger dopo PUT settings (ispeziona scheduler.get_jobs());
     job con lock occupato → skip senza eccezione.
6. STATO.md: documenta gli orari di default e il comportamento misfire.

VINCOLI
- Niente job duplicati al reload di config; scheduler.shutdown(wait=False) nel lifespan exit.
- I job NON devono partire durante i test pytest (fixture che disabilita lo scheduler; verifica esplicita).
- Apprise mai invocato se notify_enabled=false, neanche per il test endpoint (che però fallisce con
   messaggio chiaro se disabilitato: 400 {"detail":"Notifications are disabled"}).

DELIVERABLE
Report + output test + aggiornamento piano/STATO.md (fase 10).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 10 di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && /tmp/nucs-venv/bin/pip install -r requirements.txt -q && ruff check . && python -m pytest -q` → verde.
2. Backup reale: `DATA_DIR=<db> python -m app.cli backup-now` → file in backups/, apribile:
   `sqlite3 <file> "PRAGMA integrity_check;"` → ok. Esegui 8 volte (o crea file finti datati) → restano 7 file.
3. Scheduler reale: avvia l'app, imposta scan_releases_time tra 2 minuti via PUT /settings →
   attendi → GET /scans/status mostra un run releases avvenuto all'orario atteso (riporta log con timestamp).
   Cambia orario di nuovo → il vecchio trigger non resta attivo (verifica via log/STATO o /scans/status).
4. Lock: durante uno scan manuale avviato da API, fai scattare l'orario schedulato → nei log appare
   "skipped, already running".
5. Notifiche: PUT settings notify_enabled=false → POST notify-test → 400. Con URL Apprise REALE
   (se fornito dall'utente — da fase 09b puoi avviare il backend con `NOTIFY_URLS=...` su DB
   fresco e saltare la UI): enabled + URL → POST notify-test → 200 e notifica ricevuta sul dispositivo
   (riporta screenshot/descrizione). Poi lancia POST /scans/releases su DB con novità → 1 sola notifica aggregata.
   Nota: con notify_enabled=true di default (fase 09b), senza URL il notify-test risponde con un errore chiaro.
6. Restart app → nessun job duplicato nei log di avvio (elenca i job registrati).
Nota E2E: tutti i check di questa fase sono già automatici via API/curl/log (niente browser);
l'UNICO passo che richiede un umano è la **ricezione della notifica Apprise su un dispositivo
esterno** (punto 5, solo se l'utente fornisce un URL reale) — in quel caso riporta
screenshot/descrizione. Per la checklist manuale completa (incluse azioni avversarie) vedi fase 13.
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 10 di nucs.
1. Leggi piano/00-specifiche.md §2 §4 §8.4 §1.2 e piano/checklist-sicurezza.md (C3, C4).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: job duplicati dopo PUT settings, lock condivisi con scan manuali, scheduler assente
   nei test, backup con sqlite3 backup API (non copia file a caldo su DB in WAL senza checkpoint!),
   retention corretta, URL Apprise mai loggati (possono contenere token! C4), notifica aggregata (mai N notifiche),
   eccezioni nei job non fanno crashare lo scheduler.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] Scheduler verificato su orario reale; reschedule funzionante; lock rispettato.
- [ ] Backup integro con retention 7.
- [ ] Notifica test OK (o errore chiaro senza URL); aggregata verificata se possibile.
- [ ] Review pulita o findings risolti; STATO.md aggiornato.
- [ ] Commit e push: `feat(ops): scheduler, db backups, apprise notifications`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. `git checkout -b fase-11-docker-rete`.
3. Apri `piano/fasi/fase-11-docker-rete.md`. **Nota**: review con modello avanzato.

> Da qui in poi serve lavorare sul **mini PC** (o comunque sulla macchina con Docker) e avere:
> account Cloudflare con dominio + account Tailscale attivi.
