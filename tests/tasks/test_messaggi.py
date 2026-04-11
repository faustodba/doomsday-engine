# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_messaggi.py  → C:\doomsday-engine\tests\tasks\test_messaggi.py
#
#  Test unitari per tasks/messaggi.py.
#
#  Scenari coperti:
#    - should_run(): device None, matcher None, config disabilitato
#    - _mappa_esito(): tutti gli esiti → TaskResult corretto
#    - _verifica_pin(): trovato al primo tentativo, trovato al retry, non trovato
#    - _gestisci_tab(): tab attivo + read visibile, tab attivo + no read, tab anomalo
#    - run():
#        * flusso completo OK (alliance + system entrambi con messaggi)
#        * flusso OK senza messaggi (read non visibile)
#        * schermata non aperta → skip
#        * alliance anomala, system OK
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tasks.messaggi import MessaggiConfig, MessaggiTask, _Esito


# ==============================================================================
# Fake infrastructure
# ==============================================================================

@dataclass
class FakeMatch:
    cx:    int   = 480
    cy:    int   = 270
    score: float = 0.90
    found: bool  = True


class FakeScreenshot:
    pass


class FakeDevice:
    def __init__(self, name: str = "FAKE_00") -> None:
        self.name  = name
        self.calls: list[tuple] = []

    def screenshot(self):
        self.calls.append(("screenshot",))
        return FakeScreenshot()

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


class FakeMatcher:
    """
    Matcher configurabile per score.
    Supporta score diversi per chiamata successiva (lista per template).
    """
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores: dict[str, float]       = scores or {}
        self._seq:    dict[str, list[float]] = {}   # score sequenziali per retry test

    def set_score(self, tmpl: str, score: float) -> None:
        self._scores[tmpl] = score

    def set_sequence(self, tmpl: str, scores: list[float]) -> None:
        """Imposta una sequenza di score restituiti in ordine nelle chiamate successive."""
        self._seq[tmpl] = list(scores)

    def score(self, shot, tmpl: str, zone=None) -> float:
        if tmpl in self._seq and self._seq[tmpl]:
            return self._seq[tmpl].pop(0)
        return self._scores.get(tmpl, 0.0)

    def exists(self, shot, tmpl: str, threshold: float = 0.75, zone=None) -> bool:
        return self.score(shot, tmpl) >= threshold

    def find_one(self, shot, tmpl: str, threshold: float = 0.75, zone=None) -> FakeMatch:
        s = self.score(shot, tmpl)
        return FakeMatch(score=s, found=s >= threshold)


# ==============================================================================
# Helpers
# ==============================================================================

class FakeConfig:
    def __init__(self, abilitato: bool = True):
        self._abilitato = abilitato

    def task_abilitato(self, nome: str) -> bool:
        return self._abilitato if nome == "messaggi" else True


class FakeLogger:
    def __init__(self):
        self.records: list[str] = []

    def info(self, task, msg, **kw):
        self.records.append(msg)

    def error(self, task, msg, **kw):
        self.records.append(f"ERROR: {msg}")


def _make_ctx(device=None, matcher=None, navigator=None, abilitato=True):
    from core.task import TaskContext
    return TaskContext(
        instance_name="FAKE_00",
        config=FakeConfig(abilitato),
        state=object(),
        log=FakeLogger(),
        device=device,
        matcher=matcher,
        navigator=navigator,
    )




def _cfg() -> MessaggiConfig:
    return MessaggiConfig()


def _matcher_tutto_ok() -> FakeMatcher:
    """Matcher con schermata aperta, entrambi i tab attivi, read visibile."""
    cfg = _cfg()
    return FakeMatcher({
        cfg.tmpl_alliance: 0.95,
        cfg.tmpl_system:   0.95,
        cfg.tmpl_read:     0.95,
    })


def _matcher_no_read() -> FakeMatcher:
    """Matcher con tab attivi ma nessun messaggio (read non visibile)."""
    cfg = _cfg()
    return FakeMatcher({
        cfg.tmpl_alliance: 0.95,
        cfg.tmpl_system:   0.95,
        cfg.tmpl_read:     0.10,
    })


# ==============================================================================
# Test: should_run()
# ==============================================================================

