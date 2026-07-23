# Protocollo di scambio Claude ⇄ Gemini — v2 (23/07/2026)

> Migrato da v1 (16/07/2026) su proposta di Gemini, approvata dall'utente il
> 23/07/2026 dopo la scoperta che i due log append-only v1 avevano superato
> 300KB combinati (decine di migliaia di token riletti ad ogni turno). Le
> regole di fondo (turn-taking, standard di verifica, delega di ricerca,
> vincolo sulle modifiche di codice) sono INVARIATE rispetto a v1 — cambia
> solo la struttura dei file.

Turn-taking **stretto**: uno scrive, poi **aspetta**; l'altro risponde, poi aspetta.
Mai due scritture di fila dallo stesso lato. La fonte di verità su "chi tocca" è il
file **`channel.json`** (il *baton*), non il file di contenuto.

## File del canale (v2 — zero accumulo storico)

| File | Ruolo |
|------|-------|
| `channel.json` | **BATON** — chi deve scrivere adesso + seq + stato + metadati di contesto (v. sotto). Scrittura ATOMICA (tmp + rename). |
| `updates.md` | **Messaggio del turno corrente** — SOVRASCRITTO (non appeso) ad ogni passaggio di mano. Contiene solo le novità dell'ultimo turno, non lo storico. |
| `state.json` | **Stato consolidato del progetto** — issue aperte/risolte, debito tecnico, configurazione rilevante. Aggiornato IN-PLACE ad ogni turno che porta novità strutturali (non ogni turno meccanicamente). |
| `PROTOCOL.md` | questo documento |
| `archive/` | I vecchi `gemini_to_claude.md`/`claude_to_gemini.md` (v1, fino a seq 108/106) — congelati, non più caricati in memoria di default. Consultabili solo se serve ricostruire un dettaglio storico specifico. |
| `.claude_watch_state.json` | stato interno di Claude (ultimo seq gestito) — non toccare |

## Formato `channel.json`

```json
{
  "seq": 109,                    // id del PROSSIMO messaggio atteso
  "turn": "gemini",              // chi deve SCRIVERE adesso: "gemini" | "claude"
  "last_writer": "claude",
  "last_write_ts": "2026-07-23T09:55:00+02:00",
  "status": "CONTINUE",          // CONTINUE | DONE | NEEDS-USER
  "topic": "...",                // argomento corrente (libero)
  "session_id": "2026-07-23-checkpoint-01",  // id sessione/checkpoint corrente
  "turn_num": 109,               // turni accumulati in QUESTA sessione/checkpoint
  "est_context_pct": 30,         // stima soggettiva (NON un dato misurato) di chi scrive
  "mode": "NORMAL",               // NORMAL | COMPACT | SUMMARY — v. sotto
  "need_summary": "NO"           // YES se serve consolidare e proporre un nuovo checkpoint
}
```

* **`session_id`**: id della sessione/checkpoint corrente (libero, es. data).
* **`turn_num`**: contatore turni nella sessione corrente (si resetta ad un nuovo checkpoint).
* **`est_context_pct`**: stima **soggettiva** di chi scrive — nessuno dei due agenti ha
  accesso a un contatore reale di token/contesto (verificato e confermato da entrambi,
  17-23/07). Va trattata come segnale approssimativo, non come dato certo.
* **`mode`**: livello di sintesi atteso nella risposta:
  * `NORMAL` (~0-60% contesto stimato): risposte complete, spiegazioni se servono.
  * `COMPACT` (~60-80%): sintetico, solo dati/proposte essenziali, no spiegazioni ovvie.
  * `SUMMARY` (~80-90%): solo aggiornamenti incrementali rapidissimi.
* **`need_summary`**: `YES` quando ci si avvicina al limite (indicativamente >90%) — chi
  riceve il baton con `need_summary=YES` consolida `state.json` e la conversazione
  propone all'utente un nuovo checkpoint (reset del contesto chat), invece di continuare
  ad accumulare.

## Formato `updates.md` (sovrascritto ad ogni turno)

```markdown
## [seq N] gemini → claude · 2026-07-23T07:51:00+02:00 · status=CONTINUE

<corpo del messaggio — solo le novità di QUESTO turno>

---
```

Chi riceve il turno legge, integra quanto rilevante in `state.json` se è
strutturale, poi **sovrascrive** `updates.md` con la propria risposta (stesso
formato, nuovo seq). Il contenuto del turno precedente non serve più una volta
letto e recepito in `state.json` — ecco perché non si accumula.

## Formato `state.json` (stato consolidato, aggiornato in-place)

Struttura libera ma con un vincolo esplicito, richiesto dall'utente il
23/07/2026 dopo che una bozza d'esempio marcava un fix come "RESOLVED" senza
specificare che il bot in produzione non era stato riavviato (e quindi il fix
non era ancora attivo in runtime):

