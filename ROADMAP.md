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

| Step | File | Cartella |
|------|------|----------|
| 1 | `device.py` | `core/` |
| 2 | `state.py` | `core/` |
| 3 | `logger.py` | `core/` |
| 4 | `ocr_helpers.py` | `shared/` |
| 5 | `template_matcher.py` | `shared/` |
| 6 | `navigator.py` | `core/` |
| 7 | `config.py` + `instances.json` | `config/` |
| 8 | `scheduler.py` | `core/` |
| 9 | `task.py` (ABC + TaskContext + TaskResult) | `core/` |
| 10 | `rifornimento_base.py` | `shared/` |
| 11 | `boost.py` + `test_boost.py` | `tasks/` + `tests/tasks/` |

---

## Step rimanenti

| Step | File task | File test | Note |
|------|-----------|-----------|------|
| 12 | `tasks/store.py` | `tests/tasks/test_store.py` | Mysterious Merchant, scan spirale |
| 13 | `tasks/messaggi.py` | `tests/tasks/test_messaggi.py` | Tab Alleanza + Sistema |
| 14 | `tasks/alleanza.py` | `tests/tasks/test_alleanza.py` | Dono → Negozio → Attività |
| 15 | `tasks/vip.py` | `tests/tasks/test_vip.py` | Red-dot pixel check, cassaforte |
| 16 | `tasks/arena.py` | `tests/tasks/test_arena.py` | Arena of Glory daily |
| 17 | `tasks/arena_mercato.py` | `tests/tasks/test_arena_mercato.py` | Pack 360 + Pack 15 |
| 18 | `tasks/radar.py` | `tests/tasks/test_radar.py` | Radar census + classificatore RF |
| 19 | `tasks/zaino.py` | `tests/tasks/test_zaino.py` | Svuotamento zaino settimanale |
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

---

## Comando commit standard per ogni step

```bat
cd C:\doomsday-engine
git add tasks/<nome>.py tests/tasks/test_<nome>.py
git commit -m "feat: Step N — tasks/<nome>.py + test"
git push origin main
```
