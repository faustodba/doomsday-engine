# Radar Census — Metodologia operativa

> Documento di workflow operativo per `radar_tool` + `RadarCensusTask`.
> Il README.md adiacente descrive **come funzionano** i singoli script;
> questo file descrive **quando e perché** usarli.

---

## 1. Architettura a due tier

Il sistema di catalogazione icone radar lavora su due livelli **complementari**:

### Tier 1 — Pipeline automatica (in produzione)

Eseguita dal bot ad ogni esecuzione di `RadarTask`. **Non richiede intervento
manuale.**

```
RadarTask (priority 90, intervallo 12h)
  │
  ├── tap icona Radar Station + apri mappa radar
  ├── loop pallini (tap pin notifiche)
  └── se RADAR_CENSUS_ABILITATO=True
      │
      └── RadarCensusTask
          │
          ├── load_templates(radar_tool/templates/)        ← 47 PNG
          ├── detect(map_img, templates, threshold=0.65)   ← TM_CCOEFF_NORMED + NMS
          ├── classifier RF.predict(crop)                  ← classifier.pkl
          ├── _catalogo_finale()                           ← RF + heuristic fallback
          └── salva radar_archive/census/<ts>_<istanza>/
              ├── map_full.png                             ← screenshot raw
              ├── map_annotated.png                        ← bbox colorati
              ├── census.json                              ← record con cx/cy/categoria
              └── crops/                                   ← 64×64 per ogni icona
```

**Output utile per task derivati**: `census.json` ha per ogni icona
`(cx, cy, categoria, categoria_conf, ready)`. Task downstream (caccia
mostri, raccolta auto, eliminazione skull) leggono questo JSON e tappano
le coordinate per categoria.

**Logica `_catalogo_finale()`** (in `tasks/radar_census.py`):
1. Se RF predice una `OFFICIAL_LABELS` con `rf_conf >= RF_READY_MIN (0.70)` → primario RF
2. Altrimenti se nome template matcha l'heuristic con `conf_tmpl >= TMPL_READY_MIN (0.80)` → fallback heuristic
3. Altrimenti → categoria=`sconosciuto`, ready=False

**Stato attuale del classifier RF (28/04/2026)**: dataset training V5 limitato
(~28 etichette), modello underfitted, conf 0.24-0.35 su tutto. Quasi sempre
viene usato il fallback heuristic. **Questo è OK per ora** — la heuristic via
parsing nome template (`pin_skull → "skull"`, `pin_camion → "camion"`)
copre ~75% delle icone con `ready=True`.

### Tier 2 — Pipeline manuale (miglioramento offline)

GUI scripts in `radar_tool/` per estendere o migliorare l'output del tier 1.
Eseguita **on-demand** quando emergono lacune.

```
1. template_builder.py   ← aggiungi/rivedi template (GUI click+drag)
2. scan.py               ← rileva pin con nuovi template + genera crops
3. labeler.py            ← etichetta crops (GUI tasti rapidi 1-9)
4. train.py              ← riaddestra Random Forest
```

Output finali aggiornati che il bot in produzione poi riusa:
- `radar_tool/templates/*.png` (sostituiti/aggiunti)
- `radar_tool/dataset/classifier.pkl` (riaddestrato)

---

## 2. Quando usare cosa — decision tree

Quando il census produce risultati subottimali, scegli l'intervento in base
al sintomo:

| Sintomo | Causa | Soluzione | Effort |
|---------|-------|-----------|--------|
| Icona mai rilevata dal detector (assente da `census.json`) | Template inesistente per quel pin | **`template_builder.py`** — aggiungi template | ~5-10 min/template |
| Icona rilevata MA `categoria=sconosciuto` (nome template noto ma heuristic non lo gestisce) | Manca regola in `_categoria_da_template()` | **Fix codice** (5 righe in `tasks/radar_census.py`) | ~5 min |
| `categoria_conf` < 0.80 frequente | conf_tmpl basso = template non rappresentativo | **`template_builder.py`** — rivedi template (immagine più "pulita") | ~10 min |
| RF predizioni contraddittorie / sempre stessa label | Modello underfitted o training limitato | **`labeler.py` + `train.py`** — accumula >50 crops labelati e riaddestra | ~30-60 min |
| Detector rileva pin spurious (false positive) | THRESHOLD troppo basso (0.65) o template generico | Aumenta `RADAR_TOOL_THRESHOLD` o rivedi template | ~5 min |

