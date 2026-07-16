# Doomsday Engine V6 — Architettura di dettaglio (blueprint)

> Documento di riferimento costruito nello scambio Claude ⇄ Gemini (`shared_ai_exchange/`),
> **un tema alla volta, verificato riga per riga sul codice**. Ogni affermazione punta al
> file/funzione da cui è tratta. Le parti discorsive ("il perché") stanno nel canale di
> scambio; qui la parte densa e definitiva.

Indice temi:
1. **Predictor + Scheduler** ✅ (16/07/2026)
2. **Raccolta + blacklist** ✅ (16/07/2026)
3. **Emulatore / ADB** ✅ (16/07/2026)
4. **Risorse / truppe** ✅ (16/07/2026)

---

# Tema 1 — Predictor + Scheduler

## 1.0 Cosa decide, e cosa NON decide

Lo scheduler adattivo decide **solo l'ordine** in cui le istanze vengono processate nel
ciclo. **Non salta mai** un'istanza (regola vincolante di progetto, 08/05): riordino sì,
skip totale no. Architettura **sequenziale**: una istanza alla volta, il tempo del ciclo
è la somma dei tick, invariante all'ordine per *durata totale* ma non per *resa* (un
ordine migliore trova più slot liberi → più marce piazzate).

Sorgente: `core/adaptive_scheduler.py::ordina_istanze_adaptive`.

## 1.1 Il calcolo di `slot_liberi_atteso(t_offset)`

Funzione: `core/adaptive_scheduler.py::compute_slot_liberi_atteso(istanza, t_offset_min)`.
Risponde: *"quando arriverò a questa istanza fra `t_offset` minuti, quanti slot squadra
avrà liberi?"*.

### Flusso

```
1. history = load_metrics_history(istanza, last_n=10)        # da data/istanza_metrics.jsonl
2. last = history[-1]
   totali     = last.raccolta.totali          # slot squadra totali (X/Y)
   attive_now = last.raccolta.attive_post      # slot occupati all'ultima lettura
3. invii_record = ultimo record con raccolta.invii != []    # marce reali
4. per ogni invio in invii_record.raccolta.invii:
      t_marcia = _calc_t_marcia_min(invio, istanza)          # minuti (vedi §1.2)
5. per ogni marcia:
      t_residuo = max(0, t_marcia - (now - ts_invio_marcia)/60)   # ancoraggio per-marcia
6. rientri = |{ marce : t_residuo <= t_offset }|,  cap a attive_now
7. slot_liberi_atteso = max(0, totali - attive_now + rientri)
8. score = slot_liberi_atteso  → blend con lookup empirico (§1.4)
```

### Equazione temporale (rientro di una marcia)

Una marcia partita all'istante `ts_invio` con tempo-marcia stimato `T_marcia` è
**rientrata** al momento `now + t_offset` se e solo se:

```
T_marcia − (now − ts_invio)/60  ≤  t_offset          [minuti]
        └── residuo al tempo now ──┘
```

Il residuo è ancorato al **`ts_invio` REALE della singola marcia** (catturato in
`tasks/raccolta.py::_esegui_marcia` dopo la conferma "maschera chiusa"), **non** al `ts`
di fine-tick del record. Fix WU191 (05/07): l'ancoraggio a fine-tick sottostimava
l'elapsed delle marce partite a inizio di un tick lungo (la raccolta invia più squadre
nell'arco di minuti), gonfiando il residuo e sottocontando i rientri — bias verso la
sottostima confermato empiricamente (40% sottostima vs 32% sovrastima sui cicli LIVE).
Fallback all'`elapsed` uniforme del record solo se `ts_invio` manca (dati storici).

### `T_marcia` = andata + raccolta + ritorno

`T_marcia` NON è il solo viaggio: è **andata + tempo di raccolta sul nodo + ritorno**.
Concretamente (`_calc_t_marcia_min`, §1.2):

```
T_marcia[min] = stima_tempo_raccolta(istanza, tipo, livello)/60   +   eta_marcia_s/60
                └── durata reale invio→completamento (empirica) ──┘   └─ ritorno OCR ─┘
```

dove `stima_tempo_raccolta` (§1.3) è la mediana empirica **misurata** (viaggio di andata
+ permanenza sul nodo, da `report_raccolta`) e `eta_marcia_s` è il tempo di ritorno letto
via OCR sulla maschera d'invio. **Non esiste più un `T_raccolta` statico** separato: dopo
il cutover WU223 Fase C (15/07) il termine è interamente empirico.

### Finestre di campionamento e conflitti

- `load_metrics_history(last_n=10)`: gli ultimi 10 record dell'istanza; il record con
  `invii` reali più recente fornisce il modello per-marcia.
- Il **blend empirico** (§1.4) usa una finestra di **14 giorni** (`WINDOW_DAYS`,
  `core/empirical_slot_predictor.py`) — introdotta in WU191 perché prima non c'era limite
  temporale e si mescolavano regimi diversi (switch `raccolta_fast→full` del 09/05,
  crescita truppe/livelli).
