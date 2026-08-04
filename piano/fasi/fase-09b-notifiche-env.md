# FASE 09b — Notifiche: default attivo e seed da env (NOTIFY_URLS)

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: fase 09
- **Branch**: `git checkout -b fase-09b-notifiche-env` (da `main`; `fase-10-scheduler-notifiche` si riallinea da `main` dopo il merge)

---

## 1. Obiettivo

Notifiche Apprise **attive per default** (disattivabili dalla UI) e configurabili
**via ambiente** (`NOTIFY_URLS` / `NOTIFY_ENABLED`) senza passare dalle impostazioni,
con la semantica "primo avvio" di §5.1 (il DB vince dopo). Supporto a più provider
misti (Telegram `tgram://`, ntfy `ntfy://`) già garantito da Apprise e dalla lista CSV.

## 2. Prerequisiti

- Fase 09 mergiata (UI Settings → Notifications già presente).
- (Opzionale, per la verifica reale) un URL Apprise: `tgram://<token>/<chat_id>` oppure `ntfy://<topic>`.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §4 (default settings), §5.1 (env letto solo al primo avvio),
  §5.8 (segrete), §10 (GET/PUT /settings), §11.2.5 (sezione Notifications), §12.3 (.env.example)
- piano/README.md §4
- piano/STATO.md
Branch: fase-09b. Codice/commenti inglese, STRINGHE UI IN INGLESE.

OBIETTIVO
Notifiche attive di default (disattivabili) + seed delle URL Apprise da env al primo avvio.

COMPITI
1. backend/app/config.py: `notify_urls: str = ""` (env NOTIFY_URLS) e
   `notify_enabled: bool | None = None` (env NOTIFY_ENABLED; None = env assente,
   NON sovrascrive il default).
2. backend/app/main.py:
   - `_DEFAULT_SETTINGS["notify_enabled"]`: da "false" a "true" (deviazione da §4 —
     registrarla in piano/STATO.md).
   - `seed_settings_if_empty()`: SOLO se la tabella settings è vuota, applica gli
     override da env: NOTIFY_URLS non vuota → seed `notify_urls` (lista anche mista,
     una riga o virgola); NOTIFY_ENABLED esplicitamente impostata → seed quel valore.
     Log INFO con i SOLI nomi delle chiavi (mai i valori: possono contenere token).
   - Nessuna validazione bloccante al boot (URL malformati → errore all'invio, fase 10).
3. frontend/src/pages/Settings.tsx: guard di `sendTestNotification` basato SOLO sulla
   presenza di URL (`if (notify.urls.trim() === '')`) — con il default true lo switch
   non deve bloccare il messaggio "Add at least one Apprise URL first." (check E2E 09).
4. .env.example: aggiungere `NOTIFY_URLS=` e `NOTIFY_ENABLED=` con commento
   (opzionali; seed solo al primo avvio; supportano più URL anche misti).
5. Test (backend/tests): seed con NOTIFY_URLS → GET /settings valorizzato e
   notify_enabled "true"; senza env → notify_enabled "true" e notify_urls "";
   tabella già popolata → env ignorato; NOTIFY_ENABLED=false → seed "false".
6. Aggiorna piano/STATO.md (deviazione §4, semantica primo-avvio, estensione §12.3)
   e piano/fasi/fase-10-scheduler-notifiche.md (prerequisiti/verifica: l'URL reale
   si fornisce con NOTIFY_URLS al boot del backend di test).

VINCOLI
- Nessuna modifica a GET/PUT /settings, ai validatori, alle altre sezioni UI.
- Semantica §5.1: l'env vale SOLO su DB vuoto; dopo un save UI il DB vince.
- Mai loggare i valori degli URL (token Telegram — checklist C4).
- notify_enabled=true senza URL → no-op silenzioso (nessun invio, nessun warning bloccante).
- Nessuna dipendenza nuova (Apprise arriva in fase 10).
- Stringhe e messaggi UI in inglese.

DELIVERABLE
Report + output build + aggiornamento piano/STATO.md.
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 09b di nucs. Tabella PASS/FAIL con evidenza:
1. `cd backend && .venv/bin/python -m pytest -q` → verde (nuovi test seed inclusi);
   `.venv/bin/ruff check .` → OK.
2. `cd frontend && npx tsc --noEmit && npm run build` → exit 0.
3. Boot reale con env (DATA_DIR fresco, `NOTIFY_URLS="tgram://tok/chat"`,
   DEV_INSECURE_COOKIES=true): login → GET /settings → `notify_urls` valorizzato e
   `notify_enabled` "true" SENZA toccare la UI.
4. Boot su DATA_DIR già popolato con NOTIFY_URLS diversa → GET /settings restituisce
   il valore precedente (env ignorato).
5. Boot senza env → GET /settings → notify_enabled "true", notify_urls "".
6. Re-run `npm run e2e:09` (backend fresco) → check Notifications ancora verde
   ("Add at least one Apprise URL first." senza URL).
7. `grep -i tgram` sui log del boot con env reale → 0 risultati (mai loggare i token).
Se FAIL: correggi e riesegui TUTTO.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 09b di nucs.
1. Leggi piano/00-specifiche.md §4 §5.1 §5.8 §10 §12.3 e piano/checklist-sicurezza.md (C4).
2. Diff: `git diff main...HEAD`.
3. Attenzione a: nessun log di URL/token (C4), semantica primo-avvio coerente con §5.1
   (nessun override live), deviazione §4 (default notify_enabled=true) documentata in
   STATO.md, nessun cambio API/UI oltre il guard di sendTestNotification,
   nessuna dipendenza nuova, stringhe UI in inglese.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA".
```

## 6. Criteri di completamento

- [ ] pytest/ruff verdi, tsc/build ok, `e2e:09` verde.
- [ ] Boot reale con env → GET /settings valorizzato senza UI; DB popolato → env ignorato.
- [ ] STATO.md aggiornato (deviazione §4 + estensione .env.example §12.3).
- [ ] Commit e push: `feat(ops): default-enable notifications and seed notify urls from env`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. Riallinea `fase-10-scheduler-notifiche` da `main`.
3. Apri `piano/fasi/fase-10-scheduler-notifiche.md` — con NOTIFY_URLS ora disponibile,
   la verifica reale delle notifiche non richiede più reinserimenti manuali via UI.

> Promemoria: tieni pronto il tuo URL Apprise reale (es. bot Telegram: `tgram://token/chat_id`,
> oppure ntfy: `ntfy://ntfy.sh/tuo-topic`) — servirà per la verifica della fase 10.