> **Ogni voce in `active_issues` deve portare SEMPRE due stati distinti**:
> `status` (stato del codice: `RESOLVED_IN_CODE`, `OPEN`, `PARTIAL`, ...) e
> `deployment_status` (stato reale in produzione: `DEPLOYED`,
> `PENDING_RESTART`, ...). Non consolidare mai i due in uno solo — un fix
> corretto e committato non è automaticamente un fix attivo.

Vedi `state.json` corrente per un esempio applicato (sezione `bot_prod` con
l'orario di avvio del processo live, da cui si deduce quali fix committati
dopo quel timestamp sono ancora `PENDING_RESTART`).

## Regole

1. **Scrivi SOLO se `turn` == te.** Altrimenti aspetta. Mai scavalcare il baton.
2. **Ri-leggi `channel.json` (e `updates.md`) subito PRIMA di scrivere la tua
   richiesta/risposta e PRIMA di aggiornare lo stato** — non fidarti di una
   lettura fatta a inizio task se nel frattempo è passato del tempo (es.
   lavoro lungo, altre attività). L'altro potrebbe aver scritto nel frattempo
   (nuovo `seq`, `turn` diverso da quello che ricordavi, `status=NEEDS-USER`
   sopraggiunto). Se lo stato è cambiato rispetto a quanto assunto, **gestisci
   prima il nuovo contenuto** (leggilo, eventualmente rispondi) e solo dopo
   procedi con la tua scrittura — mai sovrascrivere un baton più recente di
   quello che avevi in mente. Regola esplicita dell'utente (17/07/2026), nata
   da un rischio di race condition osservato in una sessione lunga.
3. Scrivi il tuo messaggio **completo** in `updates.md` (sovrascrivendo il
   turno precedente), come blocco con intestazione:
   ```
   ## [seq N] gemini → claude · 2026-07-23T15:10 · status=CONTINUE
   <corpo del messaggio>
   ---
   ```
   Se il contenuto del turno che stai sovrascrivendo è strutturale (una issue
   risolta, un nuovo gap trovato, un cambio di stato rilevante), riportalo
   PRIMA in `state.json` — altrimenti va perso quando il prossimo turno
   sovrascrive `updates.md`.
4. **Come ULTIMO passo**, aggiorna `channel.json` in modo atomico (scrivi su
   `channel.json.tmp` e poi rinomina): `last_writer` = te, `turn` = altro,
   `seq` = N+1, `status`, `last_write_ts`, e i metadati di contesto
   (`turn_num`, `est_context_pct`, `mode`, `need_summary` aggiornati alla tua
   situazione). **Il flip del baton è il segnale di "messaggio completo,
   tocca a te"**: l'altro non legge né risponde finché il baton non passa a
   lui (evita di leggere un file scritto a metà).
5. Dopo aver passato il baton, **NON scrivere più** finché non torna a te.
6. `status`:
   - **CONTINUE** — mi aspetto una risposta.
   - **DONE** — ho concluso, nessuna risposta necessaria (l'altro può comunque
     replicare). Il canale resta in idle senza spam.
   - **NEEDS-USER** — serve una decisione umana prima di procedere: **entrambi
     aspettano l'utente**, nessuno scrive finché l'utente non sblocca.
7. **Vincolo di Claude**: modifiche al **codice del bot** (`tasks/`, `core/`,
   `shared/`, `main.py`, `config/`) NON vengono applicate in autonomia. Claude
   prepara l'analisi, passa il baton con `status=NEEDS-USER` e la porta all'utente.
   Documentazione e analisi nel canale o in `docs/`: sì, in autonomia.
8. **Anti-spam / timeout**: se il baton è tuo ma non hai nulla da dire, lascialo
   invariato — non scrivere per scrivere. Se l'altro non risponde entro un tempo
   ragionevole, niente polling aggressivo: segnala all'utente.

## Standard di verifica (v1.1 — 16/07, richiesta utente — invariato in v2)

Ogni affermazione/controdeduzione, prima di essere recepita o scritta in `docs/`, va
verificata su **tre** livelli, non solo il codice:
1. **Codice** — leggere il file·funzione·riga citati; confermare firme, costanti, flussi.
2. **Log** — cercare nei log reali (`bot.log`, `logs/*.jsonl`, `.bak`) che il ramo/flusso
   descritto **avvenga davvero** in produzione e con quale frequenza (es. `grep` di una
   frase di log distintiva → conteggio + esempi con timestamp/istanza).
3. **Monitoraggio in tempo reale** — quando pertinente, stato live dai tool MCP monitor
   (`ciclo_stato`, `anomalie_live`, `istanza_*`) o dai file di stato/dataset in
   `data/`, per confermare comportamento/posta-in-gioco attuale (es. dimensione e
   anzianità di un file dati che un bug potrebbe distruggere).

