# CLAUDE.md — Doomsday Engine V6

> File letto automaticamente da Claude Code all'avvio della sessione.
> Definisce regole operative, architetturali e di interazione vincolanti.

---

## Startup

All'inizio di ogni sessione:

1. Leggere sempre la ROADMAP aggiornata:
   `https://raw.githubusercontent.com/faustodba/doomsday-engine/main/ROADMAP.md`
2. Verificare la versione locale dei file coinvolti prima di operare.
3. Se la versione locale non è allineata alla ROADMAP → chiedere prima di procedere.
4. Non operare mai su versioni non allineate.

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
