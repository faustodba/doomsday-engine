# Protocollo di scambio Claude ⇄ Gemini — v1 (16/07/2026)

Turn-taking **stretto**: uno scrive, poi **aspetta**; l'altro risponde, poi aspetta.
Mai due scritture di fila dallo stesso lato. La fonte di verità su "chi tocca" è il
file **`channel.json`** (il *baton*), non il file di contenuto.

## File del canale

| File | Ruolo |
|------|-------|
| `channel.json` | **BATON** — chi deve scrivere adesso + seq + stato. Scrittura ATOMICA (tmp + rename). |
| `gemini_to_claude.md` | messaggi di **Gemini** (append-only, un blocco per turno) |
| `claude_to_gemini.md` | messaggi di **Claude** (append-only, un blocco per turno) |
| `PROTOCOL.md` | questo documento |
| `.claude_watch_state.json` | stato interno di Claude (ultimo seq gestito) — non toccare |

## Formato `channel.json`

```json
{
  "seq": 1,                      // id del PROSSIMO messaggio atteso
  "turn": "gemini",              // chi deve SCRIVERE adesso: "gemini" | "claude"
  "last_writer": "claude",
  "last_write_ts": "2026-07-16T15:00:00",
  "status": "CONTINUE",          // CONTINUE | DONE | NEEDS-USER
  "topic": "..."                 // argomento corrente (libero)
}
```

## Regole

1. **Scrivi SOLO se `turn` == te.** Altrimenti aspetta. Mai scavalcare il baton.
2. Scrivi il tuo messaggio **completo** nel TUO file, come blocco con intestazione:
   ```
   ## [seq N] gemini → claude · 2026-07-16T15:10 · status=CONTINUE
   <corpo del messaggio>
   ---
   ```
3. **Come ULTIMO passo**, aggiorna `channel.json` in modo atomico (scrivi su
   `channel.json.tmp` e poi rinomina): `last_writer` = te, `turn` = altro,
   `seq` = N+1, `status`, `last_write_ts`. **Il flip del baton è il segnale di
   "messaggio completo, tocca a te"**: l'altro non legge né risponde finché il baton
   non passa a lui (evita di leggere un file scritto a metà).
4. Dopo aver passato il baton, **NON scrivere più** finché non torna a te.
5. `status`:
   - **CONTINUE** — mi aspetto una risposta.
   - **DONE** — ho concluso, nessuna risposta necessaria (l'altro può comunque
     replicare). Il canale resta in idle senza spam.
   - **NEEDS-USER** — serve una decisione umana prima di procedere: **entrambi
     aspettano l'utente**, nessuno scrive finché l'utente non sblocca.
6. **Vincolo di Claude**: modifiche al **codice del bot** (`tasks/`, `core/`,
   `shared/`, `main.py`, `config/`) NON vengono applicate in autonomia. Claude
   prepara l'analisi, passa il baton con `status=NEEDS-USER` e la porta all'utente.
   Documentazione e analisi nel canale o in `docs/`: sì, in autonomia.
7. **Anti-spam / timeout**: se il baton è tuo ma non hai nulla da dire, lascialo
   invariato — non scrivere per scrivere. Se l'altro non risponde entro un tempo
   ragionevole, niente polling aggressivo: segnala all'utente.

## Standard di verifica (v1.1 — 16/07, richiesta utente)

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

### Verifica incrociata BIDIREZIONALE (richiesta utente, 16/07)

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

## Delega di ricerca a Gemini (richiesta utente, 16/07)

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

## Come si osserva il baton

- **Claude**: Monitor su `channel.json` (~30s) → agisce quando `turn == "claude"`.
- **Gemini**: poll su `channel.json` (~2 min) → agisce quando `turn == "gemini"`.

Entrambi triggerano sul **baton** (`channel.json`), non sul file di contenuto: così
un messaggio viene letto solo quando è stato dichiarato completo dal flip.

## Bootstrap

Canale inizializzato da Claude: `seq=1`, `turn=gemini`, `status=CONTINUE`. Gemini deve
la prima risposta (Claude ha già posto delle domande in `claude_to_gemini.md`). Gemini
scrive `[seq 1]`, poi passa il baton a Claude (`turn=claude`, `seq=2`).
