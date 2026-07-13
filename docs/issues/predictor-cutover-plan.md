# Cutover Predictor — da modello statico T_marcia a misura empirica tempo di raccolta

> Estratto e ampliato il 12/07/2026 dall'analisi WU200ter (memoria
> `project_tempo_raccolta_estimator.md`) con **verifica sui dati reali prod**
> e **design del cutover**. Fonte di verità operativa: questo file.
> Voce sintetica in `.claude/CLAUDE.md` (tema telemetria-predictor) e
> `docs/issues/telemetria-predictor.md` (WU200ter).

---

## 1. Scopo

Il sistema `report_raccolta` + `tempo_raccolta_estimator` (WU199/WU200) misura
il **tempo di raccolta reale** per `(istanza, tipo, livello)` incrociando due
eventi indipendenti dello stesso nodo (invio ↔ completamento report). Questo
documento definisce **cosa del predictor attuale va sostituito, cosa va tenuto
come fallback, cosa va eliminato**, e il **piano di cutover a fasi senza
regressione**.

Stato di partenza: WU200ter ha già collegato lo stimatore all'adaptive
scheduler **in sola osservazione** (campo `confronto_tempo_raccolta`, nessuna
decisione ne dipende). Questo è il passo che decide se e come rendere lo
stimatore la fonte primaria.

---

## 2. Mappa del predictor attuale (cosa tocca T_marcia)

Il "modello T_marcia" statico è la stima di quanto resta fuori una squadra di
raccolta. È incapsulato in **una sola funzione**:

- **`core/skip_predictor.py::_calc_t_marcia_min(invio, istanza)`** — formula:
  ```
  T_marcia = 2×eta_marcia + (saturazione × T_L_max[livello, istanza]) × coef
  saturazione = min(1, load_squadra / CAP_NOMINALE[tipo, livello])
  ```
  Ritorna `None` se `livello`/`load_squadra` mancanti.

Dipendenze della formula:
- `config/predictor_t_l_max.json` → `T_L_max` base per livello × moltiplicatore
  per istanza (FAU_00=1.0, farm=1.3, FAU_09=1.5, FAU_10=1.4). Tarato a mano il
  04/05, mai ricalibrato.
- `core/skip_predictor.py::CAP_NOMINALE` → capacità nominale nodo (tipo,livello).
- `core/t_marcia_calibration.py::get_calibration_coef(istanza, livello)` → `coef`
  moltiplicativo closed-loop (proposta B 08/05), applicato solo al termine di
  raccolta. Persistenza `data/predictor_t_l_calibration.json`.

**Consumatori di `_calc_t_marcia_min`** (tutti tramite la stessa firma — un solo
punto da modificare):
1. `core/adaptive_scheduler.py::compute_slot_liberi_atteso` — **consumer LIVE**,
   ordina le istanze nel ciclo. È qui che vive già il confronto WU200ter.
2. `core/skip_predictor.py::predict_slot_liberi_l1` — predizione slot liberi L1.
3. `core/skip_predictor.py::_rule_squadre_fuori` — regola SKIP (dormiente: skip
   istanza vietato dalla regola di progetto 08/05, vedi
   `feedback_no_skip_istanza`).

---

## 3. Verifica dati (snapshot 12/07/2026, prod `C:\doomsday-engine-prod`)

`data/tempo_raccolta_dataset.jsonl`: **155 match** su ~29.5h (11/07 06:43 → 12/07 12:18).

**Copertura celle `(istanza, tipo, livello)`** — 24/40 celle con ≥3 campioni
(`MIN_CAMPIONI_CELLA`). Le più popolate: FAU_00·petrolio·7 (n=20, mediana 2h10m),
FAU_10·petrolio·7 (10, 2h53m), FAU_02·petrolio·6 (9, 2h45m).

**Fallback `(tipo, livello)` globale** — robusto sui 4 tipi dominanti:

| tipo,livello | n | mediana |
|---|---|---|
| petrolio, 6 | 54 | 2h43m |
| petrolio, 7 | 51 | 2h49m |
| segheria, 7 | 23 | 2h47m |
| campo, 7 | 22 | 2h48m |
| campo, 6 | 4 | 2h29m |
| acciaio, 6 | 1 | — (sotto soglia) |

**Per istanza (aggregato)** — FAU_00 nettamente più veloce:

