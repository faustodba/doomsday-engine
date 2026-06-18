# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`
V5 (produzione): `faustodba/doomsday-bot-farm` — `C:\Bot-farm`

---

## Sessione 18/06/2026 — Fix MessaggiTask (tab bar stale + dual-tab uncommitted)

**WU165 — `tasks/messaggi.py` falliva da giorni** ("schermata non aperta" sistematico).
Diagnosi forense con `cv2.matchTemplate` pixel-precisa su 104 screenshot debug reali
(`data/messaggi_debug/`): il client gioco ha aggiunto i tab REPORT/SENT/BOOK alla
schermata Messaggi (prima solo Alliance+System), spostando a sinistra le posizioni
di Alliance e System. Le ROI/tap configurate erano stale: **0/104** screenshot
superavano la soglia con le vecchie coordinate, **103/104** con quelle ricalibrate.

Fix applicato (dev+prod):
- `roi_alliance`: `(283,23,367,47)` → `(145,15,250,50)`
- `roi_system`: `(417,23,490,50)` → `(280,15,377,50)`
- `tap_tab_alliance`: `(325,35)` → `(198,34)`
- `tap_tab_system`: `(453,36)` → `(328,34)`

Incluso nello stesso commit anche il fix "PRE-OPEN DUAL-TAB" (`_rileva_tab_attivo` +
`skip_tap`), che era già live in prod (copiato a mano) ma mai committato in dev —
gap di processo rispetto al protocollo Rilasci.

**Test suite stale scoperta e corretta**: `tests/tasks/test_messaggi.py` era ancora
scritto per la vecchia API single-tab (`MessaggiConfig(wait_back=...)`, `cfg.n_back_close`
— campi non più esistenti) e falliva 15/27, nonostante la ROADMAP dichiarasse 27/27.
Riscritto con copertura per `_rileva_tab_attivo()` e `skip_tap` in `_gestisci_tab()`.
Ora 35/35 verdi. Commit `e038736`, pushato su `main`.

**Nota dead-config risolta nello stesso giorno** (commit `54ab117`): `time.sleep(3.0)`
hardcoded in `_esegui_messaggi`/`_gestisci_tab` ignorava `cfg.wait_open`/`cfg.wait_tab`,
rendendo inefficace il tuning manuale fatto dall'utente in precedenza (tentativo di
fix prima di scoprire la causa reale). Wired ai campi cfg; `wait_tab` default
2.0→3.0 per preservare il timing reale già in esecuzione (nessun cambio comportamento
a runtime). Bonus: i test ora azzerano davvero i sleep (`_cfg_zero()`), suite passata
da 60s a 0.14s.

**Bug telemetria scoperto e risolto** (commit `6e1c5ce`): l'utente ha notato che la
dashboard/MCP `performance_task` mostrava messaggi al "100% eseguiti" nonostante il
fallimento multi-giorno. Causa: `_mappa_esito()` mappava `SCHERMATA_NON_APERTA` su
`TaskResult.skip()` (success=True) — `main.py:915` (`esito = "ok" if lr.success else
"err"`) non distingue skip da vero completamento, quindi lo storico/dashboard
mostrava "ok" per ogni fallimento. La telemetria granulare (`data/telemetry/events`,
campo `outcome`) registrava invece correttamente 441 skip vs 9 ok da inizio giugno —
discrepanza tra le due viste confermata da verifica diretta. Fix: "schermata non
aperta" non è un no-op legittimo ma un'incapacità di eseguire il task → ora
`TaskResult.fail()`. Effetto collaterale positivo: per WU79 `last_run` non avanza su
fail, quindi un blocco analogo futuro viene ritentato al ciclo successivo invece di
aspettare le 4h piene in silenzio. Test aggiornati, 35/35 verdi.