- **Code/conflitti**: lo scheduler è greedy e non simula lo stato (§1.5, limite noto) —
  non gestisce esplicitamente conflitti fra istanze; ogni istanza è valutata sui propri
  slot. Il caso "seconda squadra su nodo riservato ma non ancora occupato" (che marcia e
  torna a vuoto) è gestito **fuori** dal predictor, da `RaccoltaChiusuraTask` a fine tick.

## 1.2 `_calc_t_marcia_min` — il modello per-marcia (post-Fase C, permanente)

`core/skip_predictor.py::_calc_t_marcia_min(invio, istanza)`:

```python
livello = int(invio["livello"]); tipo = invio["tipo"]
if livello < 1 or not tipo: return None            # invio degenere → "già rientrato"
eta_min = invio["eta_marcia_s"]/60
t_emp_s = stima_tempo_raccolta(istanza, tipo, livello)   # §1.3
if t_emp_s is not None: return t_emp_s/60 + eta_min       # empirico (permanente)
return _FALLBACK_RACCOLTA_MIN + eta_min                   # 168 min, ultima spiaggia
```

- Non richiede `load_squadra` → copre anche gli invii pre-WU116.
- `None` viene trattato dai 3 chiamanti come "marcia già rientrata" (conservativo).
- I 3 consumer condivisi: `compute_slot_liberi_atteso`, `predict_slot_liberi_l1`,
  `_rule_squadre_fuori` — beneficiano da un solo punto.

## 1.3 `stima_tempo_raccolta` — la scala di fallback delle mediane

`shared/tempo_raccolta_estimator.py::stima_tempo_raccolta(istanza, tipo, livello, min_campioni=3)`.
Dataset: `data/tempo_raccolta_dataset.jsonl` (riconciliazione invio↔completamento, §Tema 2
per la costruzione). Ritorna **secondi**, o `None`.

Scala di fallback (in ordine, prima che qualifica vince):

| # | Tier | Condizione | Valore |
|---|------|-----------|--------|
| 1 | **Cella diretta** | `(istanza,tipo,livello)` ha ≥3 campioni | mediana delle durate |
| 2 | **Proporzione fra livelli** (stessa istanza) | un ALTRO livello di `(istanza,tipo)` ha ≥3 campioni | riscalamento (sotto) |
| 3 | **Pool cross-istanza** (WU223) | `(tipo,livello)` dalle ordinarie **escl. FAU_00** ha ≥3 campioni | mediana del pool |
| 3b | **Proporzione cross-istanza** | un altro livello nel pool ordinarie ha ≥3 campioni | riscalamento sul pool |
| 4 | **Niente** | nessun dato per `(tipo,livello)` da nessuna istanza | `None` → costante 168 min |

### Formula di riscalamento (tier 2 e 3b)

Il tempo di raccolta è ~proporzionale alla **capacità nominale del nodo** a rate-squadra
costante. Quindi da un livello *àncora* misurato si stima il livello target:

```
T[livello_target] = mediana(durate_àncora) × cap_nominale(tipo, livello_target)
                                            ────────────────────────────────────
                                              cap_nominale(tipo, livello_àncora)
```

`cap_nominale` da `shared/cap_nodi_dataset.py` (tabella valori nominali per tipo×livello).
Scelta dell'àncora (`_proporzione_da_altro_livello`): **più campioni** vince, tie-break
**livello più vicino** → chiave di ordinamento `(n_campioni, -|liv_àncora − liv_target|)`.

**Esempio (la tua domanda: legno L7 da legno L6, stessa istanza)**: se `(FAU_x, segheria,
6)` ha ≥3 campioni con mediana 2.80h e non c'è dato diretto per L7, allora
`T[segheria,7] = 2.80h × cap(segheria,7)/cap(segheria,6)`. Con capacità nominali (es.)
L6=240k, L7=264k → `2.80h × 264/240 = 3.08h`. (`segheria` = nome nodo di "legno" nel
dataset; etichette in `report_raccolta_reader._TIPO_LABEL`.)

### Perché FAU_00 è esclusa dal pool (tier 3)

Le ordinarie hanno tempi omogenei (~2h44–2h53m); **FAU_00 è nettamente più veloce**
(~2h09m, l'istanza più sviluppata → coppie di raccoglitori più potenti). Inserirla nel
pool cross-istanza abbasserebbe la mediana di tutte le altre. Per i **suoi** buchi FAU_00
usa comunque il pool ordinarie (leggera sovrastima accettata: sue celle marginali). Il
master (FauMorfeus) è escluso a monte del dataset (`nodi_mappa.ISTANZE_ESCLUSE`) — vedi
§1.6.

## 1.4 Blend deterministico + empirico

`core/adaptive_scheduler.py::_blend_with_empirical`. Sopra il valore deterministico di
§1.1 si fonde una **lookup storica**: *"quando quest'istanza è stata lasciata ferma ~N min,
quanti slot liberi aveva DAVVERO?"* (bucket di gap, finestra 14 giorni,
`empirical_slot_predictor.lookup_slot_liberi`).

```
slot_liberi_atteso = round( α·det + (1−α)·mediana_empirica )
```

Peso α continuo in `n_samples` (`_blend_alpha`, WU168 — prima era a gradini):

```
α(n) = max(0.3, 1.0 − 0.7 · min(n,30)/30)
       α=1.0 a n=0 (solo deterministico) → α=0.3 a n≥30 (70% empirico)
```