| istanza | n | mediana | | istanza | n | mediana |
|---|---|---|---|---|---|---|
| FAU_00 | 27 | **2h09m** | | FAU_06 | 13 | 2h47m |
| FAU_10 | 19 | 2h52m | | FAU_04 | 12 | 2h42m |
| FAU_02 | 19 | 2h45m | | FAU_01 | 11 | 2h46m |
| FAU_08 | 18 | 2h49m | | FAU_09 | 9 | 2h55m |
| FAU_07 | 14 | 2h45m | | FAU_05 | 7 | 2h55m |
| | | | | FAU_03 | 6 | 2h42m |

**Calibrazione closed-loop** (`predictor_t_l_calibration.json`): confidence "alta",
319 sample, ma **5/21 coef attivi** (≠1.0), tutti marginali (0.95–0.975). Modulo
di fatto quasi inerte.

**eta_marcia** (16.965 invii reali): mediana **59s**, media 62s, max 220s. Il
termine viaggio della formula (`2×eta ≈ 2min`) è ~1% su una raccolta ~170min.

**Confronto statico vs empirico** — lo statico sottostima le istanze lente:
FAU_00 allineato (empirico ≈ statico, mult 1.0), ma FAU_02 petrolio L7 empirico
3h09m vs statico ≈ 2h44m (mult 1.3 troppo ottimista). È il valore centrale del
cutover.

---

## 4. Analisi eliminazioni — RIVISTA sui dati (vs memoria WU200ter)

La memoria elencava 4 candidati "a eliminazione". La verifica ne conferma uno,
ne **ridimensiona due** (fallback, non delete) e conferma di **rimandarne uno**.

| Componente | Memoria WU200ter | Decisione rivista (dati 12/07) |
|---|---|---|
| `core/t_marcia_calibration.py` | eliminare intero modulo | ✅ **ELIMINARE** — quasi inerte (5/21 coef attivi, marginali). La misura diretta rende superflua la correzione indiretta via proxy slot. Rimuovere dopo Fase B stabile. |
| `config/predictor_t_l_max.json` | eliminare (base manuale) | ⚠️ **DECLASSARE a fallback ultimo, NON eliminare** — celle sottili (acciaio L6 n=1, campo L6 n=4) e nuovi livelli/tipi futuri non avranno campioni: serve un fondo statico. |
| `_calc_t_marcia_min` (la formula) | sostituire con `stima_tempo_raccolta` | ⚠️ **TIERED, non sostituzione secca** — empirica primaria, formula statica come fallback per celle sotto soglia. Firma invariata → 3 consumer beneficiano senza modifiche. |
| `core/empirical_slot_predictor.py` + blend | candidato incerto | ⏸️ **RIMANDARE** — è un layer ortogonale (lookup slot liberi per bucket di gap, non tempo di marcia). Fuori dallo scope di questo cutover. |

**NON toccare** (problema diverso): `core/cycle_duration_predictor.py` (durata
tick bot), `core/istanza_metrics.py` (logger), `CAP_NOMINALE` (capacità nodo,
serve al fallback).

---

## 5. Design del cutover

### 5.1 Semantica — allineare le due misure

- `durata_s` (empirico) = `ts_raccolta − ts_invio` = **andata + raccolta pura**
  (il report è emesso a raccolta completata).
- `T_marcia` (statico) = `2×eta + raccolta_pura` = **andata + raccolta + ritorno**
  (tempo fino a slot libero, cioè rientro squadra).
- Equivalente empirico corretto: `T_marcia_emp = durata_s + eta_ritorno ≈ durata_s + eta`.

