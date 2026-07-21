"""
tasks/radar_master.py — RadarMasterTask V6
===========================================
Task custom master #2 (20/07/2026). Il master (FauMorfeus) ha un **Radar
Station Pass** (acquisto mensile) che abilita il pulsante **"Complete All"**
nella Radar Station: un click completa in batch tutte le missioni radar
attive, consumando stamina (50/missione, cap 1500). Le istanze ordinarie
non hanno il Pass (calibrazione del pulsante disabilitato rimandata).

Flusso (calibrato + validato live sul master, screenshot reali):
  HOME -> tap icona Radar Station (78,315) -> wait apertura+notifiche
  -> loop:
       tap Complete All (90,450) -> wait animazione ricompense
       -> se compare "You've completed all the current events!" -> FINE
       -> se si apre la maschera STAMINA -> satura con Emergency Recovery
          (+50) finché il riempimento verde della barra raggiunge il cap
          (pixel-check, NON template — il badge "XN >" cambia numero ad
          ogni tap e non è discriminante via template match, verificato)
          -> chiudi maschera (X) -> ritenta Complete All
       -> altrimenti (missione completata silenziosamente) -> ritenta
  -> chiusura SEMPRE via ctx.navigator.vai_in_home() (mai back/tap grezzo:
     un back non verificato da una vista intermedia ha aperto "Exit game?"
     in questa sessione — stesso rischio già documentato per boost/gathering)

Indipendente da tasks/radar.py (pallini+card) e radar_actions.py — nessuna
condivisione di stato, è una capacità esclusiva del master dovuta al Pass.

Non gestito in questa fase (rimandato): Complete All disabilitato (Pass
scaduto/istanza senza Pass) — la guardia di sicurezza (stato radar
inatteso ripetuto) intercetta questo caso in modo conservativo (abort
pulito), senza però un'azione utile alternativa.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from core.task import Task, TaskContext, TaskResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class RadarMasterConfig:
    tap_radar_icon:     tuple[int, int] = (78, 315)
    tap_complete_all:   tuple[int, int] = (90, 450)
    tap_use_emergency:  tuple[int, int] = (725, 260)
    tap_close_stamina:  tuple[int, int] = (792, 73)

    pin_radar_completed: str = "pin/pin_radar_completed.png"
    pin_stamina_mask:    str = "pin/pin_stamina_mask.png"
    pin_radar_title:     str = "pin/pin_radar_title.png"
    soglia_template:     float = 0.80
    # 20/07 — safety Pass non attivo: quando il Radar Station Pass (acquisto
    # mensile) è scaduto/assente, il pulsante Complete All mostra un LUCCHETTO
    # in alto a destra dell'icona (calibrato su FAU_06, colore pulsante
    # invariato). Se rilevato → skip pulito (niente tap a vuoto/loop sterile).
    pin_pass_lock:       str = "pin/pin_radar_lock.png"
    pass_lock_roi:       tuple[int, int, int, int] = (85, 400, 140, 445)

    # Pixel-check riempimento barra stamina (verificato: ratio verde
    # proporzionale alla stamina reale, non serve OCR sui numeri).
    stamina_bar_roi:      tuple[int, int, int, int] = (273, 147, 722, 157)
    soglia_stamina_piena: float = 0.97

    max_complete_all_iter: int = 15   # safety loop principale
    max_saturazione_tap:   int = 30   # safety: 1500/50 = 30, mai serve di più
    max_stato_inatteso:    int = 2    # guardia sicurezza: iter consecutive

    wait_apertura_radar:      float = 0.5
    wait_notifiche:            float = 10.0
    wait_after_complete_all:  float = 4.0   # attesa base animazione ricompense
    wait_after_use_emergency: float = 1.0
    wait_after_close_stamina: float = 1.5
    # 21/07 (bug utente) — su batch grandi l'animazione della maschera ricompensa
    # dura OLTRE wait_after_complete_all: screenshottare a metà animazione fa
    # fallire tutti i riconoscimenti → falso "stato inatteso" → abort prematuro,
    # eventi non tutti completati. Dopo il wait base si POLLA finché compare uno
    # stato noto (completed/stamina/titolo) o scade max_wait_stato_post.
    max_wait_stato_post:  float = 12.0  # finestra di poll aggiuntiva dopo il wait base
    poll_stato_interval:  float = 1.5


class _Esito:
    COMPLETATO       = "completato"
    MAX_ITER         = "max_iter_raggiunto"
    STATO_INATTESO   = "stato_inatteso"
    PASS_NON_ATTIVO  = "pass_non_attivo"
    ERRORE           = "errore"


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class RadarMasterTask(Task):
    """
    Radar Station — Complete All (solo master, Radar Station Pass).
    Idempotente: nessuno stato persistito, il cooldown "Refresh in" è
    interno al gioco e visibile a schermo (fast-exit se già completato).
    """

    def __init__(self, config: RadarMasterConfig | None = None) -> None:
        self._cfg = config or RadarMasterConfig()

    def name(self) -> str:
        return "radar_master"

    def should_run(self, ctx: TaskContext) -> bool:
        if ctx.device is None or ctx.matcher is None:
            return False
        if hasattr(ctx.config, "task_abilitato"):
            if not ctx.config.task_abilitato("radar_master"):
                return False
        return True

    def run(self, ctx: TaskContext) -> TaskResult:
        cfg = self._cfg
        log = ctx.log_msg

        if ctx.navigator is not None:
            if not ctx.navigator.vai_in_home():
                return TaskResult.fail("Navigator non ha raggiunto HOME", step="vai_in_home")

        from shared.debug_buffer import DebugBuffer
        debug = DebugBuffer.for_task("radar_master", getattr(ctx, "instance_name", "_unknown"))

        n_saturazioni = 0
        esito = _Esito.ERRORE

        try:
            log(f"apro Radar Station {cfg.tap_radar_icon}")
            ctx.device.tap(*cfg.tap_radar_icon)
            time.sleep(cfg.wait_apertura_radar)
            log(f"attesa apertura mappa + notifiche ({cfg.wait_notifiche}s)")
            time.sleep(cfg.wait_notifiche)
            shot_open = ctx.device.screenshot()
            debug.snap("00_post_open", shot_open)

            # Safety Pass non attivo: se il pulsante Complete All ha il LUCCHETTO
            # (Radar Station Pass scaduto/assente) → skip, niente loop sterile.
            pass_bloccato = shot_open is not None and ctx.matcher.find_one(
                shot_open, cfg.pin_pass_lock,
                threshold=cfg.soglia_template, zone=cfg.pass_lock_roi).found
            if pass_bloccato:
                log("Complete All BLOCCATO (lucchetto) — Radar Station Pass non "
                    "attivo → skip")
                esito = _Esito.PASS_NON_ATTIVO
                debug.snap("00_pass_lock", shot_open)

            stato_inatteso_consec = 0

            for i in range(1, cfg.max_complete_all_iter + 1) if not pass_bloccato else range(0):
                shot = ctx.device.screenshot()
                if shot is None:
                    log("screenshot None — abort")
                    esito = _Esito.ERRORE
                    break

                if ctx.matcher.find_one(shot, cfg.pin_radar_completed,
                                        threshold=cfg.soglia_template).found:
                    log(f"[ITER {i}] eventi completati — fine")
                    esito = _Esito.COMPLETATO
                    debug.snap("01_completato", shot)
                    break

                log(f"[ITER {i}] tap Complete All {cfg.tap_complete_all}")
                ctx.device.tap(*cfg.tap_complete_all)
                time.sleep(cfg.wait_after_complete_all)

                # POLL post-Complete-All: l'animazione della maschera ricompensa
                # può durare più del wait base (batch grandi). Invece di
                # screenshottare una sola volta (a metà animazione → nessuno
                # stato riconosciuto → falso abort → il task ESCE senza aver
                # completato tutto), pollo finché compare uno stato noto
                # (completed/stamina/titolo) o scade max_wait_stato_post — così
                # RIENTRA nel loop e continua finché non vede "completed".
                shot2, stato = None, None
                _t0 = time.time()
                while True:
                    shot2 = ctx.device.screenshot()
                    if shot2 is None:
                        break
                    if ctx.matcher.find_one(shot2, cfg.pin_radar_completed,
                                            threshold=cfg.soglia_template).found:
                        stato = "completed"; break
                    if ctx.matcher.find_one(shot2, cfg.pin_stamina_mask,
                                            threshold=cfg.soglia_template).found:
                        stato = "stamina"; break
                    if ctx.matcher.find_one(shot2, cfg.pin_radar_title,
                                            threshold=cfg.soglia_template).found:
                        stato = "title"; break
                    if time.time() - _t0 >= cfg.max_wait_stato_post:
                        break
                    log(f"[ITER {i}] stato non ancora stabile (animazione reward?) "
                        f"— attendo {cfg.poll_stato_interval}s")
                    time.sleep(cfg.poll_stato_interval)

                if shot2 is None:
                    log("screenshot None dopo Complete All — abort")
                    esito = _Esito.ERRORE
                    break

                if stato == "completed":
                    log(f"[ITER {i}] eventi completati (post-tap) — fine")
                    esito = _Esito.COMPLETATO
                    debug.snap("01_completato", shot2)
                    break

                if stato == "stamina":
                    log(f"[ITER {i}] maschera STAMINA rilevata — saturo")
                    debug.snap(f"02_stamina_{i}", shot2)
                    self._satura_stamina(ctx, cfg, log)
                    n_saturazioni += 1
                    ctx.device.tap(*cfg.tap_close_stamina)
                    time.sleep(cfg.wait_after_close_stamina)
                    stato_inatteso_consec = 0
                    continue

                # titolo radar visibile → missione completata silenziosamente,
                # ancora sulla Radar Station → ritento (rientra nel loop).
                if stato == "title":
                    log(f"[ITER {i}] missione completata silenziosamente — ritento")
                    stato_inatteso_consec = 0
                    continue

                # stato ancora sconosciuto DOPO il poll (timeout): solo qui è un
                # vero stato inatteso (non un falso positivo da mid-animazione).
                stato_inatteso_consec += 1
                log(f"[ITER {i}] stato radar non riconosciuto dopo poll "
                    f"({stato_inatteso_consec}/{cfg.max_stato_inatteso})")
                debug.snap(f"99_stato_inatteso_{i}", shot2)
                if stato_inatteso_consec >= cfg.max_stato_inatteso:
                    log("stato inatteso ripetuto — abort in sicurezza")
                    esito = _Esito.STATO_INATTESO
                    break
            else:
                if not pass_bloccato:   # loop vuoto per Pass bloccato → non è MAX_ITER
                    log(f"max_complete_all_iter={cfg.max_complete_all_iter} raggiunto")
                    esito = _Esito.MAX_ITER

        except Exception as exc:
            log(f"eccezione: {exc}")
            debug.snap("99_exception", ctx.device.screenshot())
            esito = _Esito.ERRORE
        finally:
            # Chiusura SEMPRE via navigator (mai back/tap grezzo) — vedi
            # docstring modulo sul rischio "Exit game?" osservato in sessione.
            if ctx.navigator is not None:
                ctx.navigator.vai_in_home()

        anomalia = esito in (_Esito.STATO_INATTESO, _Esito.ERRORE, _Esito.MAX_ITER)
        debug.flush(success=(esito != _Esito.ERRORE), force=anomalia, log_fn=log)

        if esito == _Esito.ERRORE:
            return TaskResult.fail("Errore radar master", esito=esito)
        if esito == _Esito.PASS_NON_ATTIVO:
            return TaskResult.skip("Radar Station Pass non attivo (lucchetto) — skip")
        if esito == _Esito.STATO_INATTESO:
            return TaskResult.fail("Stato radar inatteso — abort in sicurezza", esito=esito)
        if esito == _Esito.MAX_ITER:
            return TaskResult.ok("Max iterazioni raggiunto (probabile evento molto carico)",
                                 esito=esito, saturazioni=n_saturazioni)
        return TaskResult.ok("Eventi radar completati", esito=esito, saturazioni=n_saturazioni)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _satura_stamina(self, ctx, cfg, log) -> None:
        """Tap Emergency Recovery (+50) finché il riempimento verde della
        barra raggiunge soglia_stamina_piena. Nessun limite di consumo
        scorte (richiesta esplicita utente)."""
        for j in range(1, cfg.max_saturazione_tap + 1):
            ctx.device.tap(*cfg.tap_use_emergency)
            time.sleep(cfg.wait_after_use_emergency)
            shot = ctx.device.screenshot()
            if shot is None:
                log("[SATURA] screenshot None — stop")
                return
            ratio = self._stamina_fill_ratio(shot, cfg.stamina_bar_roi)
            log(f"[SATURA] tap {j}/{cfg.max_saturazione_tap} → riempimento={ratio:.3f}")
            if ratio >= cfg.soglia_stamina_piena:
                log("[SATURA] barra piena — stop")
                return
        log(f"[SATURA] max_saturazione_tap={cfg.max_saturazione_tap} raggiunto")

    @staticmethod
    def _stamina_fill_ratio(screen, roi: tuple[int, int, int, int]) -> float:
        """Frazione di pixel 'verdi' (barra riempita) nella ROI. Calibrato
        su screenshot reali: ratio proporzionale alla stamina effettiva
        (6.2% stamina → ratio 0.053, 100% → ratio 1.0). Fail-safe 0.0."""
        frame = getattr(screen, "frame", None)
        if frame is None and isinstance(screen, np.ndarray):
            frame = screen
        if frame is None:
            return 0.0
        try:
            x1, y1, x2, y2 = roi
            zona = frame[y1:y2, x1:x2, :3]
            b = zona[:, :, 0].astype(int)
            g = zona[:, :, 1].astype(int)
            r = zona[:, :, 2].astype(int)
            verde = (g > 90) & (g > r) & (g > b)
            return float(verde.sum()) / float(verde.size) if verde.size else 0.0
        except Exception:
            return 0.0