### Regola pratica

> **Heuristic > RF finché RF è underfitted.** La heuristic via nome template
> è deterministica, veloce e funziona perfettamente per i casi conosciuti.
> Re-training RF è investment grande con ROI marginale finché copre solo il
> 25% di "sconosciuto" residuo.

Priorità interventi:
1. **Fix codice heuristic** quando `pin_<nome>` esiste ma non è classificato
2. **Aggiunta template** quando emergono pin nuovi mai visti
3. **Re-training RF** solo dopo aver accumulato ≥50 crops labelati di buona qualità

---

## 3. Procedura — Aggiunta template (Tier 2 — `template_builder.py`)

Quando vedi nel `map_full.png` un pin che il detector NON ha rilevato:

```bash
# 1. Identifica uno screenshot mappa radar che contiene il pin nuovo
#    (es. radar_archive/census/<ts>_<istanza>/map_full.png)

# 2. Lancia GUI
cd C:\doomsday-engine\radar_tool
python template_builder.py C:\doomsday-engine-prod\radar_archive\census\<ts>_<istanza>\map_full.png

# 3. Click + drag sul pin → preview real-time
# 4. Inserisci nome convenzione: pin_<COLORE>_<TIPO> oppure pin_<TIPO>
#    Esempi: pin_bot, pin_skull_3, pin_viola_skull
# 5. Salva → file PNG appare in radar_tool/templates/
# 6. Click "Test detection" per validare match score sulla mappa

# 7. Se OK, sync templates V6 → V6 prod (se editing in dev)
cp radar_tool/templates/*.png C:/doomsday-engine-prod/radar_tool/templates/
```

Convention naming: il `_categoria_da_template()` heuristic parsa il nome
cercando keyword (skull/sold/ped/camion/auto/para/card/bott/fiam/num/avatar).
**Se il nuovo pin non matcha nessuna keyword esistente, aggiungi anche la
regola in `tasks/radar_census.py`** (vedi sezione 4).

---

## 4. Procedura — Fix heuristic (5 righe Python)

Quando un pin è rilevato ma cataloga `sconosciuto`:

1. Apri `tasks/radar_census.py`
2. Vai a `_categoria_da_template(template_name, tipo)` (~riga 131)
3. Aggiungi regola PRIMA del `return "sconosciuto"`:

```python
if "bot" in s:                                       return "soldati"
```

4. Sync dev → prod e push commit
5. Effetto immediato al prossimo radar census (no restart bot)

**Esempio reale** (caso `pin_bot` su FAU_10 ciclo 2):
- Prima del fix: `categoria=sconosciuto`, `ready=False`
- Dopo fix `if "bot" in s: return "soldati"`: `categoria=soldati`, `ready=True`
- Recupero: 2/8 icone passate da unusable a usable

---

## 5. Procedura — Labeling + Retraining RF (Tier 2 — `labeler.py` + `train.py`)

