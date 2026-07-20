# ==============================================================================
#  DOOMSDAY ENGINE V6 - tasks/boost.py
#
#  Task: attivazione Gathering Speed Boost con scheduling intelligente.
#
#  REFACTORING 16/04/2026 — BoostState:
#    - Scheduling centralizzato in BoostState (core/state.py)
#    - should_run() legge ctx.state.boost.should_run() — nessuna logica in main.py
#    - Quando boost trovato GIÀ ATTIVO → registra_attivo("8h", now) (default)
#    - Quando boost attivato → registra_attivo(tipo, now)
#    - Quando nessun boost → registra_non_disponibile() → riprova al prossimo tick
#    - Interval fisso rimosso da _TASK_SETUP — la scadenza governa il timing
#
#  FIX 19/04/2026 — ripristino comportamento V5 sotto-maschera USE:
#    Dopo il tap su "Gathering Speed" veniva fatto 1 screenshot dopo 0.5s
#    fissi. Provato con polling 5s (commit a0f344a) → nessun miglioramento.
#    Provato con tap su (speed_cx, speed_cy) (commit 08069fc) → peggio,
#    il tap sull'icona non apriva la sotto-maschera.
#    Ripristinato V5: tap su (480, speed_cy) con X fisso centro schermo +
#    time.sleep(2.0) fisso + singolo screenshot. V5 produzione conferma
#    che questa combinazione apre correttamente la sotto-maschera USE.
#
#  FIX 19/04/2026 — ricentro riga Gathering Speed post-swipe:
#    Problema: dopo N swipe la lista popup ha un offset interno che rende
#    il tap (480, speed_cy) non responsivo (UI non cambia, pin_speed_use
#    mai trovato, score=-1.000 su tutte le istanze).
#    Causa: il tap viene eseguito ma il gioco non registra l'evento perché
#    la riga è in posizione "di scorrimento" instabile nel viewport.
#    Fix: quando pin_speed trovato dopo swipe > 0, eseguire un mini-swipe
#    inverso (giù) per riportare la riga verso il centro schermo, poi
#    ri-rilevare la posizione aggiornata prima del tap.
#    Fix aggiuntivi: delay post-tap-boost 1.5s (come V5), polling
#    pin_speed_use con timeout 4s invece di singolo screenshot.
#
#  Flusso:
#    1. should_run() → legge BoostState: skip se boost attivo e non in scadenza
#    2. Assicura HOME via navigator
#    3. Screenshot + tap TAP_BOOST → apre Manage Shelter
#    4. Verifica pin_manage → popup aperto
#    5. Scroll finché pin_speed visibile (max MAX_SWIPE)
#    6. Se pin_50_ visibile → boost già attivo → registra "8h" → chiudi popup
#    7. [FIX] Se swipe > 0 → ricentro riga con mini-swipe inverso + ri-rilevamento
#    8. Tap riga Gathering Speed (480, speed_cy)
#    9. [FIX] Polling fino a pin_speed_use visibile (timeout 4s)
#   10. Cerca pin_speed_8h + pin_speed_use → tap USE → registra "8h"
#   11. Fallback: cerca pin_speed_1d + pin_speed_use → tap USE → registra "1d"
#   12. Nessun boost → registra_non_disponibile() → chiudi popup
#
#  Logging BoostState:
#    [BOOST] stato: tipo=8h  scadenza=2026-04-16T16:00:00+00:00  ATTIVO (+7h45m)
#    [BOOST] → skip (boost attivo)
#    [BOOST] → entra (boost scaduto/in scadenza)
#
#  ESTENSIONE 20/07/2026 — boost produzione risorsa (pomodoro/legno/acciaio/
#  petrolio), calibrata dal vivo via ADB su FAU_00. Stesso popup Manage
#  Shelter, sezione "Economic Boost", MA sotto-pagina dedicata (non inline
#  come Gathering) — vedi commenti su BoostConfig/_esegui_produzione più
#  sotto per i dettagli del nuovo flusso. Un solo popup aperto per tick,
#  gestisce fino a 5 slot indipendenti (le 4 produzioni + gathering).
# ==============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.task import Task, TaskContext, TaskResult
from core.state import BoostState

if TYPE_CHECKING:
    from core.device import FakeDevice
    from shared.template_matcher import TemplateMatcher


# ==============================================================================
# Debug — salvataggio screenshot per ispezione UI
# ==============================================================================

# DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta (wait_after_tap_speed: 2.0s)
# Funzione mantenuta per riattivazione futura. Per riabilitare, decommentare le
# chiamate `_salva_debug_shot(...)` in _esegui_boost (cerca "DEBUG DISATTIVATO").
def _salva_debug_shot(screen, suffisso: str, log) -> None:
    """
    Salva screenshot corrente in debug_task/boost/.
    Filename: boost_{suffisso}_{YYYYMMDD_HHMMSS}.png
    Usa cv2.imwrite sul frame BGR. .gitignore esclude *.png.
    """
    try:
        import cv2
        from datetime import datetime as _dt
        frame = getattr(screen, "frame", None)
        if frame is None:
            return
        root = Path(__file__).resolve().parents[1]
        out_dir = root / "debug_task" / "boost"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        filename = f"boost_{suffisso}_{ts}.png"
        filepath = out_dir / filename
        cv2.imwrite(str(filepath), frame)
        log(f"[DEBUG] screenshot salvato: debug_task/boost/{filename}")
    except Exception as exc:
        log(f"[DEBUG] salvataggio screenshot fallito: {exc}")


