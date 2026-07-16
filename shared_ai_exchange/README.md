# Cartella di Scambio Asincrono tra AI (Gemini & Claude Code)

Benvenuto in questo spazio di collaborazione! Questa cartella è stata creata per permettere a **Gemini** (l'assistente corrente nell'IDE) e **Claude Code** (l'agente CLI per lo sviluppo) di passarsi consegne, specifiche e report in modo asincrono.

## Protocollo di Scambio

1. **Da Gemini a Claude Code**:
   * Quando Gemini ha bisogno di delegare un'analisi, un refactoring o una unit test a Claude, scriverà i dettagli all'interno del file:
     👉 `shared_ai_exchange/gemini_to_claude.md`
   * All'interno troverai istruzioni passo-passo, file da modificare, standard richiesti e domande per Claude.

2. **Azione dell'Utente**:
   * Apri il tuo terminale con Claude Code e ordina:
     > *"Leggi il file `shared_ai_exchange/gemini_to_claude.md`, esegui i compiti indicati e scrivi il report di risposta in `shared_ai_exchange/claude_to_gemini.md`."*

3. **Da Claude Code a Gemini**:
   * Claude scriverà l'esito del suo lavoro, il codice modificato, i log dei test o le risposte a Gemini nel file:
     👉 `shared_ai_exchange/claude_to_gemini.md`
   * Gemini leggerà questo file nel turno successivo per validare i cambiamenti e continuare l'orchestrazione.

---
_Inizializzato il 16 luglio 2026._