**WU166 — Pulizia cache: storico persistente + alert proattivo.** Scoperto durante
l'indagine WU165 (l'utente ha chiesto verifica esplicita "funziona la clear cache
mattutina?"): la pulizia FUNZIONAVA correttamente per tutte le 11 istanze del 18/06
(confermato via `cache_state.json` + `data/cache_debug/`), ma senza nessuna traccia
persistente — bypassa Task/telemetria e le righe `[CACHE]` nei log istanza si perdono
alla rotazione (solo l'ultimo tick resta in `logs/<NOME>.jsonl`). Un fallimento notturno
sarebbe stato invisibile.

Fix in 2 parti (dev+prod):
- `core/settings_helper.py::_log_cache_history()` — append-only `data/cache_history.jsonl`,
  un record per ogni tentativo (ok/fail/durata/msg).
- `core/alerts.py::check_cache_pulizia_giornaliera(cutoff_hour_utc=12)` — alert se manca
  la marca giornaliera dopo mezzogiorno UTC. Esclude istanze `tipologia=="raccolta_only"`
  (FauMorfeus/master, replica esatta esclusione `core/launcher.py:1064`) per evitare falsi
  positivi. Wired in `main.py` accanto a `check_master_saturo`/`check_heartbeat_cicli`/
  `check_maintenance_long`. Cooldown 4h.

Nessun test dedicato (repo non testa unitariamente `core/` helper, solo `tasks/*.py`).
Effetto al prossimo restart bot (flag one-shot già armato per WU165).

---

## Sessione 07/06/2026 — Analisi multi-agente + Fase 0 + notifiche A+B

**Analisi approfondita read-only** (44 agenti, 16 subsystem) → `docs/analisi_2026-06-07.md`.
27 findings critical/high verificati su codice (0 falsi positivi). 5 temi ricorrenti:
(1) monitoring cieco, (2) default silenzioso da config, (3) success spurio su screenshot
None, (4) fragilità OCR/ROI, (5) igiene repo. Piano in 5 fasi (0=osservabilità → 4=igiene).

**Fix max_squadre** (WU-MaxSquadre, bug-class C6) — FAU_00/FauMorfeus usavano 4 slot invece
di 5: `_ovr("max_squadre", 4)` legge solo dynamic, il campo mancava in `runtime_overrides`
→ fallback hardcoded. Fix dynamic `max_squadre: 5`. Validato: FAU_00 `inviate=5`.

**Fase 0 — osservabilità** (WU163, commit `5090ef5`):
- C1/O1 `check_heartbeat_cicli`: leggeva `cicli.json` (dict) come lista + chiave `ts_end`
  errata → l'unico alert *critical* "bot morto" non scattava MAI. Fix: `load_cicli()` + `end_ts`.
- C3/O4 `record_istanza_tick_end`: hardcoded `esito="ok"` anche su cascade → sezioni
  cascade/abort/fail del daily report codice morto. Fix: thread propaga esito reale via
  `_ultimo_esito_tick` letto dopo `t.join()`.

**Notifiche A+B** (WU164, commit `0e9e04b` + config dynamic):
- Errore salvataggio dashboard "from_addr non valido" = mittente vuoto (validazione endpoint).
- A: `enabled/alerts_enabled=true` + `from_addr=bot.dooms.report@gmail.com` +
  `recipients=[fausto.pace@gmail.com]` (hot-reload).
- B: `notify_alert` generico + routing heartbeat/maintenance/restart su Telegram (prima solo
  cascade/DRL). Coupling: `trigger_alert` richiede ≥1 destinatario email anche per Telegram.

**Restart**: armato (flag manuale one-shot), scatta a fine ciclo 426 per attivare B.

> **Issues aperti dall'analisi** (in `docs/analisi_2026-06-07.md`): Fase 1 (success spuri
> marcia/spedizione su screenshot None C4/C9, atomic blacklist C7, store skip C8, OCR 999M C10);
> Fase 2 (merge `_save_ov` C5, fallback `_ovr` static C6, auth dashboard C2); Fasi 3-4 perf+igiene.

---

## Stato step pytest

| Step | File principali | Test | Note |
|------|----------------|------|------|
| 1-10 | `core/`, `shared/`, `config/` | ✅ | Infrastruttura base |
| 11 | `tasks/boost.py` | ✅ 35/35 | |
| 12 | `tasks/store.py` | ✅ 39/39 | VIP Store + mercante diretto |
| 13 | `tasks/messaggi.py` | ✅ 35/35 | WU165 18/06: ricalibrazione tab bar + commit fix dual-tab |
| 14 | `tasks/alleanza.py` | ✅ 24/24 | |
| 15 | `tasks/vip.py` | ✅ 30/30 | |
| 16 | `tasks/arena.py` | ✅ 10/10 | tap_barra("campaign") |
| 17 | `tasks/arena_mercato.py` | ✅ 10/10 | struttura V5+V6, tap_barra |
| 18 | `tasks/radar.py` + `radar_census.py` | ✅ 16/16 | |
| 19 | `tasks/zaino.py` | ✅ 39/39 | |
| 20 | `tasks/rifornimento.py` | ✅ 47/47 | |
| 21 | `tasks/raccolta.py` | ✅ 57/57 | territorio + allocation gap V5 |
| 22 | `core/orchestrator.py` | ✅ 49/49 | |
| 23 | `dashboard/` | ✅ 30/30 | |
| 24-25 | Fix + refactoring | ✅ | |
| 26 | `dashboard/` V6 rewrite | ✅ | FastAPI+HTMX, 6 test client, commit `9773de3` |
| **nav** | `core/navigator.py` | ✅ 20/20 | tap_barra() TM barra inferiore |
| **main** | `main.py` + `smoke_test.py` | ✅ 61/61 | |

---

## Piano test runtime — Stato al 21/04/2026