Tie-breaker aggiuntivo `p_saturo_globale` (§1.5, proposta C): probabilità storica che
l'istanza sia satura, `None`→0.5 neutro.

## 1.5 Il greedy — ordinamento e il suo limite architetturale

`ordina_istanze_adaptive`: non una classifica statica, ma una **simulazione**:

```
t_offset = 0
finché restano istanze:
    score[i] = compute_slot_liberi_atteso(i, t_offset)  per ogni rimanente
    ordina: slot_atteso ↓, poi p_saturo ↑, poi anzianità_tick ↓
    scegli la prima; t_offset += durata_stimata(scelta)   # il tempo avanza
```

Questo spiega casi tipo FAU_02/FAU_05: al passo k FAU_02 può avere `sla=5` e FAU_05 `sla=4`
→ vince FAU_02; ma al passo k+1 il tempo è avanzato e anche FAU_05 arriva a `sla=5` → scelta
subito dopo. L'anzianità è **terzo** criterio, dopo slot e p_saturo.

### Limite noto (fonte del gate hardcoded del doppio giro, §1.6)

Il greedy **avanza il tempo ma NON lo stato simulato**: `compute_slot_liberi_atteso` legge
sempre l'**ultimo record su disco** (ciclo precedente). Quindi non sa valutare gli slot di
un'istanza che ha *già pianificato di visitare* in questo stesso ciclo. È per questo che il
2° passaggio di FAU_00 (§1.6) **non passa dal greedy** ma da un gate a fine ciclo, dove i
dati su disco sono di nuovo veri. Miglioria futura identificata (non implementata): dare al
greedy uno stato simulato per-istanza → il 2° passaggio diventerebbe un candidato ordinario.

### Gate di attivazione dello scheduler

`should_activate_scheduler`: flag `adaptive_scheduler_enabled` **E** ≥1 di 4 precondizioni
in OR — residuo giornaliero master ≤ soglia (default 50M), rifornimento OFF, ≥50% istanze
sature, >60 spedizioni oggi. `_predict_gap_minutes` (per la regola "squadre fuori")
usa il **p75** del cycle duration predictor (stima conservativa, fallback 120 min).

## 1.6 FAU_00 "doppio giro" — CORREZIONE DI UN EQUIVOCO

> **Attenzione, Gemini**: la tua domanda 3 parla di *"shadowing di FAU_00 che controlla e
> replica le marce o lo stato di FauMorfeus (master)"*. **Questo non esiste nel codice** ed
> è un equivoco su due termini. Lo correggo qui, verificato su
> `core/doppio_giro_shadow.py` + `main.py`.

**Cosa NON è**: FAU_00 non replica, controlla o rispecchia FauMorfeus. Non c'è nessuna
relazione di mirroring fra le due. FauMorfeus è il **master** (rifugio ricevente delle
risorse, **giocato manualmente**), escluso da telemetria/predictor/dataset
(`is_master_instance`, `nodi_mappa.ISTANZE_ESCLUSE`).

**Cosa È — il "doppio giro" (WU221)**: FAU_00 è l'unica istanza con raccolta nettamente
più veloce (~2h09m vs ~2h48m), quindi in un giro fisso **accumula slack** (slot liberi
mentre aspetta il giro dopo). Il doppio giro la **ri-schedula una 2ª volta nello stesso
ciclo**, in modalità **solo-raccolta**, per recuperare quello slack. È un secondo passaggio
di FAU_00 **su sé stessa** (non replica marce, stato o ricezione-risorse del master).

**Il legame col master è duplice ma limitato**, ed è qui il punto sottile:
- **posizionale** — il 2° passaggio è inserito *prima* del master (che è sempre ultimo);
- **di configurazione** — gira con `forza_solo_raccolta=True`, che imbocca lo **stesso
  identico** code path di `tipologia=="raccolta_only"` con cui è configurato FauMorfeus:
  `main.py` → `_solo_raccolta = (tipologia=="raccolta_only") or forza_solo_raccolta` →
  registra solo `RaccoltaTask`+`RaccoltaChiusuraTask`. Da qui il commento in
  `doppio_giro_shadow.py`: *"solo-raccolta (come FauMorfeus)"*, e la conferma in config
  (`runtime_overrides.json`: FauMorfeus `tipologia=raccolta_only, master=True`).

Ciò che il 2° giro **NON** condivide col master: le marce, lo stato, il ruolo di rifugio
ricevente — nessun mirroring. Condivide **solo la modalità di esecuzione** (solo-raccolta).

**Il termine "shadow"**: `doppio_giro_shadow.py` — "shadow" qui significa **osserva senza
eseguire** (Fase 0: `valuta_shadow` scrive `data/doppio_giro_shadow.jsonl` per il
cost/benefit), non "rispecchia". Con `doppio_giro_enabled=False` resta solo l'osservazione,
zero impatto; con `=True` diventa LIVE ed esegue davvero il 2° passaggio.

### Qualifica (quando il 2° passaggio è "OK")

`valuta_qualifica(CANDIDATO="FAU_00")` — qualifica sse **entrambe**:

```
elapsed ≥ SOGLIA_ELAPSED_MIN (=120 min)   # i raccoglitori del 1° passaggio rientrano a ~129m
    AND
slot_liberi_atteso ≥ SOGLIA_SLOT (=3)      # rilanciare per <3 slot non ripaga il boot (~10m)
```

`elapsed` e `slot_liberi_atteso` vengono da `compute_slot_liberi_atteso(FAU_00, 0)` (§1.1):
si riusa lo **stesso** modello, non una logica separata.

### Inserimento nel ciclo + gate

`main.py::_thread_istanza`: quando il ciclo sta per avviare il **master** e
`doppio_giro_live_attivo()`, se FAU_00 qualifica → esegue un 2° tick con
`forza_solo_raccolta=True` (registra solo `RaccoltaTask`+`RaccoltaChiusuraTask`). La
posizione "prima del master" è **progettuale (hardcoded), non calcolata** — conseguenza del
limite §1.5.

### Visibilità nella pianificazione (WU228/228b) e cooldown implicito

`ordina_istanze_adaptive(includi_doppio_giro=True)` inserisce una voce **virtuale**
`FAU_00 ↻²` prima del master **solo se** la finestra `t_master − t_avvio(FAU_00) ≥ 120min`
(altrimenti è aritmeticamente impossibile → non disegnata). La voce è **condizionale**, non
una predizione: la qualifica la decide il bot a fine ciclo. **"Cooldown" di fatto**: il 2°
passaggio riempie gli slot di FAU_00 → al ciclo successivo il greedy la scivola in coda →
la finestra si stringe → niente 2° giro. Il meccanismo si **alterna** da solo (un ciclo con
doppio giro, uno senza).

---

## Fonti (file · funzione)

- `core/adaptive_scheduler.py` — `compute_slot_liberi_atteso`, `ordina_istanze_adaptive`, `_blend_with_empirical`, `_blend_alpha`, `should_activate_scheduler`
- `core/skip_predictor.py` — `_calc_t_marcia_min`, `_predict_gap_minutes`, `_FALLBACK_RACCOLTA_MIN=168`
- `shared/tempo_raccolta_estimator.py` — `stima_tempo_raccolta`, `_proporzione_da_altro_livello`, `ISTANZA_VELOCE_ESCLUSA="FAU_00"`
- `shared/cap_nodi_dataset.py` — `cap_nominale`
- `core/empirical_slot_predictor.py` — `lookup_slot_liberi`, `WINDOW_DAYS=14`
- `core/doppio_giro_shadow.py` — `valuta_qualifica`, `SOGLIA_ELAPSED_MIN=120`, `SOGLIA_SLOT=3`, `CANDIDATO="FAU_00"`
- `main.py::_thread_istanza` — inserimento doppio giro + `forza_solo_raccolta`

---

# Tema 2 — Raccolta + Blacklist

> Verificato riga per riga su `tasks/raccolta.py` (classi `Blacklist`/`BlacklistFuori`,
> `_invia_squadra`, `_leggi_coord_nodo`, `_ocr_coord_box`, `_nodo_in_territorio`).

## 2.1 Due blacklist, ruoli distinti

| | **RAM** (`Blacklist`) | **Disco** (`BlacklistFuori`) |
|---|---|---|
| Scope | in-processo, per run | **globale**, condivisa tra tutte le istanze |
| Persistenza | volatile | `data/blacklist_fuori_globale.json` |
| Chiave | `"X_Y"` (coord OCR reali) | `"X_Y"` |
| Valore | `{ts, state, eta_s}` | `{ts, tipo}` |
| TTL | **sì**: RESERVED 45s / COMMITTED 120s | **no**: permanente (la mappa non cambia) |
| Scopo | coordinare più squadre nello stesso tick, evitare doppio invio sullo stesso nodo | ricordare i nodi **fuori territorio** una volta per tutte |

**RAM — stati e ciclo di vita** (`reserve`/`commit`/`rollback`, cleanup TTL su ogni
accesso via `_pulisci`, thread-safe):
- `reserve(chiave)` — **prima** del tap sul nodo: lo prenota (RESERVED, 45s) così una
  seconda squadra nello stesso tick non lo ritenta.
- `commit(chiave, eta_s)` — dopo un esito definitivo: marcia riuscita (con `eta_s`), **o**
  nodo di livello troppo basso (COMMITTED, 120s → non ritentato per la finestra TTL).
- `rollback(chiave)` — su fallimento/scarto: rilascia la prenotazione.

**Disco — permanente e globale**: `aggiungi(chiave, tipo)` scrive subito su file. Nessun
TTL perché un nodo fuori dal territorio alleanza resta fuori (mappa statica), e la
condivisione globale evita che 12 istanze riscoprano lo stesso nodo fuori. **Regola di
progetto vincolante**: un solo file globale, mai `blacklist_fuori_FAU_XX.json` per istanza.

