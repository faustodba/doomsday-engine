# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_alleanza.py  → C:\doomsday-engine\tests\tasks\test_alleanza.py
#
#  Test unitari per tasks/alleanza.py.
#
#  Scenari coperti:
#    - should_run(): device None, config disabilitato
#    - _rivendica_presente(): presente, assente, fail-safe
#    - _roi_hash(): hash diverso se ROI cambia
#    - _mappa_esito(): tutti gli esiti → TaskResult corretto
#    - run():
#        * flusso completo — rivendica trovato e stop pixel check
#        * stop per no-change streak
#        * stop per max_rivendica raggiunto
#        * back×3 sempre eseguiti
#        * raccogli tutto sempre eseguito
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from tasks.alleanza import AlleanzaConfig, AlleanzaTask, _Esito


# ==============================================================================
# Fake infrastructure
# ==============================================================================

class FakeScreenshot:
    """Screenshot con array numpy configurabile per i test pixel check."""

    def __init__(self, array: np.ndarray | None = None):
        # Default: immagine 540×960 nera (pulsante assente)
        self.array = array if array is not None else np.zeros((540, 960, 3), dtype=np.uint8)

    @classmethod
    def con_pulsante(cls, cfg: AlleanzaConfig) -> "FakeScreenshot":
        """Screenshot con area Rivendica luminosa/satura (pulsante presente)."""
        arr = np.zeros((540, 960, 3), dtype=np.uint8)
        x, y = cfg.coord_rivendica
        x1 = max(0, x - cfg.riv_roi_half_w)
        y1 = max(0, y - cfg.riv_roi_half_h)
        x2 = min(960, x + cfg.riv_roi_half_w)
        y2 = min(540, y + cfg.riv_roi_half_h)
        # BGR: pixel luminosi e saturi (simula pulsante colorato)
        arr[y1:y2, x1:x2] = [50, 150, 220]   # B=50 G=150 R=220
        return cls(arr)

    @classmethod
    def senza_pulsante(cls) -> "FakeScreenshot":
        """Screenshot con area Rivendica scura (pulsante assente)."""
        return cls(np.zeros((540, 960, 3), dtype=np.uint8))


class FakeDevice:
    """Device asincrono con sequenza di screenshot configurabile."""

    def __init__(self, name: str = "FAKE_00") -> None:
        self.name  = name
        self.calls: list[tuple] = []
        self._shots: list[FakeScreenshot] = []
        self._shot_idx = 0
        self._default_shot = FakeScreenshot()

    def set_shots(self, shots: list[FakeScreenshot]) -> None:
        """Imposta la sequenza di screenshot da restituire."""
        self._shots    = shots
        self._shot_idx = 0

    def set_default_shot(self, shot: FakeScreenshot) -> None:
        self._default_shot = shot

    def screenshot(self) -> FakeScreenshot:
        self.calls.append(("screenshot",))
        if self._shot_idx < len(self._shots):
            s = self._shots[self._shot_idx]
            self._shot_idx += 1
            return s
        return self._default_shot

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def back(self) -> None:
        self.calls.append(("back",))

    def swipe(self, x1, y1, x2, y2, duration_ms=400) -> None:
        self.calls.append(("swipe", x1, y1, x2, y2))

    def tap_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "tap")

    def back_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "back")

    def taps_at(self, x: int, y: int) -> int:
        return sum(1 for c in self.calls if c[0] == "tap" and c[1] == x and c[2] == y)


# ==============================================================================
# Helpers
# ==============================================================================

class FakeConfig:
    def __init__(self, abilitato: bool = True):
        self._abilitato = abilitato

    def task_abilitato(self, nome: str) -> bool:
        return self._abilitato if nome == "alleanza" else True


class FakeLogger:
    def info(self, task, msg, **kw): pass
    def error(self, task, msg, **kw): pass


def _make_ctx(device=None, navigator=None, abilitato=True):
    from core.task import TaskContext
    return TaskContext(
        instance_name="FAKE_00",
        config=FakeConfig(abilitato),
        state=object(),
        log=FakeLogger(),
        device=device,
        matcher=None,
        navigator=navigator,
    )




def _cfg() -> AlleanzaConfig:
    return AlleanzaConfig()


def _task() -> AlleanzaTask:
    return _task()


# ==============================================================================
# Test: should_run()
# ==============================================================================

