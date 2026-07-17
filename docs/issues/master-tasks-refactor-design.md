# Design — Refactor configurazione task (profili + varianti comportamentali)

> **STATO: DRAFT in discussione Claude ⇄ Gemini (weekend 18-19/07/2026).**
> **Deadline proposta definitiva: lunedì 20/07 ore 9:00.**
> Documento di lavoro: iterato durante il weekend, il log della discussione è
> in fondo. Nessuna implementazione finché la proposta non è approvata dall'utente.

## 0. Obiettivo e vincoli (dall'utente)

- Sistema **veramente solido, manutenibile**, che **non introduca regressioni
  o instabilità**.
- Gestione ampia e coerente di: **task standard**, **task custom**, **task nuovi**.
- **Valutazioni incrociate** Claude+Gemini, ogni affermazione verificata sul
  codice reale (standard v1.1 del protocollo di scambio).
- Preferita una **risposta ponderata** a una proposta immediata.

### Vincolo di design HARD (WU217, ribadito dall'utente 17/07)
- **Il master FauMorfeus è SEMPRE l'ultima istanza del ciclo**, fuori dal
  ranking adattivo (`ordina_istanze_adaptive`, posizione fissa). Aggiungere
  task al master **aumenta solo la durata media del ciclo**, non cambia
  l'ordinamento. Qualunque refactor deve preservare questo invariante.

## 1. Diagnosi stato attuale (verificata sul codice)

Tre meccanismi decidono "cosa gira" e si sovrappongono:

1. **`globali.task.*`** (`runtime_overrides.json`) — kill-switch farm-wide per
   task. Letto da `config_loader::_InstanceCfg.task_abilitato`.
2. **`tipologia`** istanza (`full` / `raccolta_only` / `raccolta_fast`) —
   profilo RIGIDO hardcoded. Governa:
   - filtro registrazione in `main.py::_thread_istanza` (`_solo_raccolta`,
     `_raccolta_fast`);
   - skip interni in alcuni task (`grafica_hq`/`pulizia_cache`);
   - risoluzione task list nel predictor (`cycle_duration_predictor` ~1035);
   - swap `RaccoltaTask → RaccoltaFastTask`.
3. **`master_task_whitelist`** (WU-MasterTasks 17/07) — toppa per il caso
   speciale master: lista task extra oltre a raccolta.

**Meccanismi ORTOGONALI da preservare** (segnalati da Gemini, verificati):
- **`forza_solo_raccolta`** (doppio giro FAU_00, `main.py`): priorità ASSOLUTA
  su qualunque profilo/whitelist → registra solo raccolta.
- **Time gates / `should_run`** (`shared/task_scheduling.py::TIME_GATES` +
  guard interni dei task): il profilo abilita NOMINALMENTE il task, ma lo skip
  dinamico (es. arena UTC≥10, master saturo, ecc.) governa l'esecuzione reale.

## 2. Requisiti del nuovo sistema

- **R1 — Selezione**: quali task gira ogni istanza, in modo dichiarativo e
  scalabile (non hardcoded, non per-caso-speciale).