> **Caveat robustezza (identificato 16/07, fix non ancora applicato)**: le 12 istanze
> girano **sequenzialmente in un solo processo** (`main.py:1519-1525`, `t.start(); t.join()`)
> e nessun altro processo scrive il file → **nessuna race cross-processo** (il
> `threading.Lock` basta). MA `_salva()` usa `write_text` **non atomico** (a differenza di
> altri saver del progetto che fanno tmp+`os.replace`): un crash/kill a metà scrittura può
> corrompere il file; e `_carica()` ritorna `{}` su qualunque errore di lettura, senza
> distinguere "file assente" da "file corrotto" → il primo `aggiungi()` successivo
> **sovrascriverebbe** azzerando la blacklist accumulata. Fix consigliato: scrittura
> atomica (tmp+`os.replace`) + `_carica` che su file presente-ma-illeggibile NON azzera
> (backup/rifiuto scrittura). **Non** serve `portalocker`/OS-lock (architettura sequenziale).

## 2.2 Il flusso per-nodo (`_invia_squadra`) — commit/rollback/espansione

Per ogni tipo, si itera `sequenza_livelli`; per ogni livello:

```
CERCA(lv) → _leggi_coord_nodo → chiave "X_Y"
  ├─ chiave ∈ BlacklistFuori(disco)?  → _reset_to_mappa → prova lv successivo   (skip, non tappa)
  ├─ chiave ∈ Blacklist(RAM)?         → retry CERCA stesso lv; ancora occupato → tipo_bloccato
  └─ altrimenti                        → reserve(chiave) + break (usa questo nodo)
se nessun lv ha dato un nodo utile → skip_neutro

tap nodo + gather
  ├─ _nodo_in_territorio == FUORI → BlacklistFuori.aggiungi(disco) + Blacklist.rollback(RAM)
  │                                  + _reset_to_mappa → skip_neutro
  ├─ livello nodo < MIN           → Blacklist.commit(RAM)  + _reset_to_mappa → tipo_bloccato
  └─ territorio IN & livello OK    → MARCIA → Blacklist.commit(chiave, eta_s) → ok=True
```

**Gli eventi che muovono le blacklist**:
- **Commit definitivo (RAM)**: marcia riuscita (`eta_s` reale) oppure livello basso (per
  non ritentare il nodo entro 120s).
- **Rollback (RAM)**: nodo fuori territorio (prima di scriverlo su disco), o qualunque
  scarto dopo `reserve` — la prenotazione va rilasciata.
- **Espansione permanente (disco)**: **solo** quando `_nodo_in_territorio` dà FUORI. È
  l'unico evento che scrive su `blacklist_fuori_globale.json`.

**Override WU50** (`RACCOLTA_FUORI_TERRITORIO_ABILITATA`, per-istanza): per rifugi piazzati
dove **tutti** i nodi sono fuori territorio — bypassa sia il check `_nodo_in_territorio`
(procede comunque) sia `BlacklistFuori.contiene` (legge nodi blacklisted). Default False.

**Nota raccolta_fast (WU198)**: il profilo veloce **salta entrambe** le blacklist (né
lookup né aggiornamento) — rischio accettato dall'utente 09/07 (il fuori-territorio è solo
un buff di resa +30%, non un rischio truppe: 25.9% hit-rate storico misurato).

## 2.3 Check territorio — `_nodo_in_territorio`

Pixel check (non OCR) sul popup nodo, ROI `_TERRITORIO_BUFF_ZONA=(250,340,420,370)`:
conta i pixel "verdi" del buff territorio +30%:

```
verde  =  g>140  AND  g>r·1.4  AND  g>b·1.3  AND  (g−r)>40
IN territorio  ⇔  #verdi ≥ _TERRITORIO_SOGLIA_PX (=20)
```

**Fail-safe True**: su qualunque errore (frame assente, eccezione) assume IN territorio →
non blackliste per errore un nodo buono.

## 2.4 OCR coordinate — `_leggi_coord_nodo` / `_ocr_coord_box`

**Lettura** (`_leggi_coord_nodo`): tap lente coord `(380,18)` → verifica popup via template
`pin_enter` su `ROI_ENTER` (retry 1× del tap se non visibile) → OCR **X e Y separati** da
`OCR_COORD_ZONA_X` / `OCR_COORD_ZONA_Y`.

**Preprocessing OCR** (`_ocr_coord_box`, tradotto da V5):
```
crop ROI → resize ×4 (INTER_CUBIC) → grayscale → threshold Otsu (BINARY+OTSU)
→ pytesseract psm 7, whitelist "0123456789XY:#." → regex \d{3,4} → primo match
```

**Recupero da letture corrotte** (in ordine):
1. Se `cx` **o** `cy` è None → attende 0.6s, **ri-screenshot**, ritenta solo la coord
   mancante.
2. Se resta solo `cy` (X illeggibile ma Y sì) → `cx = 690` (centro mappa, pattern V5) — la
   Y basta a rendere la chiave abbastanza distintiva.
3. Se entrambe None → `_leggi_coord_nodo` ritorna `None`, **ma il chiamante `_invia_squadra`
   NON invia la marcia** (correzione su segnalazione Gemini [seq 7], verificato
   `raccolta.py:1695-1701`): tratta `chiave==None` come *"nessun nodo disponibile a quel
   livello"* → `_reset_to_mappa` + `continue` al livello successivo; se nessun livello dà un
   nodo → `skip_neutro`. **Nessuna marcia alla cieca senza coordinate** — l'assenza di
   coord blocca il dispaccio su quel livello, non lo lascia procedere.

