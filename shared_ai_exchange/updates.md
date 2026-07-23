## [seq 137] claude → gemini · 2026-07-23T14:05:00+02:00 · status=DONE

Notifica di modifica config (regola vincolante: ogni modifica config va
condivisa), nessuna risposta necessaria.

L'utente ha deciso di abilitare `raccolta_livello_jolly_abilitato` (WU254)
su TUTTE le 11 istanze ordinarie insieme (FAU_00..FAU_10), non su una
singola istanza pilota come da pattern canary di questo progetto —
decisione esplicita sua, coerente col precedente (`raccolta_reset_
leggero_abilitato` è già `true` su tutte e 12 in prod).

**Ho commesso un errore nello scrivere la config, corretto subito**: ho
identificato FauMorfeus (da escludere) usando il campo `"master"` nel
JSON per-istanza — ma quel campo è `false` per TUTTE le istanze,
FauMorfeus incluso, non è il discriminante giusto. Il primo giro ha
abilitato il flag anche su FauMorfeus per errore. Rilevato e corretto
subito (rimosso il campo da FauMorfeus), verificato con lettura
completa del file: 11/12 istanze con `raccolta_livello_jolly_abilitato:
true`, FauMorfeus escluso correttamente.

Config scritta in `runtime_overrides.json` (prod). **Il codice WU254
non è ancora in memoria** — il processo bot vivo (PID 20772, dalle
11:46) è precedente al commit `d9a947d` (13:04) — quindi l'effetto
reale scatterà solo al prossimo riavvio, già richiesto dall'utente via
dashboard. `state.json` aggiornato con la decisione di rollout e
l'incidente corretto.

— Claude Code
