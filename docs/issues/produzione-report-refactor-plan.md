# Refactor produzione per-istanza → calcolo esatto dal Tab Report

> Planning WU204 (13/07/2026). Obiettivo: portare **tutti** i calcoli/report di
> produzione per-istanza sulla stessa fonte esatta — la resa reale dei nodi dal
> Tab Report (`report_raccolta_dataset.jsonl`) — eliminando la metrica castello
> (`produzione_storico` / `compute_from_storico`) esposta alle anomalie
> rifornimento/zaino. Continuazione di WU203 (che ha già convertito il pannello
> `/ui/report-raccolta`).

---

## 1. Perché

La metrica castello `produzione_qty = Δcastello − zaino_delta + rifornimento_inviato`
(`core/state.py`, calcolata in `shared/prod_unificata.compute_from_storico`)
somma i movimenti di riserva del deposito. Un rifornimento inviato o uno
svuotamento zaino la gonfia enormemente: caso reale FAU_00 = **209 M/h** per un
`rifornimento_inviato.petrolio = 999.000.000` (= cap di config `qta_petrolio`,
non l'importo reale) × peso 5.

Il report misura la **resa diretta dei nodi raccolti** (`quantita_totale`), quindi
è immune a rifornimento/zaino/OCR castello. Valore reale FAU_00: **1.71 M/h**.

---

## 2. Semantica (decisione confermata)

La produzione report-based = **resa della raccolta** (quantità raccolte dai nodi).
Esclude produzione passiva edifici, ricompense, ecc. — che la metrica castello
*provava* a includere (ma sporcata). Per questa farm la raccolta è >90% della
produzione (nodi 1.2–1.3M vs trickle passivo), quindi report ≈ produzione reale,
pulita. La sezione email "Produzione interna rifugio" diventa di fatto "resa
raccolta" — semanticamente più precisa. **Confermato dall'utente.**

---

## 3. Mappa consumatori

| # | Dove | Funzione | Fonte oggi | Azione |
|---|---|---|---|---|
| 1 | Dashboard `/ui` (pannelli + farm) | `stats_reader.get_produzione_istanze()` → `compute_from_storico` | 🔴 castello, no filtro | **migra** |
| 2 | Dashboard `/ui/report-raccolta` | `report_raccolta_reader.get_produzione_unificata()` | 🟢 report | ✅ fatto (WU203) → dedup su modulo condiviso |
| 3 | Daily report — "Produzione interna rifugio" (sez 2) | `daily_report._section_produzione_rifugio` | 🔴 castello + cap 30M/h | **migra** |
| 4 | Telegram `/produzione` | `tg_handlers_monitoring._build_produzione` → `compute_from_storico` | 🔴 castello, no filtro | **migra** |

### Fuori scope (metrica diversa)
- Daily report — "**Inviato al master**" (sez 3) `_section_produzione` legge
  `data/storico_farm.json` = **spedizioni rifornimento**, NON produzione. Il
  report non può misurarla. Resta invariata. (Ha lo stesso bug 999M — cap di
  config registrato come inviato — ma è un fix separato di `tasks/rifornimento`.)
- Metrica castello `produzione_storico`/`compute_from_storico`: **non rimossa**
  (usata anche da telemetria/altri trend); solo non più fonte della produzione
  per-istanza nei 4 punti sopra.

---

## 4. Architettura — funzione canonica condivisa

Per non duplicare la logica in dashboard (`dashboard/`) e core (`daily_report`,
`tg_handlers` sono in `core/`), la fonte di verità va in `shared/`:

```
shared/produzione_report.py
  produzione_per_istanza(giorno=None, window_h=24.0, root=None) -> dict
    # giorno="YYYY-MM-DD" (UTC): aggrega report con ts_raccolta in quel giorno (den=24h)
    # altrimenti: finestra rolling ultime window_h (den=window_h)
    # legge report_raccolta_dataset.jsonl, somma quantita_totale per (istanza, risorsa),
    #   mapping campo->pomodoro / segheria->legno, pesi {pomodoro:1,legno:1,acciaio:2,petrolio:5}
    # ritorna:
    #   { "per_istanza": {inst: {"risorse":{r:qta}, "qta_h":{r:qta/den},
    #                            "pom_eq_h":float, "n_report":int}},
    #     "farm": {"risorse":{r:qta}, "pom_eq_h":float},
    #     "den_h": float, "modalita": "giorno"|"rolling" }
    # master (FauMorfeus) INCLUSO nel dict; l'esclusione dagli aggregati è del chiamante.
```

Vincoli:
- Retention di `report_raccolta_dataset.jsonl`: deve coprire almeno la finestra
  (24h rolling / il giorno del daily report). Verificare in Step 1.
- FauMorfeus e istanze raccolta_fast: presenti nel report se leggono i messaggi
  (verificato: FauMorfeus compare con dati). Nessuna esclusione a monte.

---

## 5. Piano step-by-step (un consumatore per step, con validazione)

Ogni step: implementa → test → **validazione su dati prod reali** → commit + sync.
Nessun riavvio dashboard/bot fino a decisione utente (il flag non c'è: è un
cambio diretto di fonte, quindi l'effetto è al riavvio del servizio interessato).

| Step | Contenuto | Validazione |
|---|---|---|
| **1** | Creare `shared/produzione_report.py` (funzione canonica) + unit test. Rifattorizzare `get_produzione_unificata()` (WU203) per usarla — **dedup**, stessi numeri. | Pannello report-raccolta invariato (FAU_00=1.71); test verdi |
| **2** | `stats_reader.get_produzione_istanze()`: sostituire il campo `prod_unificata` con report-based (rolling 24h). | Pannelli `/ui` mostrano FAU_00 sano; altri campi invariati |
| **3** | `daily_report._section_produzione_rifugio` → report-based (modalità giorno). Aggiornare testo/HTML sezione. | Genera daily report di prova: FAU_00 sano, ranking coerente |
| **4** | `tg_handlers_monitoring._build_produzione` → report-based (rolling 24h). | Output `/produzione` sano |

### Rollback
Ogni step è un commit isolato → `git revert` del singolo step. La funzione
castello resta nel codice (non rimossa), quindi il ripristino è immediato.

---

## 6. Rischi

- **Semantica** (già confermata): i numeri di produzione nel daily report email
  cambiano (resa raccolta, non delta castello). Coerenti e più bassi/puliti.
- **Retention report**: se il dataset non copre il giorno richiesto, la sezione
  mostra 0 per quel giorno (finestra insufficiente) → verificare in Step 1 e, se
  serve, allungare la retention di `report_raccolta_dataset.jsonl`.
- **Copertura istanze**: istanze senza report nella finestra → 0 (onesto). Da
  monitorare che tutte producano report (fast/master inclusi).
