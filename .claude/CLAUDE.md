# CLAUDE.md — Doomsday Engine V6

> File letto automaticamente da Claude Code all'avvio della sessione.
> Definisce regole operative, architetturali e di interazione vincolanti.

---

## Startup

All'inizio di ogni sessione, in questo ordine:
1. Leggere la ROADMAP locale: `C:\doomsday-engine\ROADMAP.md`
2. Leggere il file di handoff: `C:\doomsday-engine\.claude\SESSION.md`
3. Verificare la versione locale dei file coinvolti prima di operare.
4. Se la versione locale non è allineata alla ROADMAP → chiedere prima di procedere.
5. Non operare mai su versioni non allineate.
6. Riferire all'utente: obiettivo sessione, stato attuale, prossimo step.

> La ROADMAP locale è la fonte di verità del progetto.
> SESSION.md è il ponte di contesto tra sessione browser e sessione VS Code.

---

## Repo e percorsi

| Repo | Percorso locale |
|------|----------------|
| `faustodba/doomsday-engine` (V6) | `C:\doomsday-engine` |
| `faustodba/doomsday-bot-farm` (V5, produzione) | `C:\Bot-farm` |

---

## Regole di codice

- **Mai frammenti.** Rilasciare sempre file completi, coerenti, eseguibili.
- Prima di scrivere qualsiasi primitiva V6, leggere il file V5 corrispondente.
  Zone OCR, coordinate UI, template names, logica di parsing sono già calibrati in V5.
- Ogni modifica deve essere compatibile con V5 (verifica regressione).
  Se serve un componente V5 → richiederlo esplicitamente.

---

## Standard architetturale V6 (vincolante)

| Cosa | Standard | Vietato |
|------|----------|---------|
| Firma `run` | `def run(self, ctx)` | `async def run` |
| Attese | `time.sleep(n)` | `asyncio.sleep(n)` |
| Logging | `ctx.log_msg(msg)` | `ctx.log(msg)` |
| Navigator | `ctx.navigator.vai_in_home()` | `await ctx.navigator...` |
| Barra inferiore | `ctx.navigator.tap_barra(ctx, "voce")` | coordinate fisse Campaign/Alliance/etc. |
| Template matching | `matcher.find_one()`, `matcher.score()` | `matcher.match()`, `matcher.find()` |
| Screenshot frame | `screen.frame` | `device.last_frame` |
| Device costruttore | `AdbDevice(host=H, port=P, name=N)` | `AdbDevice(porta_int)` |

---

## Regole speciali per task

- **RaccoltaTask** non ha schedulazione: deve essere eseguito per ogni istanza
  a patto che ci siano slot liberi. Non aggiungere mai `interval` o `schedule`.
- Il contatore slot squadre X/Y è leggibile via OCR sia da HOME che da MAPPA.
  Non assumere mai che si legga solo in mappa.

---

## Regole bat di rilascio

- Usare **path assoluti espliciti** per i file sorgente nei `.bat`.
- Vietato: `%~dp0`, `%USERNAME%\Downloads` o path relativi.
- Il bat deve dichiarare una variabile `FILE_DIR` configurabile in cima al file,
  con istruzione chiara per l'utente, oppure copiare i file direttamente
  in `C:\doomsday-engine` prima dell'esecuzione.

---

## Issues aperti (stato al 14/04/2026)

| # | Issue | Priorità | Stato |
|---|-------|----------|-------|
| RT-15 | Arena + ArenaMercato — da testare su FAU_01 | ALTA | ⏳ in attesa |
| 1 | Rifornimento — task disabilitato, da abilitare e testare | ALTA | ⏳ in attesa |
| 3 | Zaino — `deposito` OCR non passato dall'orchestrator a `ZainoTask.run()` | MEDIA | ⏳ in attesa |
| 4 | Radar — skip silenzioso, nessun log prodotto | ALTA | ⏳ in attesa |
| 5 | Alleanza — `COORD_ALLEANZA=(760,505)` ancora hardcoded | BASSA | ⏳ in attesa |

> Aggiornare questa tabella ad ogni sessione insieme alla ROADMAP.

---

## Protocollo SESSION.md

SESSION.md è il file di handoff tra sessione browser (claude.ai) e sessione
VS Code (Claude Code). Va aggiornato ad ogni passaggio di contesto.

### Regole
- Leggere sempre SESSION.md all'avvio prima di qualsiasi operazione.
- Dopo ogni step completato: aggiornare "Risultato ultima operazione" e "Prossimo step".
- Dopo ogni sessione VS Code: aggiornare "Stato attuale" con un riassunto.
- SESSION.md NON va in git (è in .gitignore).

### Passaggio browser → VS Code
L'utente dirà: `"Leggi SESSION.md e dimmi dove eravamo rimasti."`
Rispondere con: obiettivo, stato attuale, prossimo step — senza chiedere altro.

### Passaggio VS Code → browser
L'utente incollerà il risultato della sessione VS Code nel browser.
Aggiornare SESSION.md con il nuovo stato prima di procedere.

---

## Esecuzione

- Scomporre ogni processo in step semplici.
- Procedere step-by-step: un passo alla volta, non anticipare.
- Nessuna modifica complessa senza validazione intermedia.

---

## Interazione

- Chiedere feedback a ogni fase rilevante.
- Attendere conferma prima di ogni step critico.
- Non procedere in autonomia su operazioni distruttive o ambigue.

---

## Rilasci (batch)

Ogni rilascio segue questa sequenza:
1. Copia del file in `C:\doomsday-engine\<path>\`
2. Commit + push su `faustodba/doomsday-engine`
3. Aggiornamento ROADMAP (fix applicati, stato RT, issues aperti)
4. Aggiornamento tabella Issues aperti in CLAUDE.md se necessario
5. Aggiornamento SESSION.md con stato post-rilascio

---

## ROADMAP

- Aggiornare la ROADMAP a ogni sessione.
- Registrare: fix applicati, stato test runtime (RT-xx), issues aperti.
- La ROADMAP è la fonte di verità dello stato del progetto.

---

## Miglioramenti

- Proporre ottimizzazioni tecniche/architetturali a fine sessione o quando rilevate.
- Le proposte non bloccano il lavoro corrente — vanno documentate come issue o note.

---

## Coerenza

- Garantire coerenza semantica, architetturale e di stile tra tutti i moduli.
- Seguire pattern e convenzioni esistenti (nomi, firme, struttura classi).
- Evitare l'introduzione di nuovi pattern senza esplicita approvazione.

---

## Regola generale

> Approccio strutturato, verificabile, tracciabile.
> Ogni scelta deve essere giustificabile e reversibile.