- **R2 — Varianti comportamentali (PRIORITÀ, dall'utente)**: lo **stesso** task
  standard deve poter avere un **comportamento differenziato** per certe istanze.
  **Esempio reale confermato dall'utente (17/07): il task `arena`**, nella fase
  di **selezione/schieramento truppe** (oggi `_rebuild_truppe`, WU83/WU219:
  rimuove le squadre e fa auto-deploy della "migliore composizione" 1×/settimana).
  La variante deve poter scegliere fra:
    - **`config_partenza`**: schierare da una **configurazione di partenza**
      fissa (composizione predefinita), invece dell'auto-deploy "migliore";
    - **`no_modifica`**: **nessun effetto** — saltare il rebuild, lasciare le
      truppe schierate come sono;
    - (default attuale: auto-deploy "migliore composizione" via READY).
  Stesso "telaio" del task `arena`, diramazione del solo step di schieramento.
  > NB: NON è il task `truppe` (quello è l'addestramento caserme, altra cosa);
  > il primo esempio "truppe sync" era un fraintendimento, corretto dall'utente.
- **R3 — Predictor-aware**: il predictor deve risolvere dinamicamente la lista
  task effettiva per istanza (dal nuovo modello), niente check rigidi su
  `tipologia`. (Fix parziale già applicato per il master 17/07, commit `9751016`.)
- **R4 — Task nuovi**: aggiungere un task nuovo deve renderlo automaticamente
  disponibile alla selezione/composizione, senza toccare N punti.
- **R5 — Zero regressioni**: migrazione sicura dal modello attuale, con
  backward-compat e rollout graduale.

## 3. Proposta architetturale (DRAFT — da discutere)

### 3a. Livello SELEZIONE — profili data-driven + override
Ispirato alla proposta ibrida di Gemini:
- Nuovo file `config/profiles.json`: profili con nome, ognuno = set di task.
  Default: `completo`, `solo_raccolta`, `fast`, `master`.
- Ogni istanza in `runtime_overrides.json` dichiara `"profilo": "<nome>"`
  (sostituisce/estende `tipologia`).
- Override puntuale per-istanza: `"task_overrides": {"alleanza": false,
  "vip": true}` (on/off rispetto al profilo base).
- **Palette automatica**: la UI elenca tutti i task registrati (introspezione
  del catalogo `_import_tasks`/`task_setup.json`) → R4 gratis.
- Kill-switch globale `globali.task.*` resta come livello superiore (un task
  spento globalmente non gira comunque).

**Precedenza risolta (proposta)**: `forza_solo_raccolta` > kill-switch globale
> profilo + override > default. Da validare punto per punto.

### 3b. Livello VARIANTE — comportamento differenziato (il nodo difficile, R2)
Opzioni sul tavolo (da valutare insieme):

- **V1 — Condizionale nel task**: `if is_master(ctx): sync() else: train()`.
  Semplice, ma sparge logica-master in ogni task → poco manutenibile, viola
  "solido/manutenibile". ❌ tendenzialmente scartata.
- **V2 — Classi variante**: `TruppeTask` + `TruppeMasterTask`, registrate in
  base al profilo. Separazione netta ma proliferazione di classi + duplicazione
  del framework.
- **V3 — Parametro strategia (config-driven)**: il task legge un'opzione
  `variante` dal profilo/override (es. `truppe: {variante: "sync"}`) e dispatcha
  a una strategia interna. Classe unica, comportamento pluggable.
- **V4 — Policy/strategy objects iniettati**: il task delega gli step
  variabili a oggetti-policy risolti da config. Più potente di V3 ma più
  infrastruttura.

Solo i task che ne hanno bisogno espongono varianti; gli altri restano
identici (nessun costo per i task senza varianti).

**DECISO round 1 (Claude+Gemini concordi): V3 in forma STRUTTURATA.** La classe
principale del task (es. `ArenaTask`) fa il dispatch, ma la logica della variante
vive in un **modulo helper dedicato** nello stesso package (es.
`tasks/helpers/arena_deploy.py` con le strategie `config_partenza`/`no_modifica`)
— evita di gonfiare il file del task se la variante è complessa (proposta Gemini,
accolta). Classe unica + comportamento pluggable + file leggibili. Concretamente
sull'esempio arena: `_rebuild_truppe` diventa il punto di dispatch, la strategia
scelta dalla config decide se auto-deploy (default), schierare da preset, o
non toccare nulla.

**Vincolo di sicurezza sulle varianti (Gemini, VERIFICATO)**: una variante non
deve mai bypassare il ciclo di vita del navigator né rischiare deadlock su
schermata inattesa. Confermato sul codice che è già strutturalmente garantito:
`core/orchestrator.py:242` esegue un **gate HOME prima di OGNI task**
(`nav.vai_in_home()`), quindi ogni variante parte da HOME e deve ritornarci in
sicurezza come qualunque task standard. Il design deve solo rispettare questo
contratto esistente (nessuna nuova infrastruttura di sicurezza).

### 3c. Livello PREDICTOR — introspezione (R3)
Il predictor e l'adaptive scheduler risolvono la task-list per istanza da
`profilo + task_overrides` (una funzione unica condivisa, es.
`shared/task_resolution.py::risolvi_task_istanza(nome)`), usata da: `main.py`
(registrazione), predictor (stima), dashboard (UI/introspezione). Unica fonte
di verità → niente più logiche duplicate divergenti.

## 4. Analisi regressioni / rischi (da completare con Gemini)

| Area | Rischio | Mitigazione proposta |
|------|---------|----------------------|
| `main.py` filtro registrazione | Rompere `forza_solo_raccolta` / swap Fast | Funzione unica `risolvi_task_istanza`, test dedicati sui 3 casi |
| Predictor / adaptive | Stima errata task-list | Stessa funzione unica (3c); test su master+ordinarie |
| Doppio giro FAU_00 | Profilo che scavalca `forza_solo_raccolta` | Precedenza esplicita + test |
| Gate orari | Profilo abilita ma should_run deve governare | Invariato: profilo = nominale, should_run = reale |
| Migrazione config | `tipologia` → `profilo` su 12 istanze live | Bootstrap compat: `tipologia` legacy mappata a profilo equivalente (`raccolta_only`→`solo_raccolta`, `raccolta_fast`→`fast`, `full`→`completo`); feature-flag |
| Master-ultimo (WU217) | Refactor che rimette master in rotazione | Test di invariante: master sempre in coda |

**Garanzia "byte-identico" in Fase 1 (DECISO round 1, proposta Gemini accolta):**
un **test di parità automatizzato** (`tests/unit/test_migration_parity.py`)
risolve la task-list per tutte le 12 istanze reali con la VECCHIA logica
(`main.py` filtro + predictor storico) e con la NUOVA `risolvi_task_istanza`,
asserendo che le liste `(class_name, priority, interval_h)` siano
**identiche** sotto ogni combinazione di override. Finché il test è verde, la
Fase 1 è pura unificazione senza cambio funzionale. `risolvi_task_istanza`
mappa in modo trasparente il vecchio `tipologia` al profilo equivalente quando
il campo `profilo` non è presente (retrocompat).

> **NOTA (verificata round 1)**: il predictor a `cycle_duration_predictor.py`
> ~1035 NON ignora più la whitelist master — corretto oggi (commit `9751016`,
> Fase 0). Gemini si riferiva allo stato pre-fix. La `risolvi_task_istanza`
> di Fase 1 assorbirà anche questo, eliminando la logica ad-hoc.

## 4bis. Schema concreto (consolidato round 2, Gemini+Claude)

### `config/profiles.json` (statico)
Profilo = lista task nominali + `varianti` opzionali (variante per-task). L'unificazione
chiave: **`raccolta_fast` non è più una tipologia separata** ma il profilo `fast` =
tutti i task + `varianti: {raccolta: fast}`. Idem `master` = raccolta + set fisso.
```json
{
  "completo":      { "tasks": [<tutti i 19 task di task_setup.json>] },
  "solo_raccolta": { "tasks": ["raccolta", "raccolta_chiusura"] },
  "fast":          { "tasks": [<tutti>], "varianti": { "raccolta": "fast" } },
  "master":        { "tasks": ["raccolta", "raccolta_chiusura", "grafica_hq",
                     "pulizia_cache", "boost", "donazione", "vip", "alleanza",
                     "messaggi", "district_showdown"] }
}
```
> **CORREZIONE Claude (verificata) al profilo `master`**: per la **parità
> byte-identica di Fase 1** il profilo `master` deve corrispondere ESATTAMENTE
> alla `master_task_whitelist` attuale (10 task sopra) — **NIENTE `truppe`** e
> **niente `varianti`**. Gemini aveva incluso `truppe: sync`, ma truppe NON è
> nella whitelist di oggi: aggiungerlo romperebbe il test di parità. `truppe:
> sync` entra in **Fase 3** (varianti), non in Fase 1. In Fase 1 tutti i profili
> riproducono al bit il comportamento corrente.

### Istanza in `runtime_overrides.json` (esteso)
```json
"FauMorfeus": {
  "abilitata": true,
  "profilo": "master",
  "task_overrides":  { "boost": false },       // add(true)/remove(false) vs profilo
  "task_varianti":   { "arena": "config_partenza" }  // variante per-task (Fase 3); es. config_partenza | no_modifica
}
```
- `profilo` (str, default `"completo"`).
- `task_overrides` (dict[str,bool]): aggiunge/rimuove un task rispetto al profilo.
- `task_varianti` (dict[str,str]): imposta/cambia la variante di un task (precede
  la `varianti` del profilo). Pydantic: campi Optional, per non perderli al save.

### `shared/task_resolution.py::risolvi_task_istanza`
Fonte di verità unica per main.py (registrazione), predictor (stima), dashboard (UI).
```python
def risolvi_task_istanza(nome: str, overrides: dict | None = None,
                         forza_solo_raccolta: bool = False) -> list[dict]:
    """Combina, in ordine di precedenza:
      1. forza_solo_raccolta=True (doppio giro) → SOLO raccolta+raccolta_chiusura,
         classi STANDARD (mai fast) — INVARIANTE VERIFICATO (main.py:746,761).
      2. profilo (profiles.json; fallback: mapping legacy `tipologia`→profilo).
      3. task_overrides (add/remove) + task_varianti (variante).
      4. kill-switch globale globali.task.* (un task spento globalmente non entra).
    Ritorna list[dict] ordinata per priority, con:
      class_name, task_name, priority, interval_hours, schedule, variante|None.
    Risolve anche lo SWAP di classe: variante 'fast' su 'raccolta' → RaccoltaFastTask
    (raccolta_chiusura resta RaccoltaChiusuraTask — verificato: lo swap attuale tocca
    solo RaccoltaTask, main.py:764). main.py importa+esegue senza condizionali."""
```
priority/interval/schedule vengono da `config/task_setup.json` (join per task_name);
class_name dal catalogo `_import_tasks`/`_TASK_CLASS_TO_NAME`.

## 5. Piano a fasi (proposta di sequenza)

- **Fase 0** ✅ (fatto 17/07): fix predictor per master whitelist (commit `9751016`).
- **Fase 1**: `risolvi_task_istanza` unica + migrazione `tipologia`→`profilo`
  (retrocompat, `profiles.json` con i 4 default = comportamento IDENTICO a
  oggi). Nessun cambio funzionale, solo unificazione. Validazione a parità.
- **Fase 2**: `task_overrides` per-istanza + UI (sostituisce
  `master_task_whitelist`, che diventa un override del profilo `master`).
- **Fase 3**: meccanismo VARIANTI (R2) — implementazione su 1 task pilota
  (`truppe`, l'esempio dell'utente) con l'opzione scelta (V3?), poi estensione.
- **Fase 4**: cleanup (`tipologia` deprecata, whitelist assorbita).

## 6. Domande aperte per la discussione Claude ⇄ Gemini

> ### ⭐ DECISIONE APERTA A1 (richiede l'utente) — quali task avranno varianti?
> Il meccanismo varianti (§3b, V3 strutturata) è definito, ma **quali task ne
> hanno realmente bisogno** lo decide l'utente, per non sovra-ingegnerizzare.
> - **Confermato (corretto dall'utente 17/07)**: **`arena`** — variante sullo
>   schieramento truppe (`_rebuild_truppe`): `config_partenza` (schiera da
>   composizione predefinita) | `no_modifica` (salta il rebuild) | default
>   (auto-deploy "migliore"). NON è il task `truppe` (addestramento caserme).
> - **Già di fatto una variante**: `raccolta` → `fast` (la unifichiamo nel modello).
> - **Ipotesi da confermare/scartare** (speculative): `donazione`, `store`.
> - **Azione utente**: dare l'elenco reale dei task da differenziare (e come).
>   Fino ad allora, in Fase 3 si implementa SOLO la variante `arena`.



1. Modello profili: file `profiles.json` statico o gestibile da UI (creazione
   profili custom runtime)? Tradeoff persistenza/complessità.
2. Varianti (R2): V3 (parametro strategia) vs V4 (policy objects)? Quali task
   oltre a `truppe` avranno realisticamente varianti? (serve l'elenco reale
   dall'utente per dimensionare).
3. Migrazione: big-bang dietro feature-flag o task-per-task? Come garantire
   "comportamento byte-identico" in Fase 1?
4. `task_overrides` vs profili dedicati: quando conviene un override puntuale
   vs un nuovo profilo? Regola di stile per non ricadere nel caos attuale.
5. Dove vive la UI: pagina dedicata `/ui/profili`? Card per-istanza? Entrambe?

## 7. Log discussione (weekend)

- **17/07 21:xx — Claude**: draft V0.1 creato. Round 1 inviato a Gemini
  (canale seq 85). Review critica richiesta su §3b (varianti) e §4 (rischi).
- **17/07 22:00 — Gemini (seq 86)**: review round 1. Convergenza ampia.
  Contributi accolti (verificati sul codice): (a) §3b V3 **strutturata** con
  helper module dedicato (`tasks/helpers/<task>_<variante>.py`); (b) vincolo
  varianti = rispetto del gate HOME esistente (VERIFICATO `orchestrator.py:242`);
  (c) §4 test di parità `test_migration_parity.py` per la garanzia byte-identico
  in Fase 1 + mapping legacy `tipologia`→`profilo`; (d) profili STATICI in
  `profiles.json` (no creazione runtime da UI); (e) regola di stile profilo vs
  override; (f) UI = sezione espandibile nella card istanza (dropdown profilo +
  checklist se `custom`).
- **17/07 22:xx — Claude (V0.2)**: recepiti i punti sopra nel documento.
  Correzione fattuale a Gemini: il predictor NON ignora più la whitelist
  (fixato oggi, commit `9751016`). Round 2 → §autonomia (vedi sotto) + spinta
  alla consolidazione. **Modalità AUTONOMA attivata** (decisione utente 17/07):
  da qui Claude+Gemini discutono e convergono SENZA intervento dell'utente;
  i disaccordi si marcano "DECISIONE APERTA per l'utente", non si forza consenso.
- **17/07 22:20 — Gemini (seq 88)**: schema config concreto (`profiles.json` +
  istanza con `profilo`/`task_overrides`/`task_varianti`) + firma
  `risolvi_task_istanza` in `shared/task_resolution.py` + unificazione
  `raccolta_fast`→variante. Propone Decisione Aperta A1 (elenco varianti).
- **17/07 22:xx — Claude (V0.3)**: schema recepito in §4bis, verificato sul
  codice (invarianti forza_solo_raccolta e swap fast — main.py:746/761/764).
  **Correzione**: profilo `master` di Fase 1 = whitelist attuale SENZA `truppe`
  (byte-identità); truppe:sync è Fase 3. Decisione A1 marcata in §6. Convergenza
  quasi completa: manca solo consolidare in "PROPOSTA DEFINITIVA" + A1 (utente).
- **17/07 23:xx — Claude (V0.4, correzione utente)**: l'utente ha corretto
  l'esempio di variante: **NON è `truppe`, è `arena`** — variante sullo
  schieramento truppe in arena (`_rebuild_truppe`, WU83/WU219): `config_partenza`
  vs `no_modifica` vs default auto-deploy. Verificato sul codice
  (`tasks/arena.py:657-660`). Aggiornati §2 R2, §3b, §4bis, §6 A1. Il meccanismo
  V3-strutturato resta identico, cambia solo il task-pilota (arena, helper
  `tasks/helpers/arena_deploy.py`). Correzione notificata a Gemini.
- _(iterazioni successive appese qui)_