| Test | Descrizione | Stato | Note |
|------|-------------|-------|------|
| RT-01..05 | Infrastruttura, navigator, OCR, slot | ✅ | |
| RT-06 | VIP claim | ✅ | |
| RT-07 | Boost | ✅ | BoostState scheduling 16/04/2026. RIAPERTO 19/04 (tap non responsivo) → RISOLTO 19/04 (tap `speed_cx/speed_cy`, cy<400 responsivo, polling `pin_speed_use` 4s). Verificato FAU_00 test isolato ore 18:12 + FAU_01 ciclo completo da freddo: boost 8h attivato entrambi. |
| RT-08 | Messaggi + Alleanza | ✅ | |
| RT-09 | Store | ✅ | 18 acquistati + Free Refresh |
| RT-10 | Arena | ✅ | 5 sfide + skip checkbox |
| RT-11 | Raccolta V6 upgrade | ✅ | OCR coord X_Y, ETA, interleaving, psm=6 fix 3/5→5/5. Test 2/5→3 marce + 5/5→skip. 15/04/2026 |
| RT-12 | Tick completo FAU_01 | ✅ | Tick completo funzionante |
| RT-tap | tap_barra barra inferiore | ✅ | score=1.000 tutti 5 bottoni su FAU_01 |
| RT-15 | Arena + ArenaMercato | ✅ | Arena: 5/5 sfide 8.4s/sfida; ArenaMercato: pack360=5; fix BACK×2 |
| RT-16 | Rifornimento via mappa | ✅ | 5/5 spedizioni, qta reale 4M, provviste tracciate, soglia/abilitazione OK |
| RT-17 | Rifornimento via membri | ✅ | 1/1 spedizione, navigazione lista alleanza, avatar trovato, btn risorse 0.986 |
| RT-18 | Scheduling restart-safe | ⏳ | VIP daily OK (skip <24h, ISO string). Da testare: (1) periodic skip <interval; (2) --force daily; (3) restore_to_orchestrator al riavvio main.py |
| RT-19 | Radar + RadarCensus | ✅ | badge OK (78,315), pallini 2/2, census 10 icone, map_annotated OK. Fix pendente: falso positivo "Complete All" zona basso-sx |
| RT-20 | Zaino BAG + SVUOTA | ✅ | bag: TM-based scan+greedy+esecuzione, caution popup, fix campo qty. svuota: sidebar+USE MAX validata. Entrambe le modalità chiuse |
| RT-21 | Pytest aggiornato 258/258 | ✅ | BoostState/VipState/ArenaState/RifornimentoState + gate should_run() orchestrator. 16/04/2026 |
| RT-13 | Multi-istanza FAU_00+FAU_01 | ⏳ | dopo RT-18 + RT-22..24 |
| RT-14 | Full farm 12 istanze | ⏳ | |
| RT-22 | Ciclo notte prod 20→21/04 | 🟡 | 25 cicli 22:30→05:51, raccolta 24OK/6ERR. Rifornimento validato 11/11 istanze → **68 spedizioni, ~140.7M risorse** a FauMorfeus (legno 91.8M, petrolio 31.8M, pomodoro 17.1M). **Aperti:** arena 5 istanze KO (Issue #14), engine_status stale (#15), OCR legno anomalo FAU_10 (#16). |

---

## Indice documentazione

La cronologia dettagliata e lo storico issue sono stati riorganizzati (07/06/2026).
Questo file resta la vista **corrente + strutturale**; il resto è linkato qui.

### Issue & changelog
| Cosa | Dove |
|------|------|
| Stato issue **per tematica** (storico WU completo) | [`docs/issues/`](docs/issues/README.md) |
| Issue **aperti** (riassunto) | [`.claude/CLAUDE.md`](.claude/CLAUDE.md) → "Issues — stato sintetico" |
| Storico cronologico ROADMAP (sessioni, "Fix applicati") | [`docs/changelog/ROADMAP-storico.md`](docs/changelog/ROADMAP-storico.md) |
| Analisi architetturale 07/06 (punti critici, piano 5 fasi) | [`docs/analisi_2026-06-07.md`](docs/analisi_2026-06-07.md) |

### Architettura & riferimento
| Cosa | Dove |
|------|------|
| Overview architettura sistema | [`docs/OVERVIEW.md`](docs/OVERVIEW.md) |
| Architettura bot Telegram | [`docs/TELEGRAM_BOT_ARCHITECTURE.md`](docs/TELEGRAM_BOT_ARCHITECTURE.md) |
| Reference API moduli | [`docs/reference.html`](docs/reference.html) |
| Regole operative & standard V6 | [`.claude/CLAUDE.md`](.claude/CLAUDE.md) |

### Tematiche issue
- [Raccolta](docs/issues/raccolta.md) · [Rifornimento & Zaino](docs/issues/rifornimento-zaino.md) · [Arena/Combat](docs/issues/arena-combat.md) · [Truppe](docs/issues/truppe.md)
- [Radar](docs/issues/radar.md) · [Dashboard & Config](docs/issues/dashboard-config.md) · [Telemetria/Predictor](docs/issues/telemetria-predictor.md)
- [Notifiche & Alert](docs/issues/notifiche-alert.md) · [OCR/Vision](docs/issues/ocr-vision.md) · [Infra/Startup](docs/issues/infra-startup.md) · [Telegram](docs/issues/telegram.md)