> ⚠️ Nota: il confronto osservativo WU200ter usa `2×eta + durata_s`, che
> **somma un eta di troppo** (double-count dell'andata già dentro `durata_s`).
> Con eta mediano 59s l'errore è ~1min su ~170min (irrilevante), ma va corretto
> a `durata_s + eta` in fase di cutover per coerenza. Data la magnitudine, la
> scelta è di fatto immateriale sulle decisioni.

### 5.2 Nuova `_calc_t_marcia_min` (tiered, flag-gated)

Firma invariata. Empirica primaria se flag ON e cella disponibile; altrimenti
formula statica esistente. Bonus robustezza: l'empirica **non richiede
`load_squadra`**, quindi copre anche i vecchi invii pre-WU116 dove lo statico
ritorna `None`.

```python
def _calc_t_marcia_min(invio: dict, istanza: str) -> Optional[float]:
    livello = int(invio.get("livello", -1))
    tipo    = invio.get("tipo", "")
    eta_min = int(invio.get("eta_marcia_s", 0) or 0) / 60.0
    if livello < 1:
        return None

    # --- PRIMARIO: misura empirica diretta (flag Fase B) ---
    if _tempo_raccolta_empirico_attivo():
        try:
            from shared.tempo_raccolta_estimator import stima_tempo_raccolta
            t_emp_s = stima_tempo_raccolta(istanza, tipo, livello)
        except Exception:
            t_emp_s = None
        if t_emp_s is not None:
            return t_emp_s / 60.0 + eta_min          # durata_s + eta_ritorno

    # --- FALLBACK: formula statica invariata ---
    load = int(invio.get("load_squadra", -1))
    if load <= 0:
        return None
    cap = CAP_NOMINALE.get((tipo, livello))
    if not cap or cap <= 0:
        return None
    raccolta_min = min(1.0, load / cap) * _get_t_l_max_min(istanza, livello)
    try:
        from core.t_marcia_calibration import get_calibration_coef
        raccolta_min *= get_calibration_coef(istanza, livello)
    except Exception:
        pass
    return 2 * eta_min + raccolta_min
```

Flag `globali.tempo_raccolta_empirico_enabled` (default `False`), stesso pattern
di `adaptive_scheduler_enabled` (`config/config_loader.py` GlobalConfig +
`global_config.json` + toggle `/ui/config/global`). Hot-reload al tick, nessun
riavvio necessario per attivarlo.

### 5.2.1 Ladder di fallback dentro `stima_tempo_raccolta` (WU202b, 12/07)

Decisione utente su come stimare quando la cella esatta è magra. La dimensione
**istanza** domina (~+46% fra istanze) sul **livello** (~+10% fra L6/L7); il
livello registrato è inoltre incerto (~5% target≠reale, errore accettato senza
correzione). Quindi:

```
1. (istanza, tipo, livello)                         se ≥3 campioni → mediana diretta
2. PROPORZIONE da un altro livello della stessa (istanza, tipo):
     T[livello] = mediana[ancora] × cap[livello] / cap[ancora]
   (tempo ∝ capacità nodo a rate squadra costante; ancora = livello con più
    campioni). Un solo livello misurato copre tutti i livelli dell'istanza.
3. None → stima statica
```

**Niente fallback cross-istanza** (rimosso il vecchio `(tipo,livello)` globale:
mescolava FAU_00 veloce con le farm lente — buttava via la dimensione forte per
tenere la debole). Capacità nominale canonica consolidata in
`shared/cap_nodi_dataset.CAP_NOMINALE` (confermata sui `quantita_base` reali del
report), importata sia dall'estimator sia da `core/skip_predictor` (una sola
fonte). Verifica prod: FAU_10 campo L6=2h29m → L7 via proporzione = 2h44m
(×1,10); celle senza ancora valida → None → statico.

### 5.3 Fasi (step-by-step, reversibile)

| Fase | Contenuto | Rollback |
|---|---|---|
| **A** ✅ fatta | WU200ter: confronto osservativo in `compute_slot_liberi_atteso`. | — |
| **B — swap flag-gated** ✅ implementata 12/07 (WU202) · **ATTIVATA 13/07** | `_calc_t_marcia_min` tiered + flag `tempo_raccolta_empirico_enabled` + fix `durata_s + eta` + cache mtime. Flag **ON in prod dal 13/07** (via PATCH `/api/adaptive-scheduler`, DYNAMIC+STATIC). Effettivo al riavvio bot (codice tiered). | Flag OFF = ritorno immediato allo statico. |
| **C — cleanup / "empirico standard"** 📋 pianificata (§5.3.2) | Dopo N giorni LIVE stabile: collassare il flag (empirico non più opzionale), rimuovere `t_marcia_calibration` + file + retention, rimuovere UI di transizione (toggle, card confronto/backtest). Declassare `predictor_t_l_max.json` a fallback ultimo. | Fallback statico resta; ripristino = git revert. |
| **D — futuro (non ora)** | Valutare scaling per load atipico (vedi rischi) e revisione blend `empirical_slot_predictor`. | — |

### 5.3.1 Fase B — implementata (WU202, 12/07)