def _cfg_zero() -> AlleanzaConfig:
    """Config con tutti i wait azzerati per test veloci."""
    return AlleanzaConfig(
        wait_open_alleanza=0,
        wait_open_dono=0,
        wait_tab=0,
        wait_rivendica=0,
        wait_raccogli=0,
        wait_back=0,
        wait_back_last=0,
    )


def _task():
    return AlleanzaTask(config=_cfg_zero())



class TestShouldRun:

    def test_device_none_false(self):
        ctx = _make_ctx(device=None)
        assert AlleanzaTask().should_run(ctx) is False

    def test_disabilitato_false(self):
        ctx = _make_ctx(device=FakeDevice(), abilitato=False)
        assert AlleanzaTask().should_run(ctx) is False

    def test_ok_true(self):
        ctx = _make_ctx(device=FakeDevice(), abilitato=True)
        assert AlleanzaTask().should_run(ctx) is True


# ==============================================================================
# Test: _rivendica_presente()
# ==============================================================================

class TestRivendicaPresente:

    def test_pulsante_presente(self):
        cfg  = _cfg()
        shot = FakeScreenshot.con_pulsante(cfg)
        assert _task()._rivendica_presente(shot, cfg) is True

    def test_pulsante_assente(self):
        cfg  = _cfg()
        shot = FakeScreenshot.senza_pulsante()
        assert _task()._rivendica_presente(shot, cfg) is False

    def test_failsafe_array_none(self):
        """Se array non disponibile → True (fail-safe)."""
        cfg  = _cfg()

        class ShotSenzaArray:
            @property
            def array(self):
                raise AttributeError("no array")

        assert _task()._rivendica_presente(ShotSenzaArray(), cfg) is True


# ==============================================================================
# Test: _roi_hash()
# ==============================================================================

class TestRoiHash:

    def test_hash_diverso_se_roi_diversa(self):
        cfg   = _cfg()
        shot1 = FakeScreenshot.con_pulsante(cfg)
        shot2 = FakeScreenshot.senza_pulsante()
        h1 = _task()._roi_hash(shot1, cfg)
        h2 = _task()._roi_hash(shot2, cfg)
        assert h1 != h2

    def test_hash_uguale_stesso_shot(self):
        cfg  = _cfg()
        shot = FakeScreenshot.con_pulsante(cfg)
        h1   = _task()._roi_hash(shot, cfg)
        h2   = _task()._roi_hash(shot, cfg)
        assert h1 == h2

    def test_hash_stringa_vuota_su_errore(self):
        cfg = _cfg()

        class ShotRotto:
            @property
            def array(self):
                raise RuntimeError("errore")

        assert _task()._roi_hash(ShotRotto(), cfg) == ""


# ==============================================================================
# Test: _mappa_esito()
# ==============================================================================

class TestMappaEsito:

    def _map(self, esito, rivendiche=5, raccolti=True):
        return AlleanzaTask._mappa_esito(esito, rivendiche, raccolti,
                                         log=lambda m: None)

    def test_completato_ok(self):
        r = self._map(_Esito.COMPLETATO, rivendiche=7, raccolti=True)
        assert r.success is True
        assert r.skipped is False
        assert r.data["rivendiche"] == 7
        assert r.data["raccolti"] is True

    def test_completato_zero_rivendiche_ok(self):
        """Zero rivendiche non è un errore — pulsante già sparito."""
        r = self._map(_Esito.COMPLETATO, rivendiche=0)
        assert r.success is True

    def test_non_in_home_skip(self):
        r = self._map(_Esito.NON_IN_HOME)
        assert r.success is True
        assert r.skipped is True

    def test_errore_fail(self):
        r = self._map(_Esito.ERRORE)
        assert r.success is False


# ==============================================================================
# Test: run() — flusso completo
# ==============================================================================

