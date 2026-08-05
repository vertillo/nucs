# FASE 14 — Verifica di produzione (mini PC: deploy, HTTPS, ambiente reale)

- **Implementazione**: modello economico (esecuzione verifiche su macchina reale)
- **Review**: **modello AVANZATO obbligatorio** (networking e sicurezza del deploy)
- **Dipende da**: fase 13 (la fase 11 ha implementato container e rete; la verifica
  dell'ambiente di produzione era stata differita — questo file la raccoglie TUTTA)
- **Branch**: `git checkout -b fase-14-verifica-produzione` (da main, dopo il merge della 13)
- **Nota**: richiede il **mini PC** (o la macchina di deploy) con Docker, il `.env` di
  produzione e gli account **Tailscale** (obbligatorio) e **Cloudflare** (opzionale,
  solo quando ci sarà un dominio).

---

## 1. Obiettivo

Portare nucs in **produzione** e verificare l'intero ambiente reale: deploy con i profili
compose, HTTPS via Tailscale (senza dominio) raggiungibile da più device, scans sulla
libreria vera, risorse a riposo, persistenza, IP reali nei log, backup e notifiche
funzionanti, e — quando ci sarà un dominio — anche il tunnel Cloudflare. Chiude tutti i
punti "differiti" della fase 11 e i criteri di accettazione di §14 non ancora coperti.

## 2. Prerequisiti

- Fase 11 mergiata (Dockerfile, compose con profili, deploy/*.md, serve.json).
- Mini PC con Docker Engine ≥ 24 + Compose plugin ≥ 2.20; `.env` di produzione compilato
  da `.env.example` (ADMIN_*, MUSIC_LIBRARY_PATH reale, TS_AUTHKEY o primo avvio interattivo).
- Account **Tailscale** attivo, client installati sui device da cui si accede (Mac, telefono…).
- (Opzionale, differito) Account **Cloudflare con dominio gestito** e token tunnel.

## 3. PROMPT DI IMPLEMENTAZIONE / VERIFICA (copia-incolla)

```text
CONTESTO PROGETTO
Repo "nucs". Leggi integralmente e rispetta:
- piano/00-specifiche.md — §12 (Docker e rete), §5.5 (header), §5.6 (proxy/IP reali), §14 (DoD)
- piano/README.md §4
- piano/STATO.md (sezione fase 11: punti differiti)
Branch: fase-14. Nessuna modifica di codice se non bug bloccanti (segnalali in STATO.md).

OBIETTIVO
Verifica COMPLETA dell'ambiente di produzione sul mini PC + chiusura dei punti differiti
della fase 11 (HTTPS tailnet, IP reali, scans vera libreria, Cloudflare quando c'è il dominio).

COMPITI
1. Deploy: `git clone` del repo sul mini PC (o pull), `.env` compilato, poi
   `docker compose --profile tailscale up -d` (senza dominio: SOLO profilo tailscale).
2. Verifica container: `docker compose ps` tutti healthy; `docker compose logs app --tail=50`
   senza errori; `docker compose config | grep -A2 ports` → vuoto (nessuna porta pubblicata);
   `curl localhost:8080/api/health` dall'host → DEVE FALLIRE (nessuna porta esposta). ✅ atteso.
3. HTTPS via Tailscale: `https://nucs.<tailnet>.ts.net` → pagina login con HTTPS valido;
   login → feed. Da ALMENO un secondo device nel tailnet (es. telefono con client Tailscale).
   Se serve.json fallisce: leggi `docker compose logs tailscale`, correggi la sintassi con la
   doc ufficiale tailscale serve config, aggiorna serve.json E STATO.md, riprova.
4. `cd e2e && npm ci && BASE=https://nucs.<tailnet>.ts.net npm run e2e:11` → scenario
   login+theme+logout+security headers su HTTPS → verdi.
5. IP reali (§5.6): login dal device → nei log app l'audit `login_ok` mostra l'IP reale
   del device (o del nodo tailscale), NON 172.x del container proxy. Verificare anche che
   X-Forwarded-For sia fidato solo dalla rete Docker (§5.6).
6. Scan reali sulla libreria VERA: UI impostazioni → "Scan library now" → artisti popolati;
   "Check for new releases now" → release nel feed con copertine; pagina dettaglio con i 4 link.
7. Risorse: `docker stats --no-stream` → app < 300MB RAM a riposo (DoD §14.7), CPU ~0.
8. Persistenza: `docker compose down && docker compose up -d` → dati intatti (login, release).
9. Backup: `docker compose exec app python -m app.cli backup-now` → file in /data/backups,
   `PRAGMA integrity_check` ok; (o attesa del job notturno 02:30 se la finestra lo permette).
10. Notifiche: Settings → Notifications → "Send test notification" con l'URL reale nel .env
    (seed primo avvio) → notifica ricevuta sul device; poi uno scan con novità → 1 notifica aggregata.
11. Riavvio mini PC → l'app torna su da sola (restart unless-stopped, dati intatti).
12. (OPZIONALE, quando ci sarà un dominio Cloudflare): `CF_TUNNEL_TOKEN` nel .env +
    `docker compose --profile cloudflare --profile tailscale up -d` → Public Hostname creato
    → https://<subdomain>.<dominio> → login → feed; header sicurezza presenti; /api/health ok;
    `BASE=https://<subdomain>.<dominio> npm run e2e:11` → verdi; audit login_ok con IP reale
    (CF-Connecting-IP) o edge documentato. Cloudflare Access opzionale come difesa in profondità.
13. Aggiorna piano/STATO.md: esiti di ogni punto, eventuali correzioni a serve.json/docs,
    chiusura dei punti differiti della fase 11.

VINCOLI
- Nessuna porta pubblicata sull'host in nessun momento.
- Nessun segreto nei file committati: CF_TUNNEL_TOKEN/TS_AUTHKEY solo in .env (gitignored).
- Se un bug bloccante emerge: fix minimo + segnalazione in STATO.md, poi ri-esegui TUTTO.

DELIVERABLE
Report PASS/FAIL con evidenza per ogni punto + aggiornamento piano/STATO.md (fase 14).
```

## 4. PROMPT DI REVIEW — da dare al MODELLO AVANZATO (copia-incolla)

```text
Sei un reviewer senior DevOps/security. Revisiona la fase 14 di nucs (deploy reale).
1. Leggi piano/00-specifiche.md §12 §5.5 §5.6 §14 e piano/checklist-sicurezza.md (D TUTTA, C, F1).
2. Esamina: docker-compose.yml, docker-compose.dev.yml, deploy/, serve.json, .env.example,
   log di produzione raccolti (compose ps/logs, docker stats), audit login_ok con IP reali,
   `git diff main...HEAD` (differita della fase 13).
3. Caccia: porte esposte, segreti nei layer/immagini/log, HSTS dietro HTTPS,
   X-Forwarded-For fidato oltre il necessario, serve.json con sintassi non validata,
   cloudflared autoupdate, immagine > 400MB, app > 300MB a riposo, retention backup rotta.
4. Output: tabella findings (ALTA/MEDIA/BASSA | file | problema | fix). Zero → "REVIEW PULITA" + controlli eseguiti.
```

## 5. Criteri di completamento

- [ ] App in produzione: HTTPS Tailscale da più device, login/feed funzionanti, scans reali
      con copertine, e2e:11 su HTTPS verde.
- [ ] IP reali nei log (non 172.x), HSTS/header sicurezza verificati su HTTPS.
- [ ] Zero porte pubblicate; docker stats app < 300MB; immagine < 400MB.
- [ ] Persistenza down/up e riavvio mini PC ok; backup integro; notifica reale ricevuta.
- [ ] (Opzionale) Cloudflare con dominio → tunnel pubblico verificato.
- [ ] Review avanzata: zero ALTA/MEDIA aperti; STATO.md aggiornato; punti differiti fase 11 chiusi.
- [ ] Commit e push: `feat(deploy): production verification on mini pc (tailscale, real scans, ip logging)`.

## 6. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. Se non ancora fatto: esegui la checklist manuale della **fase 13** sull'ambiente di
   produzione (azioni avversarie incluse).
3. Progetto completo: resta solo la manutenzione (README finale aggiornato in fase 12 e,
   se necessario, il deploy definitivo su macchina pulita).