File toccati: `core/skip_predictor.py` (`_calc_t_marcia_min` tiered +
`_read_tempo_raccolta_empirico_flag`/`_tempo_raccolta_empirico_attivo`),
`shared/tempo_raccolta_estimator.py` (cache mtime `_carica_dataset_output`),
`core/adaptive_scheduler.py` (fix `2×eta→eta` + flag in `get_status`),
`config/config_loader.py` + `config/global_config.json` (flag default OFF),
`dashboard/routers/api_adaptive_scheduler.py` (PATCH dual-write) +
`dashboard/templates/partials/adaptive_scheduler_card.html` (toggle UI).
Test: `tests/unit/test_calc_t_marcia_tiered.py` (6). Suite correlata 42/42.

**Verifica end-to-end su dati reali prod (flag ON, dataset live):**

| cella | statico | empirico | scarto | esito |
|---|---|---|---|---|
| FAU_00 petrolio L7 (n=20) | 127.0 min | 131.0 min | +3.2% | istanza allineata, correzione minima |
| FAU_02 petrolio L7 (n=5) | 164.5 min | 190.2 min | **+15.6%** | istanza lenta: statico sottostimava di ~25min |
| FAU_09 acciaio L6 (n=1 < soglia) | 173.0 min | 173.0 min | 0 | cella scarna → fallback statico identico ✓ |

Con flag OFF: risultato byte-identico allo statico su tutte le celle
(verificato nei test + baseline pytest 51 failure pre-esistenti invariate).

### 5.3.2 Fase C — piano dettagliato: empirico standard + rimozioni (13/07)

Direzione utente (13/07): «al tendere dovrà essere standard e non più a scelta
questo tipo di modalità, ed elimineremo sia visivamente che funzionalmente
alcuni elementi del predictor che non vengono più utilizzati».

**Prerequisito (gate):** eseguire Fase C SOLO dopo che l'empirico è
**effettivamente LIVE** (bot ripartito col codice tiered) e **stabile** per
qualche giorno — backtest finestra pulita che regge (empirico ≤ statico con n
che cresce) e zero regressioni sui cicli reali. Fino ad allora il toggle resta
l'**interruttore di sicurezza**. NON rimuovere il flag prima.

**🔴 Rimozioni funzionali (codice):**
1. `core/t_marcia_calibration.py` — intero modulo (closed-loop `coef`): con
   l'empirico primario, il `coef` moltiplica solo il ramo statico ormai raro;
   già quasi inerte (5/21 coef ≠ 1.0, marginali). Rimuovere la chiamata in
   `_calc_t_marcia_static`, il modulo, `data/predictor_t_l_calibration.json` e
   il suo target in `_predictor_retention_loop`. Eventuale display dashboard.
2. **Collasso del flag**: `_calc_t_marcia_min` diventa "empirico primario →
   fallback statico" **senza gate**. Rimuovere `tempo_raccolta_empirico_enabled`
   (`config_loader` dataclass+parse+whitelist, `global_config.json`,
   `_read_tempo_raccolta_empirico_flag`/`_tempo_raccolta_empirico_attivo`, il
   campo nel PATCH `api_adaptive_scheduler`, il toggle nella card).

**🔴 Rimozioni visive (UI di transizione):**
3. Toggle "tempo raccolta empirico" nella card adaptive scheduler. 🟡 **PENDING**
   — resta come interruttore di sicurezza finché il flag non viene collassato
   (punto 2). Descrizione aggiornata 13/07: "modalità standard in prod, flag
   rimosso in Fase C".
4. Card "confronto tempo raccolta" (empirico vs statico) in preview. ✅ **RIMOSSA
   13/07** — con l'empirico primario Δ→≈0, la card non ha più valore diagnostico.
   Il campo `confronto_tempo_raccolta` in `compute_slot_liberi_atteso` resta
   (leggero, per il CLI/monitoraggio); rimozione rimandata al collasso del flag.
5. Card "backtest statico vs empirico" + endpoint `/ui/partial/backtest-empirico`
   + job `_backtest_empirico_loop` (+ `data/predictions/backtest_empirico.json`).
   ✅ **RIMOSSI 13/07** — servivano a DECIDERE il cutover (deciso a n=150, +3.7%).
   **Il CLI `tools/predictor_backtest_empirico.py` è TENUTO** (rilancio manuale
   on-demand per monitoraggio continuo, nessun job periodico).

**🟢 Da NON rimuovere (rete di fallback):**
- `_calc_t_marcia_static` + `config/predictor_t_l_max.json` (**declassare** a
  fallback ultimo, commento esplicito) + `shared/cap_nodi_dataset.CAP_NOMINALE`
  — servono per celle scarne (acciaio L6, livelli/tipi nuovi).