**Perché ×4 + Otsu + whitelist**: le coordinate sono 3-4 cifre piccole ad alto contrasto;
l'upscale cubico + binarizzazione Otsu massimizza la separazione cifra/sfondo, la whitelist
elimina i falsi caratteri (lettere/simboli) e la regex `\d{3,4}` scarta il rumore residuo
prendendo il primo gruppo numerico plausibile.

## Fonti (file · funzione)
- `tasks/raccolta.py` — `Blacklist` (RAM), `BlacklistFuori` (disco), `_invia_squadra`
  (flusso reserve/commit/rollback), `_nodo_in_territorio`, `_leggi_coord_nodo`,
  `_ocr_coord_box`, costanti `_TERRITORIO_BUFF_ZONA`/`_TERRITORIO_SOGLIA_PX`,
  `RACCOLTA_FUORI_TERRITORIO_ABILITATA`
- `data/blacklist_fuori_globale.json` — blacklist disco globale

---

# Tema 3 — Emulatore (MuMuPlayer) + ADB

> Verificato su `core/launcher.py` + `core/orchestrator.py`, **con analisi log prod**
> (93 boot, distribuzione tempi, frequenza cascade/timeout reali — Standard di verifica v1.1).

## 3.1 Sequenza di boot di un'istanza — `avvia_istanza`

```
0. avvia_player()                      # readiness MuMuPlayer (Win11, §3.2)
0.5 adb kill-server / start-server     # reset socket tra istanze sequenziali (fix F1b)
1. attesa istanza precedente spenta    # MuMuManager info, max 30s, poll 3s
2. MuMuManager control -v <indice> launch   (timeout 30s)
3. poll is_android_started ogni DELAY_POLL_S, max boot_timeout (adattivo per-istanza)
4. adb connect 127.0.0.1:<porta>       # RETRY ×3, sleep 5s tra tentativi
5. _avvia_gioco()                      # anti-background, RETRY ×3 (§3.3)
```

- **Timeout boot adattivo** (`AdaptiveTiming(nome).get("boot_android_s", timeout_adb_s)`):
  per-istanza, calibrato sui boot storici; `record("boot_android_s", boot_s)` a ogni
  successo. Base da config `timeout_adb_s` (mitigata 300→480s in WU201/209 per rallentamenti
  host sistemici).
- **Reset socket ADB (fix F1b)**: `kill-server`+`start-server` **prima** di ogni istanza —
  su macchina lenta (HDD, 11 istanze seriali) il frame-grabber accumula socket rotti →
  `screenshot()` ritorna None persistente. Il reset azzera lo stato senza toccare MuMu.

**Log/monitoring (prod)**: boot `is_android_started` **n=93, min 21s, p50 32s, p90 37s,
max 54s** — 0 boot oltre 200s nel periodo. `TIMEOUT: Android non started` = **0**,
`adb connect fallito dopo 3` = **0** → la sequenza di boot è attualmente robusta.

## 3.2 Readiness MuMuPlayer su Windows 11 — `avvia_player`

Il problema Win11: `MuMuNxMain.exe` può essere **in tasklist ma non ancora inizializzato**
→ `MuMuManager launch` fallisce **silenziosamente**. Quindi "processo in lista" ≠ "pronto".

```
_is_player_running()   →  tasklist /FI "IMAGENAME eq MuMuNxMain.exe"   (processo c'è?)
readiness reale        →  MuMuManager version  (returncode==0 = manager risponde = pronto)
```

Se il processo non c'è → lo avvia (Popen, reference tenuta per evitare ResourceWarning GC
su Python 3.14+) e poll ogni `_PLAYER_POLL_S=3s` fino a `timeout_player_s`. Su Win10 non
necessario ma innocuo.

> **Caveat asimmetria cold-boot [seq 11] Gemini** (verificato `launcher.py:412-421`): il ramo
> **già-in-esecuzione** (355-386) fa il check responsivo `MuMuManager version` (e attende
> fino a 30s la readiness); il ramo **cold-boot** (Popen + polling) ritorna `True` appena
> `MuMuNxMain.exe` compare in tasklist, **senza** il check `version`. In teoria il successivo
> `MuMuManager launch` potrebbe partire su manager non ancora pronto. **Log/monitoring (prod)**:
> cold-boot preso **8 volte su 93 boot** (~8.6%), tutti `avviato OK`; ma `MuMuManager launch
> errore`=**0** e `TIMEOUT Android non started`=**0** → la lacuna **non ha mai morso** (i delay
> a valle in `avvia_istanza` — reset socket, verifica-spenta — danno tempo al manager). Rischio
> **latente**, non incidente. Fix consigliato (coerenza/difesa in profondità, bassa priorità):
> aggiungere il check `MuMuManager version` anche al polling cold-boot prima di `return True`.

## 3.3 Avvio gioco anti-background — `_avvia_gioco`

Problema osservato in prod: `am start` accetta l'intent ma il gioco spesso parte **in
background** (schermo resta su HOME Android), e `ps | grep pkg` dà match anche se l'UI non
è visibile. Strategia (max 3 tentativi):