@dataclass
class BoostConfig:
    tap_boost:                tuple[int, int] = (142, 47)
    n_back_chiudi:            int             = 3
    max_swipe:                int             = 8
    swipe_x:                  int             = 480
    swipe_y_start:            int             = 380
    swipe_y_end:              int             = 280
    swipe_dur_ms:             int             = 400
    wait_after_tap_boost:     float           = 1.5    # FIX: come V5, prima del polling manage
    wait_after_swipe:         float           = 1.5
    wait_after_use:           float           = 1.5
    wait_after_back:          float           = 0.5
    wait_after_tap_speed:     float           = 2.0    # regola DELAY UI — da fix rifornimento 20/04/2026
    # FIX ricentro: mini-swipe inverso (dito scende = lista sale = riga scende nel viewport)
    ricentro_swipe_y_start:   int             = 280    # da dove parte il dito
    ricentro_swipe_y_end:     int             = 360    # dove arriva (80px verso il basso)
    ricentro_swipe_dur_ms:    int             = 300
    wait_after_ricentro:      float           = 1.2
    # FIX polling pin_speed_use dopo tap riga
    timeout_speed_use:        float           = 4.0    # polling finché sotto-maschera si apre
    poll_speed_use:           float           = 0.5
    tmpl_boost:               str             = "pin/pin_boost.png"
    tmpl_manage:              str             = "pin/pin_manage.png"
    tmpl_speed:               str             = "pin/pin_speed.png"
    tmpl_50:                  str             = "pin/pin_50_.png"
    tmpl_speed_8h:            str             = "pin/pin_speed_8h.png"
    tmpl_speed_1d:            str             = "pin/pin_speed_1d.png"
    tmpl_speed_use:           str             = "pin/pin_speed_use.png"
    soglia_boost:             float           = 0.80
    soglia_manage:            float           = 0.75
    soglia_speed:             float           = 0.75
    soglia_50:                float           = 0.75
    soglia_8h:                float           = 0.75
    soglia_1d:                float           = 0.75
    soglia_use:               float           = 0.75

    # RETE DI SICUREZZA 20/07/2026 (test live master, individuato dall'utente):
    # se si preme USE su un boost GIÀ ATTIVO (produzione O gathering) il gioco
    # mostra un dialogo "You have already activated a buff of the same type.
    # Activating a new buff will replace the effect... Continue?" con
    # CANCEL/OK. Premere OK sostituirebbe il boost (spreca il tempo residuo +
    # consuma un boost nuovo). Comportamento corretto: CANCEL → non consuma,
    # esito "già attivo". Vale per TUTTE le istanze (nessuna regola specifica
    # per il master). È un secondo livello di protezione oltre al
    # riconoscimento visivo "già attivo" (barra +25%/pin_50_): se quello
    # fallisce (es. barra tagliata borderline), questo dialogo evita comunque
    # lo spreco.
    tmpl_buff_replace:        str             = "pin/pin_buff_replace.png"
    soglia_buff_replace:      float           = 0.80
    tap_dialog_cancel:        tuple[int, int] = (371, 381)
    wait_dialog_check:        float           = 1.5   # attesa comparsa dialogo/banner post-USE
    wait_after_dialog:        float           = 1.0

    # ── Estensione 20/07/2026 — boost produzione risorsa (Economic Boost) ──
    # Verificato live via ADB su FAU_00 (bot spento, calibrazione diretta):
    # sezione "Economic Boost" del popup Manage Shelter ha 4 righe boost
    # produzione (Food/Wood/Steel/Oil Production = pomodoro/legno/acciaio/
    # petrolio), ordine confermato dall'alto verso il basso. A differenza di
    # Gathering Speed (espansione inline), il tap sulla riga apre una
    # SOTTO-PAGINA con 2 righe fisse ("8h Boost" poi "24h Boost"), ciascuna
    # col proprio pulsante USE — layout identico verificato su tutte e 4.
    produzioni: tuple["ProduzioneBoostConfig", ...] = field(default_factory=lambda: (
        ProduzioneBoostConfig("pomodoro", "pin/pin_food_production.png",  "pin/pin_food_active.png"),
        ProduzioneBoostConfig("legno",    "pin/pin_wood_production.png",  "pin/pin_wood_active.png"),
        ProduzioneBoostConfig("acciaio",  "pin/pin_steel_production.png", "pin/pin_steel_active.png"),
        ProduzioneBoostConfig("petrolio", "pin/pin_oil_production.png",   "pin/pin_oil_active.png"),
    ))
    # Coordinate sotto-pagina — fisse, identiche per tutte e 4 le risorse
    # (verificato live, nessuno scroll necessario dentro la sotto-pagina).
    tap_subpage_use_8h:       tuple[int, int] = (727, 155)
    tap_subpage_use_24h:      tuple[int, int] = (727, 232)
    tap_subpage_back:         tuple[int, int] = (167, 65)
    # Zone di ricerca per disambiguare quale pulsante USE (8h vs 24h) è
    # presente — pin_speed_use.png è identico su entrambe le righe, la
    # zona (non il contenuto) distingue le due posizioni.
    zone_subpage_use_8h:      tuple[int, int, int, int] = (650, 135, 810, 175)
    zone_subpage_use_24h:     tuple[int, int, int, int] = (650, 212, 810, 252)
    wait_after_subpage_open:  float = 2.0    # regola DELAY UI vincolante
    wait_after_subpage_back:  float = 1.0
    # BUG REALE 20/07/2026 (test live FAU_01/FAU_02, individuato dall'utente):
    # dopo il tap USE il gioco mostra un banner "You used X Boost" in alto
    # che BLOCCA la freccia back per ~2-3s (il back premuto troppo presto non
    # torna alla lista — resta incastrato sulla sotto-pagina, e gli slot
    # successivi girano a vuoto). Misurato dal vivo su FAU_02: con ~3s tra USE
    # e back il back funziona sempre. Fix: attesa più lunga PRIMA del back +
    # VERIFICA via template di essere tornato alla lista, con RETRY (non
    # timing cieco). L'utente lo fa naturalmente a mano (tempo di reazione
    # umano > 1.5s), il bot deve replicarlo esplicitamente.
    wait_after_use_produzione: float = 3.0   # attesa post-USE (banner sparisce)
    max_back_retry:           int   = 3      # tentativi di back verificato

    # BUG REALE 20/07/2026 — trovato durante il test live su FAU_01: i 4
    # template "attivo" (testo verde "<Risorsa> Production +25%") si
    # assomigliano abbastanza (stesso font/colore/sfondo) da produrre falsi
    # positivi INCROCIATI se cercati su tutto lo schermo — es. pin_wood_active
    # score 0.91 su un frame dove era ATTIVA SOLO food, non wood (verificato
    # con l'utente: nessun boost era stato attivato manualmente, legno NON
    # era davvero attivo). Prima versione del fix (finestra rettangolare
    # relativa alla riga) SCARTATA su feedback dell'utente — l'offset
    # riga→barra varia troppo (36-54px misurato su 4 righe/screenshot
    # indipendenti, non un valore fisso) e "vincolare tutto allo swipe" non
    # è robusto. Fix definitivo: STESSO pattern già collaudato di Gathering
    # (ROW_TOL, vedi _esegui_gathering) — cerca il template "attivo" su
    # TUTTO lo schermo (find_all, nessuna finestra), poi verifica che il
    # candidato più vicino sia entro row_tol_produzione dalla riga trovata.
    # Calibrato sui dati reali: veri positivi 36-54px dalla riga, falsi
    # incrociati (riga adiacente) 63-79px — 58px sta nel margine tra i due
    # cluster osservati, coerente con ROW_TOL=50 di Gathering (stesso
    # ordine di grandezza, qui leggermente più largo perché il delta
    # riga→barra della produzione è maggiore di quello di Gathering).
    row_tol_produzione:       int = 58

    # EDGE CASE 20/07/2026 (test live FAU_02, individuato dall'utente): se la
    # riga produzione è trovata troppo in fondo allo schermo, la barra verde
    # "+25%" (che sta ~41px SOTTO la riga) finisce tagliata dal bordo del
    # popup → il boost già attivo NON viene riconosciuto → ri-attivazione
    # (spreco di 1 boost). Mitigazione: se la riga è sotto soglia_ricentro_row,
    # un mini-swipe su per portarla più in alto + ri-ricerca, così la barra
    # rientra nel viewport prima del check "attivo". Pattern analogo al
    # ricentro di Gathering (WU 19/04). Il popup Manage Shelter finisce
    # ~y=490; barra a row_cy+41 → riga oltre ~449 taglia la barra, soglia 400
    # per margine.
    soglia_ricentro_row:      int = 400