class TestFlussoCompleto:
    """
    Sequenza screenshot:
      shot0: pre-rivendica (pulsante presente)
      shot1: post-rivendica tap 1 (pulsante assente → stop)
      shot_default: senza pulsante (per tutte le successive)
    """

    def _device_un_rivendica(self) -> FakeDevice:
        cfg    = _cfg()
        device = FakeDevice()
        device.set_shots([
            FakeScreenshot.con_pulsante(cfg),   # check before tap 1
            FakeScreenshot.senza_pulsante(),    # check after tap 1 → stop
        ])
        device.set_default_shot(FakeScreenshot.senza_pulsante())
        return device

    def test_ritorna_ok(self):
        device = self._device_un_rivendica()
        ctx    = _make_ctx(device=device)
        result = _task().run(ctx)
        assert result.success is True
        assert result.skipped is False

    def test_un_rivendica_eseguito(self):
        cfg    = _cfg()
        device = self._device_un_rivendica()
        ctx    = _make_ctx(device=device)
        _task().run(ctx)
        assert device.taps_at(*cfg.coord_rivendica) == 1

    def test_raccogli_tutto_eseguito(self):
        cfg    = _cfg()
        device = self._device_un_rivendica()
        ctx    = _make_ctx(device=device)
        _task().run(ctx)
        assert device.taps_at(*cfg.coord_raccogli) == 1

    def test_back_tre_volte(self):
        cfg    = _cfg()
        device = self._device_un_rivendica()
        ctx    = _make_ctx(device=device)
        _task().run(ctx)
        assert device.back_count() == cfg.n_back_chiudi

    def test_tap_alleanza_e_dono(self):
        cfg    = _cfg()
        device = self._device_un_rivendica()
        ctx    = _make_ctx(device=device)
        _task().run(ctx)
        assert device.taps_at(*cfg.coord_alleanza) == 1
        assert device.taps_at(*cfg.coord_dono) == 1


# ==============================================================================
# Test: run() — stop per no-change streak
# ==============================================================================

class TestNoChangeStreak:

    def test_stop_dopo_streak(self):
        """
        Pulsante sempre presente ma ROI non cambia mai
        → stop dopo no_change_limit streak.
        """
        cfg    = _cfg()
        # Tutti gli screenshot identici (stesso array → stesso hash)
        device = FakeDevice()
        device.set_default_shot(FakeScreenshot.con_pulsante(cfg))

        ctx    = _make_ctx(device=device)
        result = _task().run(ctx)

        assert result.success is True
        # Con no_change_limit=2: stop dopo 2 streak consecutivi
        # tap rivendica: al massimo no_change_limit + 1
        assert device.taps_at(*cfg.coord_rivendica) <= cfg.no_change_limit + 1


# ==============================================================================
# Test: run() — stop per max_rivendica
# ==============================================================================

class TestMaxRivendica:

    def test_non_supera_max(self):
        """
        Pulsante sempre presente e ROI cambia sempre (hash diverso)
        → stop a max_rivendica.
        """
        cfg = AlleanzaConfig(max_rivendica=3, no_change_limit=99,
                            wait_open_alleanza=0, wait_open_dono=0, wait_tab=0,
                            wait_rivendica=0, wait_raccogli=0, wait_back=0, wait_back_last=0)

        # Sequenza: alternanza pulsante/assente per hash diverso ma present=True
        shots = []
        for i in range(cfg.max_rivendica * 2 + 4):
            # Alterna array per hash diverso mantenendo pulsante presente
            arr = np.zeros((540, 960, 3), dtype=np.uint8)
            x, y = cfg.coord_rivendica
            x1 = max(0, x - cfg.riv_roi_half_w)
            y1 = max(0, y - cfg.riv_roi_half_h)
            x2 = min(960, x + cfg.riv_roi_half_w)
            y2 = min(540, y + cfg.riv_roi_half_h)
            # Valore leggermente diverso a ogni shot per hash unico
            arr[y1:y2, x1:x2] = [50, 150, 200 + (i % 10)]
            shots.append(FakeScreenshot(arr))

        device = FakeDevice()
        device.set_shots(shots)
        device.set_default_shot(FakeScreenshot.con_pulsante(cfg))

        ctx    = _make_ctx(device=device)
        result = AlleanzaTask(config=cfg).run(ctx)

        assert result.success is True
        assert device.taps_at(*cfg.coord_rivendica) == cfg.max_rivendica


# ==============================================================================
# Test: AlleanzaConfig defaults
# ==============================================================================

class TestAlleanzaConfig:

    def test_name(self):
        assert AlleanzaTask().name() == "alleanza"

    def test_coord_plausibili(self):
        cfg = AlleanzaConfig()
        for attr in ("coord_alleanza", "coord_dono", "coord_tab_negozio",
                     "coord_tab_attivita", "coord_rivendica", "coord_raccogli"):
            x, y = getattr(cfg, attr)
            assert 0 <= x <= 960, f"{attr}.x fuori range: {x}"
            assert 0 <= y <= 540, f"{attr}.y fuori range: {y}"

    def test_max_rivendica_positivo(self):
        assert AlleanzaConfig().max_rivendica > 0

    def test_n_back_chiudi(self):
        assert AlleanzaConfig().n_back_chiudi == 3