```
1. am start -n GAME_ACTIVITY
2. sleep 3s
3. monkey -p pkg -c LAUNCHER 1     # SEMPRE (idempotente): porta l'UI al top come tap icona
4. sleep 5s
5. _gioco_in_foreground()  via  dumpsys window | grep mCurrentFocus(pkg)   # foreground REALE
   → sì: OK ; no: retry (diagnosi: processo vivo-ma-background vs non trovato)
```

> **Correzione [seq 11] Gemini** (verificato `launcher.py:225-247`): il check foreground usa
> `dumpsys **window**` cercando `mCurrentFocus` col pacchetto gioco — **non** `dumpsys activity
> top` (deprecato dal FIX 26/04, Issue #60: matchava il pkg anche come task background →
> falso positivo dopo kill+restart, ~43s persi/istanza). C'è UNA sola window con focus utente
> per volta = quella davvero visibile. Il docstring di `_avvia_gioco` cita ancora il vecchio
> comando: è **stale** (la funzione reale è aggiornata).

**Log/monitoring (prod)**: `monkey launcher` ×**115**, `processo gioco vivo ma NON in
foreground` ×**22** (~19% dei tentativi) → il retry anti-background è un recupero **reale e
ricorrente**, non teorico. `no Live Chat` ×92 = uscita anticipata dall'attesa splash
(percorso normale quando il gioco è già oltre lo splash).

## 3.4 Robustezza ADB e cascade

- **adb connect** (`avvia_istanza` step 4): RETRY ×3 con sleep 5s. Fix 29/04: un singolo
  tentativo in timeout faceva proseguire `am start` su socket morto → 3 `am start` falliti →
  abort fasullo. Il retry chiude quel buco.
- **ADB cascade** (`orchestrator.py:312`): un task che durante un `vai_in_home()` interno
  trova ADB morto solleva **`ADBUnhealthyError`** → l'orchestrator **aborta il tick**, setta
  `ctx.adb_unhealthy=True`, emette telemetria `outcome=abort` + anomalia `ADB_UNHEALTHY`, e
  chiama `report_cascade_adb` → **alert email se ≥3 cascade in 1h** (WU137). A fine tick
  `main.py` marca l'esito `"cascade"` (WU-fix: prima era hardcoded `"ok"`, le cascade
  sparivano dal report storico) e può escalare a critical su N cicli consecutivi.

**Log/monitoring (prod)**: `ADB UNHEALTHY` = **0** nel periodo corrente, `TIMEOUT schermata
UNKNOWN` = **1** (evento WU201, rallentamento host sistemico, raro). → regime ADB
attualmente stabile.

## 3.5 Sonde future (se degradazione) — proposta

Coerente con lo Standard di verifica: se il regime peggiora, inserire sonde ad-hoc
osservative (pattern WU230) per **tempo di riaggancio ADB** dopo una cascade e **tempo di
boot per-istanza** oltre soglia, per quantificare prima di intervenire. Non necessarie ora
(metriche verdi), da valutare se `ADB UNHEALTHY`/timeout tornano a salire.

## Fonti (file · funzione)
- `core/launcher.py` — `avvia_istanza`, `avvia_player`, `_avvia_gioco`,
  `_gioco_in_foreground`/`_gioco_process_vivo`, `_is_player_running`, `AdaptiveTiming`,
  costanti `_PLAYER_PROCESS_NAME`/`DELAY_POLL_S`/`GAME_ACTIVITY`
- `core/orchestrator.py:312` — `ADBUnhealthyError` → abort tick + reset + `report_cascade_adb`
- `main.py` — esito `"cascade"` per-tick, escalation cicli consecutivi

---

# Tema 4 — Risorse / Truppe

> Verificato su `shared/ocr_helpers.py` (`leggi_capacita_nodo`, `leggi_load_squadra`),
> `tasks/raccolta.py` (hook dataset), `tasks/truppe.py`, **con analisi dati prod**
> (`cap_nodi_dataset.jsonl`, 19.997 campioni cap+load).

## 4.1 OCR capacità residua nodo — `leggi_capacita_nodo`

Legge il valore "Quantity" dal popup gather (quanto il nodo ha ancora).
- **ROI** `_ZONA_CAPACITA_NODO = (270,280,420,320)` (150×40 px, popup gather).
- **Cascade** (2 tentativi): raw RGB → fallback binv `threshold(gray, 150, BINARY)`.
  PSM 6, whitelist `0123456789,`, parse int con virgole. Ritorna intero o **-1**.

## 4.2 OCR carico squadra ("Load") — `leggi_load_squadra`

Legge il "Load" dalla maschera invio (sopra il bottone MARCH) = quanto la squadra
raccoglierà.
- **ROI** `_ZONA_LOAD_SQUADRA = (610,420,780,455)` (170×35 px).
- **Cascade**: raw RGB → binv `threshold(gray,150)`. **binv 200 è escluso di proposito**:
  distorce le cifre piccole (`5`→`9`).
- **Estrazione robusta**: prende il **primo** gruppo digit/virgola
  (`\d{1,3}(?:,\d{3})+ | \d{1,7}`) — la binv 150 a volte include rumore sotto la riga (il
  timer ETA); il "primo gruppo" lo scarta. Ritorna intero o **-1**.

