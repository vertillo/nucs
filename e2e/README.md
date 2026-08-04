# nucs E2E — verifica automatica delle fasi (puppeteer + Chrome headless)

Harness di test **browser/API** usata dai prompt di verifica delle fasi 06-13.
Sostituisce i "check manuali nel browser": lo stesso flusso viene eseguito
da Chrome headless, con tabella PASS/FAIL ed exit code ≠ 0 se qualcosa fallisce.

## Prerequisiti (da installare una volta)

- **Node ≥ 20** (stesso requisito del build frontend; verificare con `node --version`)
- **npm** (incluso con Node)
- **Backend in esecuzione** con admin attivo (vedi sotto)
- Alla prima installazione puppeteer **scarica Chrome for Testing**
  (~150-300 MB in `~/.cache/puppeteer`): serve la rete, una volta sola.

```bash
cd e2e
npm ci                       # installa puppeteer (pinnato) + package-lock.json
```

Niente altre dipendenze: `puppeteer` è l'unico package e NON tocca
`frontend/package.json` (l'app resta senza dipendenze extra).

## Avvio dell'app sotto test

Per gli scenari browser (07+), l'app deve essere **buildata e servita dal backend**
(così si testa anche CSP e static serving), con cookie insicuri attivi per http:

```bash
cd frontend && npm run build
cd backend && DATA_DIR=/tmp/nucs-e2e DEV_INSECURE_COOKIES=true \
  ADMIN_USERNAME=admin ADMIN_PASSWORD='password-lunga-12' \
  .venv/bin/uvicorn app.main:app --port 8080
```

Lo scenario fase-06 (solo API/curl) funziona anche su un backend senza frontend
ma con dati arricchiti da fase 06 (release con link + cover).

## Esecuzione

```bash
cd e2e
npm run e2e:06   # fase 06: link esterni §9 + endpoint /covers (API, no browser)
npm run e2e:07   # fase 07: login, tema, navbar, logout, redirect, CSP (browser)
npm run e2e:08   # fase 08: feed release + dettaglio (browser, seed lungo)
npm run e2e:09   # fase 09: artisti + impostazioni (browser, seed lungo)
```

Variabili d'ambiente:

| Variabile | Default | Note |
|---|---|---|
| `BASE` | `http://127.0.0.1:8080` | URL dell'app (per fase 11: `https://<tunnel>` ) |
| `ADMIN_USER` | `admin` | credenziali admin |
| `ADMIN_PASS` | `password-lunga-12` | **il backend deve avere QUESTO utente** |

> **Importante**: il backend E2E va avviato con `NOTIFY_URLS=` (vuoto) se esiste un
> `backend/.env` di sviluppo con un URL Apprise reale: le env esplicite hanno
> precedenza sul file `.env` e il seed al primo avvio deve restare pulito
> (altrimenti i check "senza URL" di fase 09 falliscono e partono notifiche reali).

## Struttura

- `harness.js` — core: launch Chrome headless, `check()` PASS/FAIL, login UI,
  POST autenticati, poll scan, raccoglitori console/CSP/network/immagini,
  screenshot su FAIL in `e2e/artifacts/`
- `scenarios/fase-XX.js` — uno scenario per fase (le fasi 08+ aggiungono il
  proprio file quando implementano l'UI)
- `artifacts/` — screenshot su FAIL (gitignored)

## Regole per chi aggiunge uno scenario

1. `check()` con messaggio esplicito e `extra` = evidenza (status, valore reale).
2. Gli errori console/network da flussi **intenzionali** (401 di login/logout)
   vanno esclusi con `h.realErrors(state)` / `h.realFailed(state)`.
3. Per i dati reali usare `await h.seed(page)` (login UI → scan library →
   discovery MB) o partire da un DB già popolato.
4. Lo scenario deve terminare con `await h.finish(...)` (screenshot + exit code).
