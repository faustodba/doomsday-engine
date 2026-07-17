# Revisione tecnica Doomsday Engine V6 — bot + dashboard (luglio 2026)

> **STATO: IN CORSO — revisione autonoma Claude ⇄ Gemini (avviata 17/07/2026 sera).**
> Deliverable a incrementi: documento tecnico (findings motivati+verificati) +
> planning a fasi. **Solo analisi: nessuna modifica al codice senza approvazione
> utente.** Ogni finding verificato sul codice reale + dati live (standard v1.1).

## 0. Metodo e governance

- **Scope**: tutti e 4 gli assi (scelta utente 17/07): (1) Correttezza &
  robustezza, (2) Architettura & manutenibilità, (3) Performance & efficienza,
  (4) Dashboard + Affidabilità/Test. Consegna a **incrementi** (un asse/tema alla
  volta), non un mega-documento unico.
- **Divisione ruoli** (a verbale, vedi `master-tasks-refactor-design.md` §8):
  Gemini = ricognizione ampia + mining log/telemetria + prime bozze; Claude =
  verifica critica + qualificazione severità + sintesi architetturale.
- **Regole finding**: ogni voce ha `[ID] titolo · asse · severità · evidenza
  (file:riga / log / dato live) · riproducibilità · proposta`. Niente
  affermazioni non verificate. I dubbi → "DECISIONE APERTA per l'utente".
- **Escalation immediata**: bug che perde dati / regressione attiva / rischio
  sicurezza → segnalati subito all'utente, non a fine revisione.
- **Baseline**: si riconcilia con `docs/analisi_2026-06-07.md` (27 findings, piano
  5 fasi) — marcare risolto / stale / ancora-valido prima di aggiungere nuovo.
- **No script ADB esterni su istanze live** (lezione WU185): solo log + MCP monitor.

## 1. Fase A — Inventario & baseline (in corso)

### 1a. Snapshot live iniziale (17/07 ~20:50 UTC)
- Bot in esecuzione, **0 anomalie** negli ultimi 10 min (MCP `anomalie_live`).
- Contesto noto da oggi (già in `docs/issues/`): master 10/10 task OK, canary
  reset-leggero chiuso 67/67, ciclo "starved" per i riavvii odierni (si
  auto-ripara). Questi NON sono findings nuovi, sono stato noto.

### 1b. Riconciliazione con analisi 07/06 (DA FARE — assegnato)
Rileggere `docs/analisi_2026-06-07.md` e marcare ogni voce:
- **§2 Punti critici** (per rischio) → ancora aperti? risolti da WU successivi?
- **§3 Ottimizzazioni ROI**, **§5 Debito tecnico**, **§6 Piano** → stato attuale.
Output: tabella "07/06 → stato 07/17" (verificata sul codice, non a memoria).

### 1c. Mappa subsystem + hotspot (DA FARE — assegnato a Gemini, mining)
Inventario dei subsystem (tasks/, core/, shared/, dashboard/) con dimensione,
n. funzioni, ultima modifica, e primo scan di **hotspot di rischio** (pattern:
`except: pass` silenziosi, `TODO/FIXME`, duplicazioni logiche, `sleep` fissi,
handle non chiusi, test falliti). Grezzo da verificare poi.

## 2. Findings per asse (popolati a incrementi)

### Asse 1 — Correttezza & robustezza
_(in attesa Fase A)_

### Asse 2 — Architettura & manutenibilità
- **[seed, già noto]** Config-tangle risoluzione task list (3 meccanismi
  sovrapposti) — già in refactor, vedi `master-tasks-refactor-design.md`. Non
  ri-analizzare, referenziare.

### Asse 3 — Performance & efficienza
- **[seed, da verificare]** Timeout arena (~78% sfide a timeout 10s) — osservato
  oggi, ipotesi template stale (issue `arena-combat.md`). Candidato asse 3+1.
- **[seed, da verificare]** Delay UI fissi (`sleep(2.0)` ecc.) — misura in corso
  (rifornimento delay-measure). Referenziare.

### Asse 4 — Dashboard + Affidabilità/Test
- **[seed, sistemico]** Bug-class field-wipe Pydantic (`IstanzaOverride`) —
  colpito 2 volte oggi (raccolta_reset_leggero + master_task_whitelist mancanti
  dal modello). Verificare se altri campi runtime_overrides sono a rischio.
- **[seed]** ~51 test falliti pre-esistenti (`ImportError: KeyCall`, marker
  asyncio, firme disallineate) — inventariare e classificare.

## 3. Planning prioritizzato (a fine analisi)
_(matrice impatto × sforzo × rischio — da compilare)_

## 4. Log revisione (autonomo)
- **17/07 ~23:xx — Claude**: doc creato, Fase A avviata (snapshot live). Kickoff
  a Gemini con divisione compiti: Gemini → 1b riconciliazione 07/06 + 1c mining
  hotspot; Claude → verifica e qualificazione. Cadenza 20-30 min, incrementi.
