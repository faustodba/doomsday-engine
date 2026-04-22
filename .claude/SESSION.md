# SESSION.md — Handoff Doomsday Engine V6

## Sessione 22/04/2026 — in corso (focus: dashboard)

### Modifiche pendenti (da committare)
- `dashboard/models.py` — nuovi modelli Pydantic (SistemaOverride, ZainoOverride, AllocazioneOverride, payload per sezione)
- `dashboard/routers/api_config_overrides.py` — 5 endpoint per sezione + patch singolo task/istanza
- `dashboard/services/config_manager.py` — save_instances_fields + get_merged_config
- `dashboard/app.py` — partial corretti (ist-table editabile 7 col, task-flags-v2 compound, inst-grid, storico filtrato, res-totali, res-oraria)
- `dashboard/templates/index.html` — two-column layout + sticky sidebar risorse
- `dashboard/templates/base.html` — palette ambra, active home
- `dashboard/static/style.css` — unificato ambra Share Tech Mono, page-layout two-column

### Deprecazioni applicate
- Campo `layout` rimosso dalla tabella istanze UI (bot ora usa template matching)
- `layout` mantenuto Optional in models.py per retrocompat. file esistenti

### Stato dashboard al commit
- Layout two-column: main-col (tutto il contenuto) + side-col sticky (risorse farm)
- Sezioni: istanze grid | task flags + globals | cfg 3 col (rifornimento/zaino/allocazione) | istanze table | storico
- Tutti i form collegati agli endpoint /api/config/* via fetch PUT
- Dati risorse farm: placeholder (endpoint res-totali, res-oraria restituiscono —)
- Task flags compound: rifornimento (mappa|membri) + zaino (bag|svuota)
- Route /ui usa get_merged_config() — fix Issue #18 applicato

### Issues chiuse in sessione 22/04
- ✅ Issue #18 — Dashboard /ui ora passa merged config (get_merged_config)
- ✅ Cleanup legacy dashboard (sessione 21/04, commit a8704aa)

### Issues aperte rilevanti
- #14 Arena START CHALLENGE non visibile (ALTA)
- #15 engine_status.json stale writer (ALTA)
- #16 OCR FAU_10 compila/reali (MEDIA)
- #17 Storico engine_status filtrato (MEDIA)
- #21 gitignore duplicato + rifornimento_mappa.py V5 legacy (BASSA)
- #23 smoke_test GlobalConfig dict vs dataclass (BASSA)

### Prossima sessione — step by step
1. Commit batch (questo SESSION.md incluso) + push
2. Validare layout dashboard in browser (http://localhost:8765/ui)
3. Implementare dati reali per pannello risorse farm (stats_reader)
4. Fix Issue #15 engine_status stale writer
5. Fix Issue #14 arena (investigare template + UI flow)
