# Allocazione raccolta per-istanza — planning (WU205)

> Planning 13/07/2026. Rendere l'allocazione raccolta (proporzioni per tipo di
> nodo) configurabile **per singola istanza**, oggi governata da un unico target
> globale. UI scelta: **Variante A — matrice editabile** (istanze × 4 risorse).

---

## 1. Semantica (confermata utente)

Stessa identica semantica di oggi, solo con target per-istanza:
- L'algoritmo `tasks/raccolta._calcola_sequenza_allocation(slot_liberi,
  deposito, ratio_target)` **non cambia**: prende già `ratio_target` come
  parametro. Weighted-deficit: assegna i raccoglitori ai tipi più sotto il
  loro target, adattandosi al deposito dell'istanza.
- Il target resta un **bias soft** (non quota rigida): se il deposito è
  sbilanciato, l'algoritmo corregge come ora.
- **Fallback**: istanza senza allocazione propria → usa il globale
  (`raccolta.allocazione`, oggi 35/35/20/10). Retrocompatibile.

Oggi: `ctx.config.ALLOCAZIONE_*` = `gcfg.allocazione_*` (globale) per tutte.
Il pattern per-istanza esiste già (`_ovr(key, fallback)` in
`config_loader._InstanceCfg`, usato per livello/truppe/max_squadre/tipologia).

---

## 2. Storage & normalizzazione

- Override in `runtime_overrides.json::istanze.<nome>.allocazione =
  {pomodoro, legno, petrolio, acciaio}` (percentuali 0-100, come il globale
  `raccolta.allocazione`).
- `config_loader._InstanceCfg` normalizza a **frazioni somma=1** (robusto a
  % o frazioni: divide per la somma). Somma 0/invalida → fallback globale.
- Mapping risorsa→nodo invariato: pomodoro→campo, legno→segheria.

---

## 3. Piano step-by-step (con validazione, come WU204)

| Step | Contenuto | Stato |
|---|---|---|
| **1** | `config_loader._InstanceCfg`: `ALLOCAZIONE_*` da override per-istanza (normalizzato) con fallback globale + unit test. | ✅ `a3ee410` (7 test) |
| **2** | `IstanzaOverride.allocazione` + whitelist `patch_istanza` + merge-safe. | ✅ `e41e4b7` (10 test) |
| **3** | Reader `config_manager.get_allocazione_istanze()`. | ✅ `1f8d11b` |
| **4** | **UI matrice** (Variante A) in `/ui/raccolta`: endpoint + template (input % + barra mix + totale + salva/reset per riga) via PATCH per-istanza. | ✅ `1f8d11b` |

**WU205 COMPLETATO** (13/07). Validato end-to-end su dati prod: render 12
istanze (tutte "globale" = retrocompat), PATCH custom → persiste + badge, reset
→ globale. Effetto al prossimo tick raccolta (nessun riavvio bot necessario,
`runtime_overrides` riletto a inizio ciclo). **Fase 2 opzionale** (non fatta):
barra read-only compatta nella card HOME (Variante C).

Ogni step: commit isolato + sync + validazione. Nessun riavvio necessario per
il salvataggio config (il bot rilegge `runtime_overrides` a inizio ciclo, come
per gli altri override per-istanza). L'allocazione ha effetto al prossimo tick
raccolta dell'istanza.

---

## 4. Rischi / note

- **Retrocompat**: nessuna istanza ha override oggi → tutte usano il globale,
  comportamento invariato finché non imposti un override.
- **Normalizzazione**: la matrice normalizza a 100 lato UI + il loader
  normalizza a 1 lato bot (doppia rete). Somma 0 → fallback globale.
- **Colori risorse** (barre): rosso/ambra/grigio/blu — validare solo se
  estesi alla card HOME (Variante C, fase 2).
- **Fase 2 opzionale** (non ora): barra read-only compatta nella card istanza
  HOME (Variante C).
