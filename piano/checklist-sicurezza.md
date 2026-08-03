# CHECKLIST SICUREZZA — da usare in OGNI review di fase

> Istruzioni per il modello reviewer: valuta OGNI punto come ✅ / ❌ / ➖ (non applicabile alla fase).
> Ogni ❌ va riportato con: file, riga/frammento, gravità (ALTA/MEDIA/BASSA), fix proposto.
> Le gravità ALTA e MEDIA sono bloccanti: la fase non si chiude finché non sono risolte.

## A. Autenticazione e sessioni
- [ ] A1. Password hashate con argon2id (mai bcrypt<cost<12, mai MD5/SHA in chiaro, mai reversible).
- [ ] A2. Token di sessione opaco ≥ 128 bit di entropia; nel DB solo hash del token.
- [ ] A3. Cookie: HttpOnly + Secure (salvo DEV_INSECURE_COOKIES) + SameSite=Lax; nessun Domain.
- [ ] A4. Login: risposta identica per utente inesistente/password errata; tempo di risposta simile (hash dummy).
- [ ] A5. Rate limit login: 5 tentativi/5 min/IP + blocco globale 15 min dopo 10 fallimenti.
- [ ] A6. Logout e cambio password revocano correttamente le sessioni.
- [ ] A7. Sessioni scadute non accettate; cleanup periodico presente.
- [ ] A8. Nessun endpoint autenticato risponde senza sessione valida (401, non redirect per API).

## B. Input, output, injection
- [ ] B1. Tutti gli input validati con pydantic (tipi, lunghezze max, formati data/time).
- [ ] B2. Query DB solo via ORM/parametrizzate: nessuna concatenazione SQL.
- [ ] B3. Path della libreria e delle cover mai costruiti da input utente (path traversal: controllare `..`, symlink).
- [ ] B4. Output API non contiene: hash password, token, secret Spotify, path assoluti del server, stack trace.
- [ ] B5. React: nessun `dangerouslySetInnerHTML` su dati esterni; URL esterni sempre codificati (`quote`/`encodeURIComponent`).
- [ ] B6. Header di sicurezza presenti su tutte le risposte (CSP, nosniff, DENY, Referrer-Policy, Permissions-Policy).
- [ ] B7. Controllo Origin/Referer + header `X-Requested-With` su tutte le mutazioni (POST/PUT/PATCH/DELETE).

## C. Segreti e configurazione
- [ ] C1. Nessun segreto committato (controllare `git diff` e file nuovi): .env, token, password di esempio reali.
- [ ] C2. `.env.example` contiene solo placeholder.
- [ ] C3. GET /settings non restituisce valori di chiavi segrete (solo flag `*_set`).
- [ ] C4. Log privi di segreti/token/cookie (cercare `password`, `token`, `cookie`, `secret` nei log statement).

## D. Rete e container
- [ ] D1. Nessuna porta pubblicata sull'host per `app` (solo `expose` interno).
- [ ] D2. Container app: utente non-root, filesystem read-only + tmpfs, volumi minimi, libreria montata `:ro`.
- [ ] D3. Limiti memoria/CPU presenti su tutti i servizi.
- [ ] D4. Immagini con tag/versione pinnata (niente `latest` salvo servizi infra senza alternativa — annotarlo).
- [ ] D5. `X-Forwarded-For` considerato solo da proxy fidati (CIDR rete Docker).
- [ ] D6. Errori 5xx → messaggio generico al client, dettaglio solo nei log.

## E. Dipendenze e supply chain
- [ ] E1. Versioni pinnate in requirements.txt / package.json; lockfile committati.
- [ ] E2. Nessuna dipendenza nuova non prevista dalle specifiche senza nota in STATO.md.
- [ ] E3. `pip-audit` / `npm audit` eseguiti nelle fasi previste; finding high/critical risolti o giustificati.

## F. Privacy e superficie
- [ ] F1. `X-Robots-Tag: noindex` + robots.txt disallow.
- [ ] F2. Copertine servite dalla cache locale (niente hotlink di terze parti nel browser) → CSP `img-src 'self'` rispettata.
- [ ] F3. Audit log di login_ok/login_fail/settings_change presente e senza dati sensibili.
- [ ] F4. L'app non scrive MAI dentro la cartella musica.
