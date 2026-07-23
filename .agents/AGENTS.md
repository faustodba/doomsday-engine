# Regole di Progetto

## Comunicazione e Scambio con Claude Code

> **Protocollo v2 dal 23/07/2026** (migrazione proposta da Gemini stesso,
> approvata dall'utente): `gemini_to_claude.md`/`claude_to_gemini.md` sono
> stati archiviati in `shared_ai_exchange/archive/` e non sono più i file
> vivi dello scambio. Vedi `shared_ai_exchange/PROTOCOL.md` per la specifica
> completa.

- **[REGOLA] Verifica preliminare prima di inviare richieste**: Prima di scrivere qualsiasi richiesta o informazione per Claude Code in `shared_ai_exchange/updates.md` e prima di aggiornare lo stato del baton in `shared_ai_exchange/channel.json`, verifica sempre se nel frattempo sono giunte nuove richieste, messaggi o informazioni da Claude in `shared_ai_exchange/updates.md` (turno precedente, prima di sovrascriverlo) o in `shared_ai_exchange/channel.json`. Questo previene collisioni di scrittura e assicura che nessuna comunicazione recente vada ignorata.
- Per lo stato consolidato del progetto (issue aperte/risolte, debito
  tecnico) vedi `shared_ai_exchange/state.json` — ogni voce riporta sia
  `status` (stato del codice) sia `deployment_status` (stato reale in
  produzione) come campi separati: un fix committato non è detto sia già
  attivo sul bot in esecuzione (serve verificarlo, es. da quando gira il
  processo prod rispetto al commit).