@dataclass
class ProduzioneBoostConfig:
    """Un boost produzione risorsa (pomodoro/legno/acciaio/petrolio)."""
    risorsa:       str
    tmpl_row:      str      # icona riga nella lista scrollabile
    tmpl_active:   str      # testo verde "<Risorsa> Production +25%" (già attivo)
    soglia_row:    float = 0.80
    soglia_active: float = 0.80


class _Outcome:
    GIA_ATTIVO        = "boost_gia_attivo"
    ATTIVATO_8H       = "boost_attivato_8h"
    ATTIVATO_1D       = "boost_attivato_1d"
    NESSUN_BOOST      = "nessun_boost_disponibile"
    POPUP_NON_APERTO  = "popup_non_aperto"
    SPEED_NON_TROVATO = "speed_non_trovato"
    ERRORE            = "errore"


class BoostTask(Task):
    """
    Attiva i booster del popup Manage Shelter → "Economic Boost": Gathering
    Speed + i 4 booster produzione risorsa (pomodoro/legno/acciaio/petrolio,
    estensione 20/07/2026), ciascuno con scheduling indipendente via
    BoostState (gathering) / ProduzioneBoostState (produzione, 4 slot
    BoostState — stessa classe riusata).

    Scheduling: non usa interval fisso in _TASK_SETUP.
    La decisione di eseguire è delegata a should_run(): entra se Gathering
    O ALMENO UNA produzione richiede un check (attivo/mai attivato/scaduto/
    nessun boost trovato → esegue quel/i slot).
    """

    def __init__(self, config: BoostConfig | None = None) -> None:
        self._cfg = config or BoostConfig()

    def name(self) -> str:
        return "boost"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("boost"):
                return False
        # Estensione 20/07/2026 — entra se Gathering Speed O almeno UNA delle
        # 4 produzioni risorsa (pomodoro/legno/acciaio/petrolio) è dovuta.
        return ctx.state.boost.should_run() or ctx.state.produzione_boost.should_run_qualcuno()

    def run(self, ctx: TaskContext) -> TaskResult:
        def log(msg: str) -> None:
            ctx.log_msg(f"[BOOST] {msg}")

        cfg = self._cfg
        gathering_dovuto  = ctx.state.boost.should_run()
        produzioni_dovute = [
            p for p in cfg.produzioni
            if ctx.state.produzione_boost.slot(p.risorsa).should_run()
        ]

        log(f"stato gathering: {ctx.state.boost.log_stato()}")
        for p in cfg.produzioni:
            log(f"stato {p.risorsa}: {ctx.state.produzione_boost.slot(p.risorsa).log_stato()}")

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="assicura_home")

        # WU115 — debug buffer (hot-reload via globali.debug_tasks.boost)
        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("boost", getattr(ctx, "instance_name", "_unknown"))
        self._dbg = debug

        risultati: dict[str, tuple[str, str | None]] = {}
        try:
            if not self._apri_manage_shelter(ctx.device, ctx.matcher, cfg, log):
                debug.flush(success=True, force=True, log_fn=log)
                return TaskResult.skip("Manage Shelter non aperto")

            # Produzione PRIMA di gathering — ogni slot produzione torna
            # sempre alla lista via tap_subpage_back (verificato live, popup
            # resta aperto qualunque sia l'esito). Gathering va SEMPRE per
            # ultimo: il suo ramo ATTIVATO_8H/1D chiude l'INTERO popup con un
            # solo back() (comportamento originale collaudato, vedi test
            # `test_back_dopo_use`) — un _chiudi_popup() extra dopo
            # rischierebbe di premere back a vuoto già su HOME (dialogo
            # "Exit game?", incidente osservato durante la calibrazione live
            # del 20/07 — vedi debug_task/boost_extension/10_back_home.png).
            for p in produzioni_dovute:
                risultati[p.risorsa] = self._esegui_produzione(ctx.device, ctx.matcher, log, cfg, p)

            gathering_ha_chiuso_tutto = False
            if gathering_dovuto:
                outcome, tipo = self._esegui_gathering(ctx.device, ctx.matcher, log, cfg)
                risultati["gathering"] = (outcome, tipo)
                gathering_ha_chiuso_tutto = outcome in (_Outcome.ATTIVATO_8H, _Outcome.ATTIVATO_1D)

            if not gathering_ha_chiuso_tutto:
                self._chiudi_popup(ctx.device, cfg)
        except Exception as exc:
            debug.snap("99_exception", ctx.device.screenshot())
            debug.flush(success=False, log_fn=log)
            return TaskResult.fail(f"Eccezione: {exc}", step="esegui_boost")

        # Anomalie: qualunque slot con riga non trovata o errore forza il flush
        anomalia = any(
            outcome in (_Outcome.SPEED_NON_TROVATO, _Outcome.ERRORE)
            for outcome, _tipo in risultati.values()
        )
        ha_errore = any(outcome == _Outcome.ERRORE for outcome, _tipo in risultati.values())
        debug.flush(success=not ha_errore, force=anomalia, log_fn=log)

        # ── Aggiorna gli state slot coinvolti ─────────────────────────────────
        now = datetime.now(timezone.utc)

        if "gathering" in risultati:
            outcome, tipo = risultati["gathering"]
            self._aggiorna_state_slot(ctx.state.boost, outcome, tipo, "BoostState", log, now)

        for p in produzioni_dovute:
            outcome, tipo = risultati[p.risorsa]
            self._aggiorna_state_slot(
                ctx.state.produzione_boost.slot(p.risorsa), outcome, tipo,
                f"ProduzioneBoostState[{p.risorsa}]", log, now,
            )

        return self._mappa_risultati(risultati, log)

    @staticmethod
    def _aggiorna_state_slot(
        slot: BoostState, outcome: str, tipo_attivato: str | None,
        nome_log: str, log, now: datetime,
    ) -> None:
        """Applica lo stesso pattern registra_attivo/registra_non_disponibile
        già usato per Gathering a QUALSIASI slot BoostState (gathering o
        produzione risorsa — riusa la stessa classe, vedi ProduzioneBoostState)."""
        if outcome in (_Outcome.GIA_ATTIVO, _Outcome.ATTIVATO_8H, _Outcome.ATTIVATO_1D):
            tipo = tipo_attivato or "8h"
            slot.registra_attivo(tipo, riferimento=now)
            log(f"{nome_log} aggiornato → {slot.log_stato()}")
        elif outcome == _Outcome.NESSUN_BOOST:
            slot.registra_non_disponibile()
            log(f"{nome_log} → nessun boost disponibile, riprova al prossimo tick")
        # SPEED_NON_TROVATO / ERRORE: stato invariato, il task riprova al
        # prossimo tick secondo la scadenza esistente (comportamento
        # invariato dal design originale single-slot).

    # ── Flusso principale ─────────────────────────────────────────────────────

    def _apri_manage_shelter(self, device, matcher, cfg: BoostConfig, log) -> bool:
        """
        Apre il popup Manage Shelter (STEP 1-2 del flusso originale).
        Ritorna True se il popup è aperto (pin_manage trovato), False
        altrimenti — in caso di False chiude eventuali resti prima di
        tornare (comportamento POPUP_NON_APERTO invariato).
        """
        _dbg = getattr(self, "_dbg", None)

        # STEP 1 — tap boost
        shot    = device.screenshot()
        score_b = matcher.score(shot, cfg.tmpl_boost)
        if _dbg is not None:
            _dbg.snap_array("00_pre_tap_boost", getattr(shot, "frame", None))
        log(f"pin_boost score={score_b:.3f} → tap {cfg.tap_boost}")
        device.tap(*cfg.tap_boost)

        # FIX: delay post-tap come V5 (1.5s) prima del polling manage
        # Senza questo delay il polling parte mentre l'animazione di apertura
        # del popup non è ancora iniziata.
        time.sleep(cfg.wait_after_tap_boost)

        # STEP 2 — attesa polling popup Manage Shelter (max 6s)
        # Nota: il sleep sopra già copre il primo secondo, quindi il timeout
        # effettivo è 6s aggiuntivi oltre al wait_after_tap_boost.
        score_m = self._attendi_template(
            device, matcher, cfg.tmpl_manage, cfg.soglia_manage,
            timeout=6.0, poll=0.5
        )
        log(f"pin_manage score={score_m:.3f}")
        if _dbg is not None:
            _dbg.snap("01_popup_manage", device.screenshot())
        if score_m < cfg.soglia_manage:
            log("Popup non aperto — abort")
            self._chiudi_popup(device, cfg)
            return False
        return True

    def _esegui_gathering(
        self,
        device,
        matcher,
        log,
        cfg: BoostConfig,
    ) -> tuple[str, str | None]:
        """
        Gestisce lo slot Gathering Speed (STEP 3-8 del flusso originale).
        Precondizione: Manage Shelter già aperto (_apri_manage_shelter).
        NON chiude il popup — la chiusura è responsabilità del chiamante
        (run()), che deve poter gestire altri slot (produzione) nella
        stessa visita al popup prima di chiudere.
        Ritorna (outcome, tipo) dove tipo è "8h" | "1d" | None.
        """
        _dbg = getattr(self, "_dbg", None)

        # STEP 3 — scroll fino a pin_speed
        speed_trovato = False
        speed_cx      = -1
        speed_cy      = -1
        score_50_last = -1.0
        swipe_eseguiti = 0

        for swipe_n in range(cfg.max_swipe + 1):
            shot        = device.screenshot()
            score_speed = matcher.score(shot, cfg.tmpl_speed)
            score_50    = matcher.score(shot, cfg.tmpl_50)
            log(f"swipe {swipe_n:02d} → pin_speed={score_speed:.3f}  pin_50_={score_50:.3f}")

            if score_speed >= cfg.soglia_speed:
                match = matcher.find_one(shot, cfg.tmpl_speed, threshold=cfg.soglia_speed)
                if match and match.found:
                    speed_cx = match.cx
                    speed_cy = match.cy
                else:
                    speed_cx = 480
                    speed_cy = 270
                speed_trovato  = True
                score_50_last  = score_50
                swipe_eseguiti = swipe_n
                log(f"pin_speed TROVATO cx={speed_cx} cy={speed_cy} (dopo {swipe_n} swipe)")
                break

            score_50_last = max(score_50_last, score_50)
            if swipe_n < cfg.max_swipe:
                self._swipe_su(device, cfg)

        if _dbg is not None:
            _dbg.snap("02_post_scroll_speed", device.screenshot())
        if not speed_trovato:
            log(f"pin_speed non trovato dopo {cfg.max_swipe} swipe — abort")
            return _Outcome.SPEED_NON_TROVATO, None

        # STEP 4 — boost già attivo?
        if score_50_last >= cfg.soglia_50:
            log(f"Boost GIÀ ATTIVO (pin_50_ score={score_50_last:.3f}) → registra 8h")
            return _Outcome.GIA_ATTIVO, "8h"

        # STEP 4b — ricentro riga post-swipe RIMOSSO per test isolato
        # (test: verificare se tap su (speed_cx, speed_cy) centra correttamente
        # la riga sull'icona pin_speed senza passare per ricentro mini-swipe).

        # DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta. Per riabilitare,
        # decommentare le 3 righe sotto.
        # shot_pre = device.screenshot()
        # if shot_pre is not None:
        #     _salva_debug_shot(shot_pre, "pre_tap", log)

        # STEP 5 — tap riga Gathering Speed
        # TEST ISOLATO 19/04/2026: tap su (speed_cx, speed_cy) invece di
        # (480, speed_cy). Obiettivo: isolare l'effetto del tap esattamente
        # sul centro del match pin_speed, specie quando la riga è in fondo
        # alla lista (cy alto, es. 452 osservato) dove (480, cy) cadeva in
        # zona non responsiva.
        tap_speed = (speed_cx, speed_cy)
        log(f"Tap Gathering Speed {tap_speed}")
        device.tap(*tap_speed)

        # STEP 6 — FIX polling pin_speed_use (timeout 4s)
        # Sostituisce il singolo screenshot fisso a 2.0s.
        # La sotto-maschera USE impiega variabile 0.5–2.5s ad aprirsi
        # a seconda del carico del dispositivo. Il polling garantisce
        # di catturare il frame corretto indipendentemente dalla latenza.
        time.sleep(cfg.wait_after_tap_speed)  # attesa rendering popup USE (regola DELAY UI — da fix rifornimento 20/04/2026)
        shot = self._attendi_frame_use(device, matcher, cfg, log)

        # DEBUG DISATTIVATO 26/04/2026 — Issue #13 risolta. Per riabilitare,
        # decommentare le 2 righe sotto.
        # if shot is not None:
        #     _salva_debug_shot(shot, "post_tap", log)

        if _dbg is not None and shot is not None:
            _dbg.snap_array("03_frame_use", getattr(shot, "frame", None))
        if shot is None:
            log("Screenshot fallito dopo tap speed — abort")
            return _Outcome.ERRORE, None

        # STEP 7-8 — boost 8h preferito, 1d fallback.
        # FIX 26/04 (auto-WU9): row alignment check tra template durata e
        # bottone USE. Pre-fix: `matcher.score()` ritornava la correlazione
        # max nell'INTERA immagine, sensibile a falsi positivi (pin_speed_8h
        # matchava elementi UI fuori dal popup), causando registrazione "8h"
        # quando in realtà il bot tappava USE associato al 1d.
        # Post-fix: `find_one()` con soglia + verifica |cy_durata - cy_use|
        # < 50px → garantisce che la durata associata a USE sia quella
        # registrata (stessa riga del popup).
        match_8h  = matcher.find_one(shot, cfg.tmpl_speed_8h, threshold=cfg.soglia_8h)
        match_1d  = matcher.find_one(shot, cfg.tmpl_speed_1d, threshold=cfg.soglia_1d)
        match_use = matcher.find_one(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use)

        score_8h  = match_8h.score  if (match_8h  and match_8h.found)  else -1.0
        score_1d  = match_1d.score  if (match_1d  and match_1d.found)  else -1.0
        score_use = match_use.score if (match_use and match_use.found) else -1.0

        cy_8h     = match_8h.cy     if (match_8h  and match_8h.found)  else None
        cy_1d     = match_1d.cy     if (match_1d  and match_1d.found)  else None
        cy_use    = match_use.cy    if (match_use and match_use.found) else None

        log(f"pin_speed_8h={score_8h:.3f} (cy={cy_8h})  "
            f"pin_speed_1d={score_1d:.3f} (cy={cy_1d})  "
            f"pin_speed_use={score_use:.3f} (cy={cy_use})")

        if match_use is None or not match_use.found:
            log("Nessun pin_speed_use")
            return _Outcome.NESSUN_BOOST, None

        ROW_TOL = 50  # tolleranza Y per "stessa riga"
        aligned_8h = cy_8h is not None and abs(cy_8h - cy_use) < ROW_TOL
        aligned_1d = cy_1d is not None and abs(cy_1d - cy_use) < ROW_TOL

        # Preferenza 8h (se allineato), altrimenti 1d (se allineato).
        # RETE DI SICUREZZA 20/07/2026: dopo il tap USE, se il gathering era
        # GIÀ ATTIVO compare il dialogo "replace the effect?" →
        # _gestisci_dialogo_gia_attivo preme CANCEL (non consuma) → GIA_ATTIVO.
        # Risolve il caso pin_50_ borderline (barra +50% tagliata quando la
        # riga è in fondo) osservato sul master. wait_after_use gestito
        # dall'helper.
        if aligned_8h:
            log(f"Boost 8h ALLINEATO USE (Δcy={abs(cy_8h-cy_use)}) → tap USE "
                f"({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            gia = self._gestisci_dialogo_gia_attivo(device, matcher, cfg, log, "gathering")
            device.back()
            time.sleep(cfg.wait_after_back)
            return (_Outcome.GIA_ATTIVO if gia else _Outcome.ATTIVATO_8H), "8h"

        if aligned_1d:
            log(f"Boost 1d ALLINEATO USE (Δcy={abs(cy_1d-cy_use)}) → tap USE "
                f"({match_use.cx},{match_use.cy})")
            device.tap(match_use.cx, match_use.cy)
            gia = self._gestisci_dialogo_gia_attivo(device, matcher, cfg, log, "gathering")
            device.back()
            time.sleep(cfg.wait_after_back)
            return (_Outcome.GIA_ATTIVO if gia else _Outcome.ATTIVATO_1D), "1d"

        log(f"USE presente ma nessuna durata (8h/1d) allineata sulla stessa riga "
            f"(Δcy_8h={abs(cy_8h-cy_use) if cy_8h is not None else 'n/a'}, "
            f"Δcy_1d={abs(cy_1d-cy_use) if cy_1d is not None else 'n/a'}) — "
            f"skip per evitare registrazione errata")
        return _Outcome.NESSUN_BOOST, None

        log("Nessun boost gratuito disponibile — chiudo popup")
        self._chiudi_popup(device, cfg)
        return _Outcome.NESSUN_BOOST, None

    def _esegui_produzione(
        self,
        device,
        matcher,
        log,
        cfg: BoostConfig,
        prod_cfg: ProduzioneBoostConfig,
    ) -> tuple[str, str | None]:
        """
        Gestisce UNO slot boost produzione risorsa (pomodoro/legno/acciaio/
        petrolio). Estensione 20/07/2026 — calibrata dal vivo su FAU_00.

        Precondizione: Manage Shelter già aperto. NON chiude il popup (come
        _esegui_gathering — la chiusura è responsabilità del chiamante).

        Flusso (diverso da Gathering — sotto-pagina dedicata, non inline):
          1. Scroll cercando tmpl_row (le icone SONO discriminanti tra
             risorse, verificato — nessun cross-match).
          2. Se non trovato dopo max_swipe → SPEED_NON_TROVATO.
          3. Riga trovata → cerca tmpl_active su TUTTO lo schermo
             (find_all, come Gathering), poi verifica che il candidato più
             vicino sia entro row_tol_produzione dalla riga trovata — STESSO
             pattern ROW_TOL già collaudato di Gathering (allineamento per
             prossimità, non una finestra rettangolare fissa). I 4 template
             "attivo" si assomigliano (stesso stile testo verde) e
             produrrebbero falsi positivi incrociati con una risorsa DIVERSA
             attiva altrove nel frame se cercati senza verificare la
             posizione (bug reale trovato 20/07/2026 sul test live FAU_01 —
             legno/petrolio segnalati "già attivi" quando non lo erano,
             individuato dall'utente confrontando col gioco reale — nessun
             boost era mai stato attivato manualmente sull'istanza).
          4. Se un candidato è entro tolleranza → GIA_ATTIVO, nessun tap.
          5. Altrimenti tap riga → sotto-pagina con 2 righe fisse (8h poi
             24h), ciascuna col proprio USE — nessun allineamento riga
             necessario qui (diverso da Gathering), la ZONA distingue le due
             righe (pin_speed_use.png è identico su entrambe, ma le due
             posizioni della sotto-pagina sono FISSE, non scorrono).
          6. Preferenza 8h (zone_subpage_use_8h), fallback 24h
             (zone_subpage_use_24h) se 8h non disponibile in quella zona.
          7. Ritorno alla lista VERIFICATO (_chiudi_sottopagina): dopo USE il
             banner "You used" blocca il back per ~2-3s → attesa +
             back-con-verifica + retry (la sotto-pagina NON torna da sola dopo
             USE, verificato live; e un back cieco troppo presto resta
             incastrato — bug reale 20/07/2026).

        Ritorna (outcome, tipo) dove tipo è "8h" | "1d" | None.
        """
        _dbg = getattr(self, "_dbg", None)
        risorsa = prod_cfg.risorsa

        trovato       = False
        gia_attivo    = False
        score_active  = 0.0
        row_cx        = 480
        row_cy        = 270

        for swipe_n in range(cfg.max_swipe + 1):
            shot      = device.screenshot()
            match_row = matcher.find_one(shot, prod_cfg.tmpl_row, threshold=prod_cfg.soglia_row)
            log(f"[{risorsa}] swipe {swipe_n:02d} → riga={match_row.score:.3f} "
                f"(found={match_row.found})")

            if match_row.found:
                row_cx, row_cy = match_row.cx, match_row.cy
                # EDGE CASE: se la riga è troppo in fondo, la barra "+25%" sotto
                # di essa è tagliata dal bordo del popup → falso negativo sul
                # check "attivo". Ricentro con un mini-swipe su + ri-ricerca
                # (pattern ricentro Gathering) prima di leggere la barra.
                if row_cy > cfg.soglia_ricentro_row:
                    log(f"[{risorsa}] riga in fondo (cy={row_cy}) → ricentro per "
                        f"non tagliare la barra attivo")
                    self._swipe_su(device, cfg)
                    shot = device.screenshot()
                    match_row2 = matcher.find_one(shot, prod_cfg.tmpl_row,
                                                   threshold=prod_cfg.soglia_row)
                    if match_row2.found:
                        row_cx, row_cy = match_row2.cx, match_row2.cy
                        log(f"[{risorsa}] riga ri-trovata dopo ricentro ({row_cx},{row_cy})")
                # STESSO pattern ROW_TOL di Gathering: cerca su TUTTO lo
                # schermo (nessuna finestra rettangolare), poi verifica la
                # prossimità Y al candidato più vicino — non una finestra
                # calibrata a mano (fragile, vedi commento su BoostConfig).
                candidati = matcher.find_all(shot, prod_cfg.tmpl_active,
                                              threshold=prod_cfg.soglia_active)
                vicino = min(candidati, key=lambda c: abs(c.cy - row_cy), default=None)
                if vicino is not None and abs(vicino.cy - row_cy) < cfg.row_tol_produzione:
                    gia_attivo   = True
                    score_active = vicino.score
                    log(f"[{risorsa}] riga trovata ({row_cx},{row_cy}) → attivo "
                        f"TROVATO score={vicino.score:.3f} Δcy={abs(vicino.cy - row_cy)}")
                else:
                    log(f"[{risorsa}] riga trovata ({row_cx},{row_cy}) → nessun "
                        f"candidato attivo entro tolleranza "
                        f"({[round(c.score,3) for c in candidati]})")
                trovato = True
                break

            if swipe_n < cfg.max_swipe:
                self._swipe_su(device, cfg)

        if _dbg is not None:
            _dbg.snap(f"10_{risorsa}_post_scroll", device.screenshot())

        if not trovato:
            log(f"[{risorsa}] riga non trovata dopo {cfg.max_swipe} swipe")
            return _Outcome.SPEED_NON_TROVATO, None

        if gia_attivo:
            log(f"[{risorsa}] GIÀ ATTIVO (score={score_active:.3f})")
            return _Outcome.GIA_ATTIVO, "8h"

        # Tap riga → apre sotto-pagina dedicata (diverso da Gathering)
        log(f"[{risorsa}] tap riga ({row_cx},{row_cy})")
        device.tap(row_cx, row_cy)
        time.sleep(cfg.wait_after_subpage_open)  # regola DELAY UI vincolante

        shot = device.screenshot()
        if _dbg is not None:
            _dbg.snap(f"11_{risorsa}_subpage", shot)

        match_8h  = matcher.find_one(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use,
                                      zone=cfg.zone_subpage_use_8h)
        match_24h = matcher.find_one(shot, cfg.tmpl_speed_use, threshold=cfg.soglia_use,
                                      zone=cfg.zone_subpage_use_24h)
        log(f"[{risorsa}] sotto-pagina USE 8h={match_8h.score:.3f}  24h={match_24h.score:.3f}")

        if match_8h.found:
            log(f"[{risorsa}] USE 8h → tap {cfg.tap_subpage_use_8h}")
            device.tap(*cfg.tap_subpage_use_8h)
            if self._gestisci_dialogo_gia_attivo(device, matcher, cfg, log, risorsa):
                # boost già attivo, CANCEL premuto (non consumato) → torna alla lista
                self._chiudi_sottopagina(device, matcher, cfg, log, risorsa, dopo_use=False)
                return _Outcome.GIA_ATTIVO, "8h"
            self._chiudi_sottopagina(device, matcher, cfg, log, risorsa, dopo_use=True)
            return _Outcome.ATTIVATO_8H, "8h"

        if match_24h.found:
            log(f"[{risorsa}] USE 24h (fallback) → tap {cfg.tap_subpage_use_24h}")
            device.tap(*cfg.tap_subpage_use_24h)
            if self._gestisci_dialogo_gia_attivo(device, matcher, cfg, log, risorsa):
                self._chiudi_sottopagina(device, matcher, cfg, log, risorsa, dopo_use=False)
                return _Outcome.GIA_ATTIVO, "1d"
            self._chiudi_sottopagina(device, matcher, cfg, log, risorsa, dopo_use=True)
            return _Outcome.ATTIVATO_1D, "1d"

        log(f"[{risorsa}] nessun pulsante USE trovato nella sotto-pagina")
        self._chiudi_sottopagina(device, matcher, cfg, log, risorsa, dopo_use=False)
        return _Outcome.NESSUN_BOOST, None

    # ── Helper ────────────────────────────────────────────────────────────────

    def _gestisci_dialogo_gia_attivo(self, device, matcher, cfg: BoostConfig,
                                     log, contesto: str) -> bool:
        """
        Da chiamare SUBITO dopo un tap USE. Se il gioco mostra il dialogo
        "You have already activated a buff... replace the effect? Continue?"
        (il boost era GIÀ ATTIVO) → tap CANCEL (non sostituisce, zero spreco)
        e ritorna True. Altrimenti (nessun dialogo = boost attivato con
        successo, appare il banner "You used") ritorna False.

        RETE DI SICUREZZA 20/07/2026: secondo livello oltre al riconoscimento
        visivo "già attivo" — se quello fallisce (barra tagliata borderline),
        questo evita comunque lo spreco. Vale per produzione E gathering,
        stesso dialogo per tutte le istanze (individuato dall'utente).

        NB: l'attesa `wait_dialog_check` copre ANCHE il tempo in cui, se il
        boost NON è attivo, compare il banner "You used" — quindi il chiamante
        NON deve aspettare di nuovo prima del back nel ramo "attivato".
        """
        time.sleep(cfg.wait_dialog_check)
        shot = device.screenshot()
        score = matcher.score(shot, cfg.tmpl_buff_replace)
        if score >= cfg.soglia_buff_replace:
            log(f"[{contesto}] dialogo 'buff già attivo' (score={score:.3f}) → "
                f"CANCEL (non sostituisco, zero spreco)")
            device.tap(*cfg.tap_dialog_cancel)
            time.sleep(cfg.wait_after_dialog)
            return True
        return False

    def _chiudi_sottopagina(self, device, matcher, cfg: BoostConfig, log,
                            risorsa: str, dopo_use: bool) -> bool:
        """
        Torna dalla sotto-pagina produzione alla lista, in modo VERIFICATO.

        BUG REALE 20/07/2026 (test live, individuato dall'utente): dopo il tap
        USE il banner "You used X Boost" blocca la freccia back per ~2-3s. Un
        back cieco premuto troppo presto NON torna alla lista → gli slot
        successivi girano a vuoto. Fix: attesa post-USE + back con VERIFICA
        (il pulsante USE della sotto-pagina è ancora presente? allora non sono
        tornato → ritento) + RETRY. Se anche `dopo_use=False` (nessun boost),
        stesso pattern verificato per uniformità/robustezza.

        Ritorna True se ha confermato il ritorno alla lista, False se dopo
        max_back_retry è ancora bloccato (il chiamante prosegue comunque; il
        _chiudi_popup finale del tick fa da rete di sicurezza).
        """
        if dopo_use:
            # Attesa perché il banner "You used" sparisca e il back torni attivo.
            time.sleep(cfg.wait_after_use_produzione)

        for tentativo in range(cfg.max_back_retry):
            device.tap(*cfg.tap_subpage_back)
            time.sleep(cfg.wait_after_subpage_back)
            shot = device.screenshot()
            # Sono ancora sulla sotto-pagina se il pulsante USE (8h o 24h) è
            # ancora visibile nelle sue zone fisse. Se NON lo è → tornato alla lista.
            still_8h  = matcher.find_one(shot, cfg.tmpl_speed_use,
                                          threshold=cfg.soglia_use,
                                          zone=cfg.zone_subpage_use_8h).found
            still_24h = matcher.find_one(shot, cfg.tmpl_speed_use,
                                          threshold=cfg.soglia_use,
                                          zone=cfg.zone_subpage_use_24h).found
            if not (still_8h or still_24h):
                log(f"[{risorsa}] tornato alla lista (back tentativo {tentativo + 1})")
                return True
            log(f"[{risorsa}] ancora sulla sotto-pagina dopo back "
                f"tentativo {tentativo + 1}/{cfg.max_back_retry} — ritento")

        log(f"[{risorsa}] [WARN] back non confermato dopo {cfg.max_back_retry} "
            f"tentativi — proseguo, _chiudi_popup finale fa da rete di sicurezza")
        return False

    def _chiudi_popup(self, device, cfg: BoostConfig) -> None:
        for _ in range(cfg.n_back_chiudi):
            device.back()
            time.sleep(cfg.wait_after_back)

    def _swipe_su(self, device, cfg: BoostConfig) -> None:
        device.swipe(
            cfg.swipe_x, cfg.swipe_y_start,
            cfg.swipe_x, cfg.swipe_y_end,
            cfg.swipe_dur_ms,
        )
        time.sleep(cfg.wait_after_swipe)

    def _attendi_template(self, device, matcher, tmpl: str,
                          soglia: float, timeout: float = 5.0,
                          poll: float = 0.5) -> float:
        """
        Polling con timeout: verifica il template ogni `poll` secondi
        fino a timeout. Ritorna lo score al momento del rilevamento
        (>= soglia) oppure l'ultimo score se timeout.
        """
        t_start = time.time()
        score = 0.0
        while time.time() - t_start < timeout:
            shot = device.screenshot()
            if shot is None:
                time.sleep(poll)
                continue
            score = matcher.score(shot, tmpl)
            if score >= soglia:
                return score
            time.sleep(poll)
        return score

    def _attendi_frame_use(self, device, matcher, cfg: BoostConfig, log) -> object | None:
        """
        Polling post-tap riga: attende che pin_speed_use sia visibile
        oppure che il timeout sia scaduto.
        Ritorna il frame (screenshot) al momento del rilevamento, o
        l'ultimo frame valido se timeout.
        Logga lo score ad ogni poll per diagnostica.
        """
        t_start  = time.time()
        last_shot = None
        poll_n    = 0

        while time.time() - t_start < cfg.timeout_speed_use:
            shot = device.screenshot()
            if shot is None:
                time.sleep(cfg.poll_speed_use)
                poll_n += 1
                continue

            last_shot  = shot
            score_use  = matcher.score(shot, cfg.tmpl_speed_use)
            score_8h   = matcher.score(shot, cfg.tmpl_speed_8h)
            log(f"polling USE [{poll_n:02d}] pin_speed_use={score_use:.3f}  pin_speed_8h={score_8h:.3f}")

            if score_use >= cfg.soglia_use:
                log(f"pin_speed_use VISIBILE al poll {poll_n}")
                return shot

            time.sleep(cfg.poll_speed_use)
            poll_n += 1

        log(f"timeout {cfg.timeout_speed_use}s: pin_speed_use mai trovato — uso ultimo frame disponibile")
        return last_shot

    # ── Mapping outcome → TaskResult ──────────────────────────────────────────

    @staticmethod
    def _mappa_outcome(outcome: str, log, tipo_attivato: str | None = None) -> TaskResult:
        # Output telemetria — Issue #53 Step 3 (outcome + durata + tipo)
        mapping = {
            _Outcome.GIA_ATTIVO:        TaskResult.ok("Speed boost già attivo",
                                                       outcome="gia_attivo", durata=tipo_attivato),
            _Outcome.ATTIVATO_8H:       TaskResult.ok("Speed boost 8h attivato",
                                                       outcome="attivato", durata="8h"),
            _Outcome.ATTIVATO_1D:       TaskResult.ok("Speed boost 1d attivato",
                                                       outcome="attivato", durata="1d"),
            _Outcome.NESSUN_BOOST:      TaskResult.skip("Nessun boost gratuito disponibile"),
            _Outcome.POPUP_NON_APERTO:  TaskResult.skip("Manage Shelter non aperto"),
            _Outcome.SPEED_NON_TROVATO: TaskResult.skip("Riga Gathering Speed non trovata"),
            _Outcome.ERRORE:            TaskResult.fail("Errore generico boost"),
        }
        result = mapping.get(outcome, TaskResult.fail(f"Outcome sconosciuto: {outcome}"))
        log(f"Outcome={outcome!r} → {result}")
        return result

    @staticmethod
    def _mappa_risultati(risultati: dict[str, tuple[str, str | None]], log) -> TaskResult:
        """
        Aggrega gli esiti di TUTTI gli slot processati nel tick (gathering +
        produzioni dovute) in un unico TaskResult — estensione 20/07/2026,
        sostituisce _mappa_outcome (tenuta per compat/test, single-slot) per
        il caso multi-slot. `data` porta l'outcome grezzo per ogni slot
        (chiave = "gathering" | "pomodoro" | "legno" | "acciaio" | "petrolio"),
        usato per telemetria/log — schema diverso dal vecchio single-slot
        (`outcome`/`durata`), nessun consumer noto dipende da quello schema
        (verificato: nessun riferimento a result.data nel resto del progetto
        per il task boost).
        """
        riepilogo = {nome: outcome for nome, (outcome, _tipo) in risultati.items()}
        log(f"Riepilogo tick: {riepilogo!r}")

        if not risultati:
            return TaskResult.skip("Nessuno slot boost dovuto in questo tick")

        if any(outcome == _Outcome.ERRORE for outcome, _tipo in risultati.values()):
            return TaskResult.fail("Errore generico boost", **riepilogo)

        attivi = [nome for nome, (outcome, _tipo) in risultati.items()
                  if outcome in (_Outcome.GIA_ATTIVO, _Outcome.ATTIVATO_8H, _Outcome.ATTIVATO_1D)]
        if attivi:
            return TaskResult.ok(f"Boost attivi/confermati: {attivi}", **riepilogo)

        return TaskResult.skip(f"Nessun boost attivato in questo tick ({riepilogo})")