def _cfg_zero() -> MessaggiConfig:
    """Config con tutti i wait azzerati per test veloci."""
    return MessaggiConfig(
        wait_open=0,
        wait_tab=0,
        wait_read=0,
        wait_close=0,
        wait_back=0,
        retry_sleep=0,
        retry_sleep_open=0,
        retry_sleep_read=0,
    )


def _task():
    return MessaggiTask(config=_cfg_zero())



class TestShouldRun:

    def test_device_none_false(self):
        ctx = _make_ctx(device=None, matcher=FakeMatcher())
        assert MessaggiTask().should_run(ctx) is False

    def test_matcher_none_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=None)
        assert MessaggiTask().should_run(ctx) is False

    def test_disabilitato_false(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=False)
        assert MessaggiTask().should_run(ctx) is False

    def test_ok_true(self):
        ctx = _make_ctx(device=FakeDevice(), matcher=FakeMatcher(), abilitato=True)
        assert MessaggiTask().should_run(ctx) is True


# ==============================================================================
# Test: _mappa_esito()
# ==============================================================================

class TestMappaEsito:

    def _map(self, esito, alliance=True, system=True):
        return MessaggiTask._mappa_esito(esito, alliance, system, log=lambda m: None)

    def test_completato_ok(self):
        r = self._map(_Esito.COMPLETATO, alliance=True, system=True)
        assert r.success is True
        assert r.skipped is False
        assert r.data["alliance"] is True
        assert r.data["system"] is True

    def test_completato_con_anomalie_tab(self):
        """Anche se un tab è anomalo il task è completato (non fail)."""
        r = self._map(_Esito.COMPLETATO, alliance=False, system=True)
        assert r.success is True
        assert r.data["alliance"] is False

    def test_schermata_non_aperta_skip(self):
        r = self._map(_Esito.SCHERMATA_NON_APERTA)
        assert r.success is True
        assert r.skipped is True

    def test_errore_fail(self):
        r = self._map(_Esito.ERRORE)
        assert r.success is False


# ==============================================================================
# Test: _verifica_pin()
# ==============================================================================

class TestVerificaPin:

    def _task(self) -> MessaggiTask:
        return _task()

    def test_trovato_primo_tentativo(self):
        cfg  = _cfg()
        m    = FakeMatcher({cfg.tmpl_alliance: 0.95})
        device = FakeDevice()
        ok = self._task()._verifica_pin(
            device, m, cfg.tmpl_alliance, cfg.soglia_alliance,
            cfg.roi_alliance, retry=0, retry_sleep=0, log=lambda x: None, label="TEST"
        )
        assert ok is True

    def test_non_trovato(self):
        cfg  = _cfg()
        m    = FakeMatcher({cfg.tmpl_alliance: 0.10})
        device = FakeDevice()
        ok = self._task()._verifica_pin(
            device, m, cfg.tmpl_alliance, cfg.soglia_alliance,
            cfg.roi_alliance, retry=0, retry_sleep=0, log=lambda x: None, label="TEST"
        )
        assert ok is False

    def test_trovato_al_retry(self):
        """Prima chiamata fallisce, seconda riesce."""
        cfg = _cfg()
        m   = FakeMatcher()
        m.set_sequence(cfg.tmpl_alliance, [0.10, 0.95])   # fail → ok
        device = FakeDevice()
        ok = self._task()._verifica_pin(
            device, m, cfg.tmpl_alliance, cfg.soglia_alliance,
            cfg.roi_alliance, retry=1, retry_sleep=0, log=lambda x: None, label="TEST"
        )
        assert ok is True
        # Due screenshot: uno per il fail, uno per il retry
        assert device.calls.count(("screenshot",)) == 2

    def test_non_trovato_dopo_tutti_retry(self):
        cfg = _cfg()
        m   = FakeMatcher({cfg.tmpl_alliance: 0.10})
        device = FakeDevice()
        ok = self._task()._verifica_pin(
            device, m, cfg.tmpl_alliance, cfg.soglia_alliance,
            cfg.roi_alliance, retry=2, retry_sleep=0, log=lambda x: None, label="TEST"
        )
        assert ok is False
        assert device.calls.count(("screenshot",)) == 3   # tentativo 0,1,2


# ==============================================================================
# Test: run() — flusso completo con messaggi
# ==============================================================================

