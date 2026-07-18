"""
tests/unit/test_ds_event_window_r06.py — R-06 (revisione 07/2026)

La finestra evento District Showdown era implementata DUE volte (task live +
predictor) con rischio drift: il predictor hardcodava "lunedì sempre fuori"
ignorando `ds_end_hour`. Ora c'è un'unica funzione condivisa
`shared.task_scheduling.is_in_ds_event_window`; task e predictor la chiamano.

Questi test verificano:
  1. la funzione condivisa replica la vecchia logica (Ven→Lun default);
  2. task e predictor restano perfettamente coerenti (predictor = NOT task-window);
  3. il bug latente (ds_end_hour>0) è ora gestito uniformemente.
"""

from datetime import datetime, timezone

from shared.task_scheduling import is_in_ds_event_window


def _utc(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


# --- 1. Comportamento default (Ven 00:00 → Lun 00:00) --------------------------
# 2026-07-17 = venerdì, 07-18 sab, 07-19 dom, 07-20 lun, 07-14 mar.

def test_venerdi_dentro():
    assert is_in_ds_event_window(_utc(2026, 7, 17, 0)) is True
    assert is_in_ds_event_window(_utc(2026, 7, 17, 23)) is True


def test_sabato_domenica_dentro():
    assert is_in_ds_event_window(_utc(2026, 7, 18, 12)) is True   # sab
    assert is_in_ds_event_window(_utc(2026, 7, 19, 12)) is True   # dom


def test_lunedi_fuori_default():
    # ds_end_hour=0 → h<0 sempre False → lunedì fuori
    assert is_in_ds_event_window(_utc(2026, 7, 20, 0)) is False
    assert is_in_ds_event_window(_utc(2026, 7, 20, 12)) is False


def test_infrasettimanale_fuori():
    assert is_in_ds_event_window(_utc(2026, 7, 14, 12)) is False  # mar
    assert is_in_ds_event_window(_utc(2026, 7, 15, 12)) is False  # mer
    assert is_in_ds_event_window(_utc(2026, 7, 16, 12)) is False  # gio


# --- 2. Coerenza task ↔ predictor su tutta la settimana ------------------------

def _task_window_legacy(now):
    """Vecchia logica del TASK (pre-R-06), per confronto."""
    wd, h = now.weekday(), now.hour
    if wd == 0:            # lun, ds_end_hour=0
        return h < 0
    if wd == 4:            # ven, ds_start_hour=0
        return h >= 0
    if wd in (5, 6):
        return True
    return False


def _predictor_will_skip_legacy(now):
    """Vecchia logica del PREDICTOR (pre-R-06)."""
    wd = now.weekday()
    if wd == 0:
        return True
    if wd == 4:
        return False
    if wd in (5, 6):
        return False
    return True


def test_shared_equivale_al_task_legacy():
    for day in range(14, 21):          # una settimana intera
        for h in range(24):
            now = _utc(2026, 7, day, h)
            assert is_in_ds_event_window(now) == _task_window_legacy(now), (day, h)


def test_predictor_e_negazione_della_finestra():
    # Il predictor (post-R-06) fa `not is_in_ds_event_window` → deve coincidere
    # con la vecchia logica predittore su tutti gli slot.
    for day in range(14, 21):
        for h in range(24):
            now = _utc(2026, 7, day, h)
            assert (not is_in_ds_event_window(now)) == _predictor_will_skip_legacy(now), (day, h)


# --- 3. Bug latente ds_end_hour>0 ora gestito ---------------------------------

def test_ds_end_hour_positivo_lunedi_parziale():
    # Se l'evento finisse lun 04:00 UTC, il lunedì mattina presto è DENTRO.
    assert is_in_ds_event_window(_utc(2026, 7, 20, 3), ds_end_hour=4) is True
    assert is_in_ds_event_window(_utc(2026, 7, 20, 5), ds_end_hour=4) is False


def test_ds_start_hour_positivo_venerdi_parziale():
    # Se l'evento iniziasse ven 12:00 UTC, il venerdì mattina è FUORI.
    assert is_in_ds_event_window(_utc(2026, 7, 17, 9), ds_start_hour=12) is False
    assert is_in_ds_event_window(_utc(2026, 7, 17, 13), ds_start_hour=12) is True