**Relazione**: `load = min(capacità_squadra, capacità_residua_nodo)`. Confrontando i due OCR
si misura la **saturazione**: `load < cap` ⇒ squadra **underprovisioned** (poche truppe) →
il nodo non viene chiuso al 100% e non rigenererà al massimo.

## 4.3 Underprovisioning — misurato, non gestito reattivamente

Punto chiave (verificato): il bot **NON** ha una coda reattiva né un gate "invia solo se
truppe sufficienti". La marcia parte **con le truppe che ci sono** (il `load` riflette
quello). L'underprovisioning è **osservato**, non contrastato al momento:
- **Registrazione** (`tasks/raccolta.py:1874`): `registra_cap_sample(cap, load, ...)` →
  `data/cap_nodi_dataset.jsonl`. Alimenta la sezione "Copertura Squadre" del daily report.
- **Reintegro**: **open-loop**, via `TruppeTask` schedulato (§4.4) che tiene le caserme in
  addestramento — **non** innescato dal rilevamento di underprovisioning.

**Dati prod** (`cap_nodi_dataset.jsonl`, 19.997 campioni): underprovisioned (`load<98%cap`)
= **746 = 3.7%**; ratio `load/cap` **p10=p50=p90=1.00** → le squadre sono **quasi sempre
piene** (portano ≥ capacità nodo). Concentrazione per tipo: **campo 7%, segheria 6%**,
acciaio 3%, petrolio 1% — l'underprovisioning morde i tipi a truppa più consumata, ma resta
un fenomeno di coda, non sistemico. → l'approccio open-loop è **empiricamente adeguato** al
regime attuale.

> **Rottura per istanza** (verifica incrociata indipendente Gemini `[seq 18]`, confermata da
> Claude con ricalcolo proprio sullo stesso dataset — stessi tassi, ±0.01pp): il fenomeno
> **non è uniforme fra istanze**. `FAU_00` ha un tasso **quasi nullo (0.31%)**, contro **7.20%
> FAU_10** e **6.74% FAU_09** (le più colpite). Coerente con quanto osservato altrove nel
> blueprint (§1.3): FAU_00 è l'istanza più sviluppata — le sue truppe superano stabilmente la
> capacità dei nodi, mentre le ordinarie con caserme meno progredite sentono la coda. Non
> cambia la conclusione (open-loop adeguato al regime attuale), ma localizza dove un
> intervento mirato (se mai servisse) avrebbe più leva: FAU_10/FAU_09, non la farm intera.

## 4.4 `TruppeTask` — reintegro caserme (schedulato)

Addestramento automatico delle **4 caserme** (Infantry / Rider / Ranged / Engine).
- **Schema config (WU132, 06/05)**: 4 flag **indipendenti** per caserma
  (`_TIPI_VALIDI = {infantry, rider, ranged, engine}`) + override per-istanza. Niente più
  `tipo_solo`/`livello`/`count_min`.
- **Flusso** (per caserma abilitata): tap `(30,247)` naviga + seleziona la prossima caserma
  libera → verifica titolo OCR → … → tap `(794,471)` TRAIN (giallo) → conferma. Il pannello
  porta automaticamente alla prossima caserma libera; `X/4` = caserme in addestramento.
- **Guard** `should_run`: rispetta la schedulazione + i flag per-caserma.
- **Nota WU135 (06/05)**: rimosso lo scorporo `prod_ora` basato su OCR del consumo truppe in
  addestramento (fragile: perdeva le cifre iniziali, i valori cumulati amplificavano
  l'errore). Riattivabile solo dopo refactor OCR completo.
- **Stato attuale (16/07): DISABILITATO deliberatamente**, non un gap operativo —
  `globali.truppe=false` su tutte e 12 le istanze (dev e prod). **Chiarito dall'utente**: le
  truppe accumulate coprono già tutte le tipologie di nodo necessarie, l'addestramento
  continuo non serve più al regime attuale. Coerente con l'underprovisioning misurato al
  3.7% (§4.3) — la scorta esistente basta. Riattivabile in futuro se la copertura degrada
  (nuovi livelli nodo, crescita farm). Un piccolo difetto di efficienza individuato nello
  scambio con Gemini (`_checkbox_fast_training_on` ricattura uno screenshot già disponibile
  dal chiamante, `tasks/truppe.py:253` vs `:314`) resta **corretto da segnalare ma senza
  impatto pratico** finché il task resta spento — non richiede intervento ora.

## Fonti (file · funzione)
- `shared/ocr_helpers.py` — `leggi_capacita_nodo` (`_ZONA_CAPACITA_NODO`), `leggi_load_squadra`
  (`_ZONA_LOAD_SQUADRA`, `_parse_first_int_with_commas`, `_LOAD_RE`)
- `tasks/raccolta.py:1858,1874` — lettura cap + hook `registra_cap_sample`
- `shared/cap_nodi_dataset.py` — `registra_cap_sample` → `data/cap_nodi_dataset.jsonl`
- `tasks/truppe.py` — `TruppeTask` (4 caserme, `_TIPI_VALIDI`, flusso tap TRAIN)

---

*Blueprint completo — 4/4 temi (16/07/2026). Costruito nello scambio Claude ⇄ Gemini con
Standard di verifica v1.1 (codice + log + monitoraggio).*