Una controdeduzione "da codice" che non regge ai log va marcata come tale; una che i log
confermano va rafforzata coi numeri reali. Vale per **entrambi** gli agenti.

### Verifica incrociata BIDIREZIONALE (richiesta utente, 16/07 — invariata in v2)

Non solo "Gemini verifica Claude": **ogni** affermazione consegnata da un lato — inclusi i
contenuti di `docs/bot_master_architecture.md` — va **verificata anche dall'altro agente**,
non accettata per fiducia. Chi riceve un Tema/sintesi:
1. Rilegge autonomamente codice+log+monitoraggio dei punti chiave (non solo "sembra
   plausibile") prima di dire "confermo".
2. Se non trova nulla da correggere, lo dichiara esplicitamente **con cosa ha verificato**
   (es. "confermato X su riga Y, log Z"), non con un assenso generico.
3. Le controdeduzioni restano benvenute in entrambe le direzioni per l'intera durata dello
   scambio, blueprint chiuso o no — un `status=DONE` non blocca una correzione successiva.

Obiettivo: due controlli indipendenti sono più forti di uno che verifica e uno che si fida.

## Delega di ricerca a Gemini (richiesta utente, 16/07 — invariata in v2)

Claude ha un budget di token limitato in questa sessione; Gemini no (o comunque un budget
separato). Quando un compito è **ricognizione ampia** — grep/lettura su molti file, scavo
nei log storici, mappatura di "dove succede X nel codebase" — e **non richiede sintesi
critica immediata né una modifica**, Claude può **delegarlo a Gemini** invece di consumare
il proprio contesto a scansionare tutto lui stesso.

**Come**: stesso canale, stesso turn-taking. Claude scrive una richiesta di ricerca ben
delimitata (cosa cercare, dove, che formato di risposta serve) nel proprio turno, passa il
baton; Gemini esegue la ricognizione coi propri strumenti e riporta i risultati grezzi
(elenco file/righe/pattern trovati) nel proprio turno.

**Fiducia sul risultato**: un report di ricognizione di Gemini è un **lead da verificare**,
non un fatto accertato — a meno che Gemini stesso dichiari di aver già applicato lo
Standard di verifica v1.1 (codice+log+monitoraggio) su quel punto specifico. Per compiti
puramente esplorativi (es. "quali file toccano X", "quante occorrenze di Y nei log") il
report può essere preso a valore pressoché pieno, visto che è lavoro meccanico a basso
rischio di interpretazione; per affermazioni che orienteranno una decisione o un fix,
resta la verifica a 3 livelli prima di agire.

**Quando NON delegare**: task che richiedono editing di codice (comunque mai autonomo, vedi
sopra), decisioni architetturali, o sintesi che solo Claude ha il contesto pieno per fare
correttamente (es. collegare un finding a conversazioni precedenti con l'utente).

## Workflow "Gemini propone, Claude verifica e scrive" (richiesta utente, 23/07 — nuovo in v2)

Nato da un incidente reale: Gemini ha dichiarato 3 fix applicati, ma solo 1/3 era
effettivamente sul disco (gli altri 2 erano rimasti solo nel messaggio, mai scritti nei
file di progetto). In una sessione successiva, due file già corretti e committati da
Claude sono stati sovrascritti da un intervento esterno che ne ha rimosso il fix e
introdotto codice malformato.

Regola operativa: **Gemini propone** (analisi, diagnosi, anche codice come bozza) —
**Claude verifica sempre sul file reale** prima di considerare una cosa fatta, ed è
**sempre Claude** ad effettuare le modifiche definitive sul codice del progetto (coerente
con la regola 7). Se una proposta di Gemini necessita di chiarimenti prima di essere
applicata, Claude li richiede nel canale invece di assumere.

## Come si osserva il baton

- **Claude**: Monitor su `channel.json` (~30s) → agisce quando `turn == "claude"`.
- **Gemini**: poll su `channel.json` (~2 min) → agisce quando `turn == "gemini"`.

Entrambi triggerano sul **baton** (`channel.json`), non sul file di contenuto: così
un messaggio viene letto solo quando è stato dichiarato completo dal flip.

## Storia

- **v1** (16/07/2026 → 23/07/2026, seq 1-108): 2 file append-only
  (`claude_to_gemini.md`/`gemini_to_claude.md`), archiviati in `archive/` con
  suffisso `_v1_fino_seqNNN`. Canale inizializzato da Claude: `seq=1`,
  `turn=gemini`, `status=CONTINUE`.
- **v2** (23/07/2026 →, seq 109+): struttura a 3 file di questo documento.
  Migrazione eseguita da Claude su proposta di Gemini, approvata dall'utente.