- `core/empirical_slot_predictor.py` (blend, ortogonale), `core/cycle_duration_predictor.py`
  (durata tick), `core/istanza_metrics.py` (logger).

**Esecuzione:** step-by-step con validazione (come WU204), un commit isolato per
rimozione, `git revert` per rollback. Da pianificare in dettaglio al momento
dell'esecuzione (post-stabilizzazione).

### 5.4 Criterio di prontezza al go-live Fase B

Al 12/07: 24/40 celle ≥3 campioni + fallback `(tipo,livello)` solido sui 4 tipi
dominanti ⇒ **la grande maggioranza degli invii LIVE ha già una stima empirica
oggi**, con caduta pulita allo statico per acciaio/campo-L6 e celle nuove. Il
criterio è soddisfatto per lo shadow; per il LIVE pilota basta confermare 2-3
giorni di `confronto_tempo_raccolta` con `diff_min` stabile (no oscillazioni da
under-sampling).

### 5.4.1 Backtest quantitativo — decidere su un numero (WU202c, 13/07)

`tools/predictor_backtest_empirico.py` ricostruisce, su ogni arrivo storico
reale, gli slot liberi predetti da statico ed empirico e li confronta col
ground truth `attive_pre` (OCR). **Metrica di decisione = MAE sulla "finestra
pulita"** (arrivi ≥ `empirical_start`, senza look-ahead). Job 1×/die in
dashboard (`_backtest_empirico_loop` → `data/predictions/backtest_empirico.json`)
+ card `/ui/predictor-istanze` che mostra la finestra crescere. **Criterio
cutover: n≥150 e empirico stabilmente sotto lo statico.**

Evoluzione finestra pulita (sempre a favore dell'empirico, segnale coerente):
| data | n | MAE statico | MAE empirico | Δ |
|---|---|---|---|---|
| 13/07 mattina | 9-10 | 1.20 | 1.10 | +8% |
| 13/07 (n=139) | 139 | 1.101 | 1.072 | +2.6% |
| **13/07 (n=150)** | **150** | **1.087** | **1.047** | **+3.7%** ✅ |

**Criterio raggiunto** al n=150: empirico MAE 1.047 < statico 1.087 (+3.7%),
bias più bilanciato (−0.03 vs +0.09), e sui casi che cambiano davvero la
decisione (recent_flip n=14) empirico nettamente meglio (MAE 1.14 vs 1.57,
+27%). Impatto complessivo comunque **bounded** (~5% delle decisioni cambiano).
→ **Flag attivato in prod il 13/07** (Fase B ATTIVATA). Effettivo al riavvio bot.

---

## 6. Rischi e guardrail

- **Load atipico**: la mediana per cella assume load tipico dell'istanza (stabile,
  stessa composizione truppe). Un invio con squadra parziale sarebbe più veloce
  del previsto — lo statico lo cattura via `saturazione`, l'empirico no. Impatto
  atteso basso (load stabile), da monitorare; eventuale scaling `durata × load/load_tipico`
  è Fase D, non blocca il cutover.
- **Dataset piccolo / retention 15gg**: `RETENTION_GIORNI=15` tiene il dataset
  fresco ma piccolo. Sorvegliare che le celle non scendano sotto soglia dopo la
  potatura (il fallback assorbe, ma degrada l'accuratezza per-istanza).
- **FauMorfeus / raccolta_fast esclusi**: non producono evento "occupato" →
  nessuna stima empirica, sempre fallback statico. Atteso e corretto.
- **Zero regressione garantita**: con flag OFF il percorso è byte-identico
  all'attuale; con flag ON e cella assente, fallback identico all'attuale.

---

## 7. Checklist implementazione Fase B

- [x] `_tempo_raccolta_empirico_attivo()` + flag `tempo_raccolta_empirico_enabled`
      in `config_loader.py` (default False) + `global_config.json` + toggle UI.
- [x] `_calc_t_marcia_min` tiered (blocco §5.2), firma invariata.
- [x] Fix confronto WU200ter: `2×eta` → `eta` in `compute_slot_liberi_atteso`.
- [x] Cache mtime sul dataset di output (`_carica_dataset_output`) — riduce
      l'I/O ripetuto del confronto già live + della stima primaria.
- [x] Test: flag OFF ⇒ output identico allo statico; flag ON cella presente ⇒
      usa empirico; cella assente ⇒ fallback statico. (6 test + verifica prod)
- [ ] **(utente)** Sync dev→prod, attiva shadow, osserva 2-3 giorni, poi LIVE pilota.
