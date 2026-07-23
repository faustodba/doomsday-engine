# Cartella di Scambio Asincrono tra AI (Gemini & Claude Code)

Benvenuto in questo spazio di collaborazione! Questa cartella è stata creata per permettere a **Gemini** (l'assistente corrente nell'IDE) e **Claude Code** (l'agente CLI per lo sviluppo) di passarsi consegne, specifiche e report in modo asincrono.

> **Protocollo v2 dal 23/07/2026** — vedi [`PROTOCOL.md`](PROTOCOL.md) per la
> specifica completa e vincolante (turn-taking, standard di verifica, formato
> file). Questo README è solo una guida rapida per l'utente umano.

## Protocollo di Scambio (sintesi)

1. **Chi tocca adesso**: guarda `"turn"` in `shared_ai_exchange/channel.json`.

2. **Da Gemini a Claude Code**:
   * Quando è il turno di Gemini ed è lui a scrivere, i dettagli (istruzioni,
     file da modificare, standard richiesti, domande per Claude) sono in:
     👉 `shared_ai_exchange/updates.md` (sovrascritto ad ogni turno — contiene
     solo le novità dell'ultimo passaggio, non lo storico).

3. **Azione dell'Utente**:
   * Apri il tuo terminale con Claude Code e ordina:
     > *"Leggi Gemini"* oppure *"Leggi `shared_ai_exchange/updates.md` ed allineati."*

4. **Da Claude Code a Gemini**:
   * Claude scrive l'esito del suo lavoro (codice modificato, log dei test,
     risposte) sovrascrivendo lo stesso file:
     👉 `shared_ai_exchange/updates.md`
   * Gemini lo legge nel turno successivo per validare i cambiamenti.

5. **Stato consolidato del progetto** (issue aperte/risolte, debito tecnico):
   👉 `shared_ai_exchange/state.json` — aggiornato in-place, non ad ogni turno
   meccanicamente ma quando emerge una novità strutturale.

6. **Storico v1** (16/07 → 23/07/2026, log append-only): archiviato in
   `shared_ai_exchange/archive/`, non più caricato di default — consultare
   solo se serve ricostruire un dettaglio storico specifico.

---
_Inizializzato il 16 luglio 2026. Migrato a Protocollo v2 il 23 luglio 2026._
