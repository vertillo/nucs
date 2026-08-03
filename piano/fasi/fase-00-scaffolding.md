# FASE 00 — Scaffolding repository e convenzioni

- **Implementazione**: modello economico
- **Review**: modello economico
- **Dipende da**: niente (è la prima)
- **Branch**: `git checkout -b fase-00-scaffolding`

---

## 1. Obiettivo

Creare la struttura vuota del repository (§3 delle specifiche), i file di configurazione base
(.gitignore, .env.example, pyproject con ruff, pre-requisiti CI), in modo che le fasi successive
trovino uno scheletro coerente. **Nessuna logica applicativa in questa fase.**

## 2. Prerequisiti

- Repo git inizializzato, branch `main` pulito.
- `piano/` già presente (c'è).

## 3. PROMPT DI IMPLEMENTAZIONE (copia-incolla)

```text
CONTESTO PROGETTO
Stai lavorando sul repository di "nucs", un'app self-hosted per tracciare le nuove
uscite musicali. Prima di scrivere qualsiasi file leggi integralmente:
- piano/00-specifiche.md  (FONTE DI VERITÀ: stack, struttura repo §3, env §12.3)
- piano/README.md         (regole globali §4 — le devi rispettare tutte)
- piano/STATO.md          (diario di avanzamento)

OBIETTIVO DI QUESTA FASE
Creare SOLO lo scaffolding del repository, senza logica applicativa.

COMPITI
1. Crea la struttura directory esatta descritta in piano/00-specifiche.md §3:
   backend/app/{api,services}, backend/tests, backend/alembic/versions, frontend/src/{pages,components,api},
   docker/, deploy/tailscale/, .github/workflows/.
   Dove serve che git tracci directory vuote usa file .gitkeep.
2. Crea .gitignore per: Python (__pycache__, .venv, *.egg-info, .pytest_cache, .ruff_cache),
   Node (node_modules, dist), .env, data/, *.db, .DS_Store.
3. Crea .env.example copiando ESATTAMENTE le variabili da piano/00-specifiche.md §12.3
   (valori placeholder, nessun segreto reale).
4. Crea backend/pyproject.toml con configurazione ruff (target py312, line-length 110,
   regole: E,F,I,UP,B,S + ignore documentati) e configurazione pytest (testpaths=backend/tests).
5. Crea backend/requirements.txt e backend/requirements-dev.txt VUOTI salvo commento
   "# populated in phase 01" (le dipendenze arrivano nella fase 01).
6. Crea .github/workflows/ci.yml MINIMO: trigger su push/PR, job che installa ruff e
   esegue `ruff check backend/` (tollera assenza di codice: `|| true` NON consentito;
   piuttosto fai in modo che passi con repo quasi vuoto).
7. Crea README.md radice con 10 righe: titolo, scopo, stato "in costruzione", rimando a piano/.
8. .dockerignore radice: .git, node_modules, data, piano, .env.

VINCOLI
- NON creare codice sorgente (niente main.py, niente package.json con contenuto reale,
  niente Dockerfile): solo struttura e config elencate sopra.
- NON committare: lo faccio io dopo la verifica.
- File di testo UTF-8, newline finale presente.

DELIVERABLE
Al termine elenca tutti i file creati. Poi aggiorna piano/STATO.md usando il template in fondo
al file (fase 00).
```

## 4. PROMPT DI VERIFICA (copia-incolla)

```text
Verifica la fase 00 del progetto nucs. Esegui e riporta l'esito di OGNI controllo:
1. `find . -path ./.git -prune -o -type f -print | sort` → confronta con la struttura §3 di
   piano/00-specifiche.md: elenca eventuali file mancanti o extra rispetto a quanto richiesto
   per la fase 00 (ricorda: in questa fase NON devono esistere main.py, Dockerfile, package.json compilato).
2. `cat .env.example` → deve contenere TUTTE le variabili di piano/00-specifiche.md §12.3, nessuna con valore reale.
3. `python3 -m pip install ruff >/dev/null 2>&1 && ruff check backend/ 2>&1; echo "ruff exit: $?"` → exit 0.
4. `git status --porcelain` → elenca i file: NON deve comparire .env né directory data/.
5. Apri .github/workflows/ci.yml: conferma che non usa `|| true` e che il comando ruff è corretto.
Produci una tabella: controllo | esito (PASS/FAIL) | evidenza. Se qualcosa è FAIL, correggilo
e riesegui TUTTI i controlli da capo.
```

## 5. PROMPT DI REVIEW (copia-incolla)

```text
Fai la review della fase 00 del progetto nucs.
1. Leggi piano/00-specifiche.md §3 e §12.3 e piano/checklist-sicurezza.md (sezioni C ed E).
2. Esamina `git diff main...HEAD` (o i file untracked se non ancora committato).
3. Controlla: struttura conforme, nessun segreto, nessun file superfluo, config ruff sensata,
   .gitignore completo, niente dipendenze non pinnate introdotte di soppiatto.
4. Output: tabella findings con gravità (ALTA/MEDIA/BASSA), file, problema, fix.
   Se zero findings: scrivi esplicitamente "REVIEW PULITA".
```

## 6. Criteri di completamento

- [x] Struttura directory conforme a §3 (per quanto atteso in questa fase).
- [x] `.env.example` completo e senza segreti.
- [x] `ruff check backend/` exit 0.
- [x] Review pulita o findings risolti.
- [x] `piano/STATO.md` aggiornato.
- [x] Commit e push: `chore: project scaffolding`.

## 7. Prossimo step

1. Il modello esegue commit semantico e push sul branch corrente, poi merge su `main`.
2. Crea il branch: `git checkout -b fase-01-backend-base`.
3. Apri `piano/fasi/fase-01-backend-base.md` e incolla il prompt di implementazione.
