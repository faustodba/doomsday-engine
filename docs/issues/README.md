# Archivio Issues per tematica

Storico completo delle voci WU/issue del progetto, **diviso per tematica** e consolidato
dalla tabella flat di `.claude/CLAUDE.md` (riorganizzazione 07/06/2026, voci verbatim).
CLAUDE.md ora tiene solo le **regole operative** + un riassunto degli **issue aperti**.

## Indice tematico

| Tema | File | Voci | Aperte |
|------|------|------|--------|
| Telegram bot | [telegram.md](telegram.md) | 4 | 0 |
| Notifiche & alert (email/Telegram) | [notifiche-alert.md](notifiche-alert.md) | 7 | 1 |
| Radar & anagrafe membri | [radar.md](radar.md) | 7 | 2 |
| Arena · Mercato · District Showdown · Boost | [arena-combat.md](arena-combat.md) | 51 | 4 |
| Rifornimento & Zaino | [rifornimento-zaino.md](rifornimento-zaino.md) | 41 | 2 |
| Raccolta | [raccolta.md](raccolta.md) | 35 | 1 |
| Truppe (addestramento) | [truppe.md](truppe.md) | 6 | 0 |
| Telemetria · Predictor · Scheduler | [telemetria-predictor.md](telemetria-predictor.md) | 15 | 1 |
| Dashboard & configurazione | [dashboard-config.md](dashboard-config.md) | 19 | 0 |
| OCR · Template matching · Banner | [ocr-vision.md](ocr-vision.md) | 17 | 2 |
| Infra · Startup · Launcher · ADB | [infra-startup.md](infra-startup.md) | 14 | 3 |
| Altro / trasversale | [altro.md](altro.md) | 7 | 0 |
| **TOTALE** | — | **223** | **16** |

## 🔓 Issue aperti / parziali (cross-tema)

| Tema | # | Issue | Priorità | Stato (sintesi) |
|------|---|-------|----------|-----------------|
| infra-startup | 12 | Stabilizzazione HOME FAU_01/FAU_02 non converge | MEDIA | 🟡 mitigato (window 30→60s commit `9c1dfb4`) |
| infra-startup | 49 | Ottimizzazioni startup istanza (DELAY_POLL, stable_polls, de | BASSA | 🆕 APERTA 24/04 — guadagno stimato ~90s/ciclo, rimandata post-stabilizzazione DS |
| arena-combat | 51 | DistrictShowdown — gate readiness popup fase 3/4/5 (tap a vu | BASSA | 🆕 APERTA 24/04 (downgrade ALTA→BASSA 04/05) — proposta: `_wait_template_ready` analogo a p |
| arena-combat | 52 | Notte 26/04 — produzione_corrente null + stab HOME 88% timeo | MIX | 🟡 parziale — 52c risolto da #56 WU24; 52a/b/d aperti |
| telemetria-predictor | 53 | Telemetria task & dashboard analytics — events JSONL + rollu | — | 🆕 APERTA 26/04 — MVP ~12h (memoria `project_telemetria_arch.md`) |
| ocr-vision | 54 | Banner catalog & dismissal pipeline boot stabilization — 573 | — | 🟡 parziale — framework + 3 banner attivi (exit_game_dialog, auto_collect_afk_banner, banne |
| rifornimento-zaino | 65 | Wait > 60s rifornimento → anticipare task post-raccolta nel  | BASSA | 🆕 APERTA 26/04 step 2 — quando wait>60s, eseguire prima i task post-raccolta poi tornare a |
| infra-startup | 72 | Fase 4 #69 false negative su gioco in background — exit earl | DA OSSERVARE | 🔍 26/04 osservato 1 volta su FAU_10 (19:36:39 "no Live Chat" exit ma gioco in background → |
| ocr-vision | 54 | Banner catalog & dismissal pipeline boot stabilization | — | 🟡 parziale (estesa con `pin_btn_x_close` + `pin_btn_back_arrow` in WU26/66) |
| notifiche-alert | 81 | Update Version popup gioco — detect + gestione | BASSA | 🆕 APERTA 28/04 (downgrade ALTA→BASSA 04/05) — pulsante "Update Version" + icona triangolo  |
| radar | — | Bot in modalità raccolta-only (28/04 19:45) | — | ⏸️ Tutti i task disabilitati da dashboard tranne `raccolta` (always) + `radar_census`. Mod |
| rifornimento-zaino | — | Notte 28→29/04 maintenance mode 6h49m (motivo "aggiornamento | — | ⚠️ Utente attiva manualmente maintenance da dashboard alle 22:56 28/04 (per aggiornare sof |
| arena-combat | — | Pulizia + reinstallazione istanze MuMu (29/04 pomeriggio) | — | 🛠️ IN CORSO 29/04 — utente sta reinstallando le istanze MuMu (cascata ADB persistente FAU_ |
| arena-combat | 89 | Template arena Failure/Continue/Victory stale — UI client ri | ALTA | 🟡 PARZIALE 30/04 10:10 (WU77) — con cascade ADB risolto da Issue #88, finalmente possibile |
| raccolta | — | Modalità raccolta_fast estesa a tutte le istanze (06/05 pome | — | 🟡 In corso 06/05 — utente attiva `tipologia=raccolta_fast` su tutte le istanze ordinarie + |
| radar | WU158 | Anagrafe avatar membri alleanza — POC validato 99% accuracy | — | 🟡 POC IMPLEMENTATO 12/05 (script standalone `c:/tmp/test_anagrafe_*.py`), **integrazione b |
