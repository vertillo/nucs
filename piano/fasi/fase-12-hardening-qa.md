# FASE 12 — Hardening finale, audit di sicurezza, QA end-to-end, documentazione

- **Implementazione**: modello economico (esecuzione controlli) + **modello AVANZATO** (audit)
- **Review**: **modello AVANZATO obbligatorio**
- **Dipende da**: fase 11
- **Branch**: `git checkout -b fase-12-hardening-qa`

---

## 1. Obiettivo

Ultimo passaggio prima dell'uso quotidiano: audit dipendenze, checklist sicurezza completa,
test end-to-end sui 10 criteri di accettazione §14, README finale, tag v1.0.0.

## 2. Prerequisiti

- Tutte le fasi precedenti mergiate e verificate sul mini PC.

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente:
- piano/00-specifiche.md — in particolare §14 (Definition of Done, TUTTI i 10 punti)
- piano/checklist-sicurezza.md — TUTTA
- piano/STATO.md — rileggi tutti i "Problemi noti / debito tecnico" delle fasi precedenti
Branch: fase-12. Codice/commenti inglese, docs in italiano.

OBIETTIVO
Chiudere ogni debito aperto, auditare, documentare, rilasciare v1.0.0.

COMPITI
1. Debito tecnico: elenca TUTTI i "Problemi noti" da STATO.md → per ciascuno: risolvi (preferito)
   oppure giustifica per iscritto in STATO.md perché resta (con issue/testo nel README se visibile all'utente).
2. Audit dipendenze:
   - backend: pip install pip-audit → pip-audit -r requirements.txt → ogni finding high/critical:
     aggiorna la dipendenza se esiste fix; altrimenti giustifica in STATO.md.
   - frontend: npm audit --production → idem (dopo fix: npm run build + tsc devono restare verdi).
   - Riesegui TUTTA la suite test backend dopo gli aggiornamenti.
3. Hardening spot-check da checklist (sezioni A-F): per OGNI punto non ancora ✅ nelle review precedenti,
   implementa il fix ORA. In particolare verifica a mano:
   - risposta /login costante nel tempo (utente esistente vs no): misura con curl time su 5 richieste ciascuno;
   - cookie Secure presente dietro HTTPS via tunnel Cloudflare;
   - CSP senza 'unsafe-eval'; style 'unsafe-inline' giustificato (Tailwind non ne ha bisogno a runtime:
     se la build non usa inline style, RIMUOVI 'unsafe-inline' da style-src — testa nel browser);
   - log di avvio non contengono valori env sensibili.
4. Test E2E manuale guidato: produci piano/verifica-e2e.md con la checklist §14 espansa in passi
   numerati eseguibili (comandi + risultato atteso), e ESEGUI ciascun passo segnando ✅/❌.
   I 10 punti §14 devono risultare TUTTI ✅ (o il progetto non è finito).
5. README.md finale (italiano, struttura: Cos'è / Screenshot testuale o ASCII / Requisiti /
   Installazione passo-passo (docker, .env tabella variabili, compose up con profili) /
   Cloudflare Tunnel (link deploy/cloudflared.md) / Tailscale (link deploy/tailscale.md) /
   Primo avvio e primo scan / Uso quotidiano / Backup e ripristino / Aggiornamento (git pull + rebuild) /
   Sicurezza (cosa fa l'app: login, rate limit, header; raccomandazione Cloudflare Access opzionale) /
   FAQ (5 domande realistiche: release mancante→mbid non abbinato→rematch; artista spezzato male→ignored;
   notifiche; cambio porta? nessuna porta; reset password da CLI)).
6. Versione: imposta 1.0.0 ovunque esposta (/api/health già la riporta), commit finale.

VINCOLI
- Nessuna nuova funzionalità. Solo fix, hardening, docs.
- Se l'audit dipendenze richiede un major upgrade rischioso: NON farlo ora; giustifica e pianifica in STATO.md.

DELIVERABLE
Report completo (debiti chiusi, audit, E2E) + README finale + aggiornamento STATO.md (fase 12).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica finale della fase 12 / del progetto nucs:
1. `cd backend && python -m pytest -q && ruff check .` verde; `cd frontend && npx tsc --noEmit && npm run build` verde.
2. `pip-audit -r backend/requirements.txt` e `npm audit --production --prefix frontend` → riporta tabella
   findings residui con giustificazione scritta (devono essere già in STATO.md).
3. Esegui piano/verifica-e2e.md COMPLETO sul mini PC in produzione (profili cloudflare+tailscale attivi):
   ogni passo ✅ con evidenza (output/screenshot descritto).
4. Attacco simulato: script con 12 login sbagliati da curl → osserva 429 entro i parametri §5.3 e
   verifica che l'audit log li registri senza leak. Poi login corretto dopo attesa blocco → funziona.
5. `docker stats --no-stream` dopo 24h di funzionamento (se possibile) → memoria stabile < 400MB (no leak evidenti).
6. `git ls-files | grep -iE "\.env$|secret|token"` → nessun file sensibile tracciato.
7. README: seguilo LETTERALMENTE da zero su una seconda macchina o directory pulita (clone + .env nuovo)
   fino al login → se un passo manca o è ambiguo, correggilo e ricomincia la prova.
Tabella finale: controllo | PASS/FAIL | evidenza.
```

## 5. PROMPT DI REVIEW FINALE — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un auditor senior (sicurezza applicativa + architettura). Audit finale pre-rilascio di nucs v1.0.0.
1. Leggi TUTTO piano/ (specifiche, checklist, STATO completo con debiti e giustificazioni) e verifica-e2e.md compilato.
2. Esamina il repo completo (non solo il diff): `git ls-files`.
3. Compila piano/checklist-sicurezza.md INTERAMENTE (A1-F4) con ✅/❌/➖ ed evidenza file:riga per ciascun punto.
4. Verifica coerenza: ciò che STATO.md dichiara fatto esiste davvero nel codice? Segnala ogni discrepanza.
5. Threat model rapido: elenca i 5 rischi residui più rilevanti per un'app self-hosted esposta via
   Cloudflare Tunnel e per ciascuno: mitigazione presente? sì/no/parziale.
6. Output: (a) checklist compilata, (b) tabella findings ALTA/MEDIA/BASSA, (c) rischi residui,
   (d) VERDETTO finale: "PRONTO PER v1.0.0" oppure "NON PRONTO: <motivi>".
```

## 6. Criteri di completamento

- [ ] Verdetto auditor: PRONTO (o tutti i bloccanti chiusi e rieseguito l'audit).
- [ ] §14: 10/10 punti ✅ documentati in verifica-e2e.md.
- [ ] README validato da installazione pulita.
- [ ] STATO.md aggiornato; commit e push: `chore(release): v1.0.0 hardening, audit, docs`.
- [ ] Merge su `main` + `git tag v1.0.0`.

## 7. Prossimo step (vita dopo il rilascio)

1. Uso quotidiano: gli scan girano da soli; controlla il feed o attiva le notifiche.
2. Aggiornamenti futuri: `git pull && docker compose build && docker compose up -d` (le migrazioni Alembic partono da sole).
3. Idee v2 (già parcheggiate in §1.1 delle specifiche + sezione "Ideate ma rimandate" di STATO.md):
   multi-utente, PWA, integrazione Lidarr, statistiche. Per ognuna: nuovo piano, stessa metodologia.