Eseguire **solo** quando:
- Heuristic copre già tutto il copribile
- Si vogliono catturare distinzioni che il nome template non esprime
  (es. `pin_camion` rappresenta sia "camion verde mostro" che "camion oro
  raccolta" → RF distingue, heuristic no)

```bash
cd C:\doomsday-engine\radar_tool

# 1. Genera detections fresche su uno screenshot recente
python scan.py C:\doomsday-engine-prod\radar_archive\census\<ts>_<istanza>\map_full.png --debug
# Output: detections.json + dataset/crops/crop_NNN_tipo.png

# 2. GUI labeling
python labeler.py detections.json C:\doomsday-engine-prod\radar_archive\census\<ts>_<istanza>\map_full.png
# Tasti rapidi: 1-9 per label, 0=sconosciuto, D=scarta, Invio=conferma
# Predizione RF in tempo reale (dopo primo training)
# Bottone "Ri-addestra RF" senza uscire dalla GUI

# 3. Training batch (se non già lanciato dalla GUI)
python train.py
# Output: dataset/classifier.pkl

# 4. Test smoke
python radar_tool/_smoke_test.py
# Verifica RF caricato + trained=True + predizioni sensate

# 5. Sync dev → prod
cp radar_tool/dataset/classifier.pkl C:/doomsday-engine-prod/radar_tool/dataset/

# 6. Effetto immediato al prossimo radar census (no restart bot)
```

Label disponibili attuali (`OFFICIAL_LABELS` in `radar_census.py`):
- pedone, auto, camion, skull
- avatar, numero, card, paracadute
- fiamma, bottiglia, soldati, sconosciuto

`ACTION_LABELS` (sottoinsieme che dà `ready=True` automaticamente quando
classificato): tutti tranne `sconosciuto`.

---

## 6. Path importanti

| Path | Contenuto | Tier |
|------|-----------|------|
| `radar_tool/templates/*.png` | 47 PNG template per detector | 1 (input) |
| `radar_tool/dataset/classifier.pkl` | Random Forest pickled | 1 (input) |
| `radar_tool/dataset/labels.json` | Etichette training (~28 V5) | 2 (input training) |
| `radar_tool/dataset/crops/` | Crops 64×64 etichettati | 2 (input training) |
| `radar_tool/_smoke_test.py` | Test offline dopo modifiche templates/RF | 1+2 (validazione) |
| `radar_archive/census/<ts>_<istanza>/` | Output run-time del bot | 1 (output) |
| `radar_archive/census/<ts>_<istanza>/crops/` | Crops generati ad ogni census (potenziali sample per re-training) | 2 (input futuro) |

---

## 7. Quando NON intervenire

- ❌ **Non re-addestrare RF** se la heuristic copre >70% delle icone con
  `ready=True`. Investment alto, gain marginale.
- ❌ **Non aggiungere template duplicati** — se un pin è già rilevato (anche
  da template diverso) il NMS in `detector.py` filtra automaticamente. Aggiungi
  solo se il pin non viene MAI rilevato.
- ❌ **Non modificare `THRESHOLD = 0.65`** in `detector.py` senza A/B test su
  >100 icone. Soglia troppo alta → miss; troppo bassa → false positive.
- ❌ **Non committare crops di test** in `radar_tool/dataset/crops/` — sono
  troppi e sensibili al gitignore (`*.png` → solo `templates/` tracciate).

---

## 8. Versioning del modello

`classifier.pkl` non è versionato in git (è binario, escluso da `.gitignore`).
Quando lo riaddestri:

1. Backup precedente: `cp dataset/classifier.pkl dataset/classifier.bak.pkl`
2. Esegui `train.py`
3. Smoke test: `python _smoke_test.py` su sample noto
4. Se OK, sync dev → prod
5. Se fail, ripristino: `cp dataset/classifier.bak.pkl dataset/classifier.pkl`

Track dei training nel `labels.json` (timestamp implicito in `crop_file`).

---

## 9. FAQ

**Q: Devo riavviare il bot dopo aver aggiornato `templates/` o `classifier.pkl`?**
A: No. `RadarCensusTask` ricarica entrambi all'inizio di ogni `run()`.
Effetto immediato dal prossimo census.

**Q: I crops del census in `radar_archive/` possono essere usati per training?**
A: Sì, sono già nel formato 64×64 corretto. Copiali in `dataset/crops/` e
labelati con `labeler.py` su un wrapper che li usi come input.

**Q: Cosa succede se aggiungo un template senza aggiornare l'heuristic?**
A: Il detector lo userà per match. La catalogazione finale dipenderà da:
RF predict (se conosce la label) → fallback heuristic (se nome contiene
keyword nota) → `sconosciuto`. Se nuovo template ha nome con keyword non
nota, l'icona sarà `ready=False`. Risolvibile aggiungendo regola heuristic.

**Q: Per quanto tempo va mantenuto `radar_archive/census/`?**
A: Nessuna retention automatica al momento. Cresce ad ogni census (~2MB per
istanza × 12 istanze × 1/12h = ~50MB/giorno). Cleanup manuale dopo training
batch o policy retention da definire (proposta: 30 giorni).
