# Piano di realizzazione — nucs

Applicazione self-hosted per non perdere le nuove uscite musicali degli artisti che ti piacciono
(inclusi i featuring), con feed delle release, link rapidi (Spotify / YouTube Music / Deezer / Google),
login sicuro, tema scuro/chiaro, deploy via Docker Compose dietro Cloudflare Tunnel e Tailscale.

---

## 1. Come è organizzato questo piano

| File | Ruolo |
|---|---|
| `piano/README.md` | Questo file: workflow, regole globali, indice delle fasi. |
| `piano/00-specifiche.md` | **LA FONTE UNICA DI VERITÀ.** Architettura, stack, schema DB, API, UI, sicurezza, Docker. Se un prompt e questo file divergono, vale questo file. |
| `piano/checklist-sicurezza.md` | Checklist OWASP-oriented usata nelle review di ogni fase. |
| `piano/STATO.md` | Diario di avanzamento. Viene aggiornato dal modello **alla fine di ogni fase**. Ogni fase successiva lo legge per riprendere il contesto. |
| `piano/mockup-opendesign.md` | Brief completo per Open Design: genera il **prototipo UI interattivo** prima delle fasi frontend (07-09) per validare flussi e feature. Se produci i mockup, salvali in `piano/mockup/` e usali come riferimento visivo nelle fasi 07-09. |
| `piano/fasi/fase-XX-*.md` | Una fase = un file con: prompt di implementazione, prompt di verifica, prompt di review, criteri di completamento, istruzioni per lo step successivo. |

## 2. Workflow di ogni fase (seguirlo SEMPRE, senza eccezioni)

1. **Prepara il contesto**: apri il repo nel tool del modello (DeepSeek o altro). Il modello deve poter leggere `piano/00-specifiche.md`, `piano/STATO.md` e il codice esistente.
2. **Crea il branch**: `git checkout -b fase-XX-nome` (da `main` aggiornato).
3. **Incolla il PROMPT DI IMPLEMENTAZIONE** della fase (sezione 3 del file di fase).
4. **Incolla il PROMPT DI VERIFICA** (sezione 4). La fase non è completata finché tutti i controlli non passano.
5. **Incolla il PROMPT DI REVIEW** (sezione 5) — possibilmente a un modello più avanzato dove indicato. Applica i fix obbligatori (severity alta/media).
6. **Chiedi al modello di aggiornare `piano/STATO.md`** con: cosa è stato fatto, decisioni prese, deviazioni dalle specifiche, risultati dei test, problemi noti.
7. **Commit e push**: il modello esegue `git add -A && git commit` con messaggio conventional semantico (es. `feat(auth): session login with rate limiting`), poi `git push`. Merge su `main` solo dopo review passata.
8. **Passa alla fase successiva** usando il blocco "Prossimo step" in fondo al file di fase.

> Regola d'oro: **mai saltare la verifica** e **mai far proseguire il modello se i test non passano**. I modelli economici tendono a dichiarare completato ciò che non hanno verificato: i prompt di verifica esistono per questo.

## 3. Scelta del modello per fase

| Tipo | Quando usarlo |
|---|---|
| **Economico** (es. DeepSeek) | Implementazioni guidate da prompt dettagliati, CRUD, UI, test, Docker di base. |
| **Avanzato** (es. Claude/GPT top) | Review di sicurezza, logica di discovery MusicBrainz (rate limit, paginazione, dedup), networking Docker/Tailscale, audit finale. |

Nell'intestazione di ogni fase è indicato il modello consigliato per implementazione e review.

## 4. Regole globali vincolanti (valide per TUTTI i prompt di tutte le fasi)

Queste regole sono già incluse nei prompt, ma le ripeti se il modello le ignora:

1. Leggere sempre `piano/00-specifiche.md` prima di scrivere codice. In caso di conflitto, le specifiche vincono; se qualcosa è ambiguo, fermarsi e dichiarare l'ambiguità invece di improvvisare.
2. **Modifiche minime**: non refactorare codice di fasi precedenti se non richiesto dalla fase corrente.
3. Codice, commenti e messaggi di commit in **inglese**; stringhe UI, messaggi di errore e notifiche in **inglese**. I documenti operativi per l'utente (es. README di progetto) restano in italiano.
4. Versioni delle dipendenze **sempre pinnate** (niente `*` o `latest`). `package-lock.json` e `requirements.txt` vanno committati.
5. **Mai** committare `.env`, segreti, token, password. Esiste solo `.env.example`.
6. Mai disattivare test o check per farli passare: si corregge la causa, non il sintomo.
7. Ogni fase termina con l'aggiornamento di `piano/STATO.md`.
8. Niente funzionalità extra non richieste ("voglia di aiutare" = scope creep). Le idee vanno annotate in `STATO.md` sezione "Ideate ma rimandate".
9. Non esporre mai dati di sicurezza (hash, sessioni, log con IP interni) via API.
10. Se un passaggio richiede credenziali esterne (Spotify, Cloudflare, Tailscale), il modello deve scrivere istruzioni precise e fermarsi in attesa, non inventare valori.

## 5. Indice delle fasi

| # | Fase | Impl. | Review |
|---|---|---|---|
| 00 | Scaffolding repo, convenzioni, CI minima | Economico | Economico |
| 01 | Backend base: FastAPI, config, SQLite, migrazioni, health | Economico | Economico |
| 02 | Autenticazione e sicurezza base (login, sessioni, rate limit, header) | Economico | **Avanzato** |
| 03 | Scansione libreria musicale (tag, artisti, album artist, featuring, contributi) | Economico | Economico |
| 04 | Abbinamento artisti → MusicBrainz ID | Economico | Economico |
| 05 | Motore di discovery release (proprie + featuring) | Economico | **Avanzato** |
| 06 | Link esterni (Spotify/YTM/Deezer/Google) e cache copertine | Economico | Economico |
| 07 | Frontend base: Vite/React/Tailwind, tema, login, layout | Economico | Economico |
| 08 | UI feed release + pagina dettaglio | Economico | Economico |
| 09 | UI artisti + pagina impostazioni | Economico | Economico |
| 09b | Notifiche: default attivo + seed da env (NOTIFY_URLS) | Economico | Economico |
| 10 | Scheduler, backup DB, notifiche opzionali (Apprise) | Economico | Economico |
| 11 | Docker finale, compose, Cloudflare Tunnel, Tailscale | Economico | **Avanzato** |
| 12 | Hardening, audit sicurezza, QA finale, guida deploy | Economico | **Avanzato** |
| 13 | Verifica manuale completa (checklist happy path + azioni avversarie) | **UMANO** | **Avanzato** |
| 14 | Verifica di produzione (mini PC: deploy, HTTPS tailnet, ambiente reale) | Economico | **Avanzato** |

> Le fasi vanno eseguite **in ordine**. 07 può iniziare in parallelo a 05/06 solo se sei esperto: sconsigliato.
> Le fasi 07-12 usano l'harness E2E automatico in `e2e/` (puppeteer + Chrome headless) al posto dei check manuali nel browser: `cd e2e && npm ci` (una volta, vedi `e2e/README.md`). La fase 13 è la checklist manuale complementare (azione avversarie incluse) eseguita dall'operatore.

## 6. Prerequisiti da preparare TU (umano) prima di iniziare

- [ ] Mini PC (o macchina di build) con Docker Engine ≥ 24 e Docker Compose plugin ≥ 2.20.
- [ ] Account Cloudflare (gratuito) con un dominio gestito da Cloudflare (per il tunnel).
- [ ] Account Tailscale (gratuito) e tailnet attivo.
- [ ] Percorso della cartella musica sul mini PC (es. `/srv/musica`). I file devono avere tag decenti (ARTIST, ALBUMARTIST, TITLE).
- [ ] (Opzionale, fase 06) App Spotify Developer per avere link diretti: https://developer.spotify.com/dashboard
- [ ] (Opzionale, fase 10) URL Apprise per notifiche (es. Telegram, ntfy, email).
- [ ] Git configurato sulla macchina di lavoro.

## 7. Cosa fare se qualcosa si blocca

1. Riapri il file di fase → sezione "Criteri di completamento": individua il punto esatto non soddisfatto.
2. Incolla al modello: output dell'errore completo + `git status` + contenuto dei file coinvolti + questo incipit:
   > "Siamo alla fase XX del progetto descritto in `piano/00-specifiche.md`. La verifica al punto Y fallisce con questo errore: `<errore>`. Diagnosticane la causa, proponi il fix minimo, applicalo e riesegui la verifica. Non modificare altro."
3. Se dopo 2 tentativi il modello economico non risolve → passa al modello avanzato per quella singola fase.