class TestFlussoCompleto:

    def test_ritorna_ok(self):
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = _task().run(ctx)
        assert result.success is True
        assert result.skipped is False

    def test_alliance_e_system_ok(self):
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = _task().run(ctx)
        assert result.data["alliance"] is True
        assert result.data["system"] is True

    def test_tap_read_eseguito_due_volte(self):
        """Read and claim all deve essere tappato una volta per tab."""
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.taps_at(*cfg.tap_read_all) == 2

    def test_back_chiusura_eseguiti(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.back_count() == cfg.n_back_close

    def test_tap_close_eseguito(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_tutto_ok()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.taps_at(*cfg.tap_close) == 1


# ==============================================================================
# Test: run() — nessun messaggio (read non visibile)
# ==============================================================================

class TestNessunMessaggio:

    def test_ritorna_ok_senza_read(self):
        device  = FakeDevice()
        matcher = _matcher_no_read()
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = _task().run(ctx)
        assert result.success is True
        assert result.skipped is False

    def test_read_non_tappato(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = _matcher_no_read()
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.taps_at(*cfg.tap_read_all) == 0


# ==============================================================================
# Test: run() — schermata non aperta
# ==============================================================================

class TestSchermataNonAperta:

    def test_ritorna_skip(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = FakeMatcher({cfg.tmpl_alliance: 0.10})   # schermata non rilevata
        ctx     = _make_ctx(device=device, matcher=matcher)
        result = _task().run(ctx)
        assert result.success is True
        assert result.skipped is True

    def test_back_eseguito(self):
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = FakeMatcher({cfg.tmpl_alliance: 0.10})
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.back_count() >= 1

    def test_tab_non_tappati(self):
        """Se la schermata non si apre i tab non devono essere tappati."""
        cfg     = _cfg()
        device  = FakeDevice()
        matcher = FakeMatcher({cfg.tmpl_alliance: 0.10})
        ctx     = _make_ctx(device=device, matcher=matcher)
        _task().run(ctx)
        assert device.taps_at(*cfg.tap_tab_alliance) == 0
        assert device.taps_at(*cfg.tap_tab_system) == 0


# ==============================================================================
# Test: run() — alliance anomala, system OK
# ==============================================================================

class TestAllianceAnomala:

    def test_system_completato_nonostante_alliance_anomala(self):
        """Alliance anomala non blocca il task — system viene comunque eseguito."""
        cfg     = _cfg()
        device  = FakeDevice()
        # alliance sempre sotto soglia dopo PRE-OPEN (che usa alliance per open check)
        # PRE-OPEN: prima chiamata OK (schermata aperta)
        # PRE-ALLIANCE: seconda chiamata KO (tab non attivo)
        m = FakeMatcher()
        m.set_sequence(cfg.tmpl_alliance, [0.95, 0.10, 0.10, 0.10])  # open OK, tab fail×3
        m.set_score(cfg.tmpl_system, 0.95)
        m.set_score(cfg.tmpl_read, 0.95)
        ctx    = _make_ctx(device=device, matcher=m)
        result = _task().run(ctx)

        assert result.success is True
        assert result.data["alliance"] is False
        assert result.data["system"] is True


# ==============================================================================
# Test: MessaggiConfig defaults
# ==============================================================================

class TestMessaggiConfig:

    def test_name(self):
        assert MessaggiTask().name() == "messaggi"

    def test_soglie_in_range(self):
        cfg = MessaggiConfig()
        for attr in ("soglia_alliance", "soglia_system", "soglia_read"):
            val = getattr(cfg, attr)
            assert 0 < val < 1, f"{attr} fuori range: {val}"

    def test_coordinate_plausibili(self):
        cfg = MessaggiConfig()
        for coord_attr in ("tap_icona_messaggi", "tap_tab_alliance",
                           "tap_tab_system", "tap_read_all", "tap_close"):
            x, y = getattr(cfg, coord_attr)
            assert 0 <= x <= 960, f"{coord_attr}.x fuori range: {x}"
            assert 0 <= y <= 540, f"{coord_attr}.y fuori range: {y}"

    def test_tmpl_paths_pin(self):
        cfg = MessaggiConfig()
        for attr in ("tmpl_alliance", "tmpl_system", "tmpl_read"):
            assert getattr(cfg, attr).startswith("pin/"), f"{attr} non inizia con pin/"
