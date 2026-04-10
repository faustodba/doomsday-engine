# DOOMSDAY ENGINE V6 — ROADMAP

Repo: `faustodba/doomsday-engine` — `C:\doomsday-engine`

## Struttura cartelle

```
doomsday-engine/
├── core/                        # Layer infrastruttura
├── shared/                      # Utilities condivise tra task
├── config/                      # Configurazione tipizzata
├── tasks/                       # Task del bot (uno per modulo)
├── tests/
│   ├── unit/                    # Test layer core e shared
│   ├── tasks/                   # Test ogni singolo task
│   └── fixtures/                # PNG screenshot + JSON stati
├── dashboard/                   # Server REST + frontend
└── main.py
```

---

## Step completati ✅

| Step | File | Cartella | Note |
|------|------|----------|------|
| 1 | `device.py` | `core/` | MuMuDevice + Screenshot + FakeDevice |
| 2 | `state.py` | `core/` | InstanceState |
| 3 | `logger.py` | `core/` | StructuredLogger |
| 4 | `ocr_helpers.py` | `shared/` | |
| 5 | `template_matcher.py` | `shared/` | TemplateCache + TemplateMatcher |
| 6 | `navigator.py` | `core/` | GameNavigator, Screen enum |
| 7 | `config.py` + `instances.json` | `config/` | InstanceConfig |
| 8 | `scheduler.py` | `core/` | TaskScheduler |
| 9 | `task.py` | `core/` | Task ABC + TaskContext + TaskResult |
| 10 | `rifornimento_base.py` | `shared/` | compila_e_invia, leggi_* |
| 11 | `boost.py` + `test_boost.py` | `tasks/` + `tests/tasks/` | daily priority=10, 7 template pin/ |
| 12 | `store.py` + `test_store.py` | `tasks/` + `tests/tasks/` | periodic 4h, scan spirale, 12 template pin/ |
| 13 | `messaggi.py` + `test_messaggi.py` | `tasks/` + `tests/tasks/` | periodic 4h, 3 template pin/ |
| 14 | `alleanza.py` + `test_alleanza.py` | `tasks/` + `tests/tasks/` | periodic 4h, nessun template (pixel check) |
| 15 | `vip.py` + `test_vip.py` | `tasks/` + `tests/tasks/` | daily priority=15, 7 template pin/ |

---

## Step rimanenti

| Step | File task | File test | Note |
|------|-----------|-----------|------|
| 16 | `tasks/arena.py` | `tests/tasks/test_arena.py` | Arena of Glory, daily |
| 17 | `tasks/arena_mercato.py` | `tests/tasks/test_arena_mercato.py` | Pack 360 + Pack 15, periodic |
| 18 | `tasks/radar.py` | `tests/tasks/test_radar.py` | Radar census + RF, periodic |
| 19 | `tasks/zaino.py` | `tests/tasks/test_zaino.py` | Svuotamento zaino, periodic |
| 20 | `tasks/rifornimento.py` | `tests/tasks/test_rifornimento.py` | Lista membri + mappa |
| 21 | `tasks/raccolta.py` | `tests/tasks/test_raccolta.py` | Task più complesso |
| 22 | `core/orchestrator.py` | `tests/unit/test_orchestrator.py` | Loop principale async |
| 23 | `dashboard/server.py` + `dashboard/dashboard.html` | — | WebSocket, ultimo step |

---

## Principi di sviluppo

1. **Ordine degli step è vincolante** — ogni layer dipende dal precedente.
2. **Nessun task in produzione senza test verde.**
3. **File sempre completi** — mai patch parziali.
4. **Prima di modificare un file esistente** — richiedere sempre la versione aggiornata dal PC.
5. **Ogni step = 1 commit** con messaggio `feat: Step N — descrizione`.
6. **MuMu only** — BlueStacks rimosso dal design.
7. **Porta ADB** = `16384 + index * 32`.
8. **Tutti i task** implementano `Task` ABC da `core/task.py`.
9. **Tutti i test task** usano `FakeDevice` + `FakeMatcher` — zero ADB reale.
10. **Scheduling**: boost/vip/arena = `daily`; store/messaggi/alleanza/radar/arena_mercato = `periodic`.
11. **Template**: tutti i PNG in `templates/pin/` — cartella piatta unica. Nessuna sottocartella per task. I path nei `*Config` usano sempre il prefisso `pin/` (es. `"pin/pin_store.png"`).

---

## Comando commit standard per ogni step

```bat
cd C:\doomsday-engine
git add tasks/<nome>.py tests/tasks/test_<nome>.py
git commit -m "feat: Step N — tasks/<nome>.py + test"
git push origin main
```
