# ==============================================================================
#  DOOMSDAY ENGINE V6 - tests/tasks/test_boost.py        → C:\doomsday-engine\tests\tasks\test_boost.py
#
#  Test unitari per tasks/boost.py.
#
#  Copertura:
#    - should_run(): config disabilitato, device None, matcher None
#    - _mappa_outcome(): tutti gli _Outcome → TaskResult corretto
#    - _esegui_boost() via run(): scenari principali con FakeDevice
#        * boost già attivo (pin_50_ trovato)
#        * boost 8h attivato
#        * boost 1d attivato (fallback)
#        * nessun boost disponibile
#        * popup non aperto
#        * pin_speed non trovato dopo max swipe
#    - TaskResult properties: success, skipped, data
#
#  FakeDevice / FakeMatcher: implementazioni minimali inline.
#  Nessuna dipendenza da ADB, emulatore o file system.
#  330 test verdi richiesti — questo file aggiunge N test al conteggio.
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from tasks.boost import BoostConfig, BoostTask, _Outcome


# ==============================================================================
# Fake infrastructure
# ==============================================================================

@dataclass
class FakeMatch:
    """Risultato match per FakeMatcher.find()."""
    cx:    int   = 480
    cy:    int   = 270
    score: float = 0.90


class FakeScreenshot:
    """Screenshot fittizio — non contiene dati reali."""
    pass


class FakeDevice:
    """
    Device sincrono/asincrono minimale per i test.
    Registra tutte le chiamate in self.calls.
    """

    def __init__(self, name: str = "FAKE_00") -> None:
        self.name  = name
        self.calls: list[tuple] = []
        self._shot = FakeScreenshot()

    def screenshot(self) -> FakeScreenshot:
        self.calls.append(("screenshot",))
        return self._shot

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", x, y))

    def back(self) -> None:
        self.calls.append(("back",))

    def swipe(self, x1, y1, x2, y2, duration_ms=400) -> None:
        self.calls.append(("swipe", x1, y1, x2, y2))

    def scroll(self, x1, y1, x2, y2, durata_ms=400) -> None:
        self.calls.append(("scroll", x1, y1, x2, y2))

    def keyevent(self, code: str) -> None:
        self.calls.append(("keyevent", code))

    def input_text(self, text: str) -> None:
        self.calls.append(("input_text", text))

    def tap_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "tap")

    def back_count(self) -> int:
        return sum(1 for c in self.calls if c[0] == "back")


class FakeMatcher:
    """
    Template matcher configurabile per i test.
    scores: dict {tmpl_path: float} — ritorna 0.0 se non configurato.
    """

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores: dict[str, float] = scores or {}
        self._finds:  dict[str, FakeMatch | None] = {}

    def set_score(self, tmpl: str, score: float) -> None:
        self._scores[tmpl] = score

    def set_find(self, tmpl: str, match: FakeMatch | None) -> None:
        self._finds[tmpl] = match

    def score(self, shot, tmpl: str) -> float:
        return self._scores.get(tmpl, 0.0)

    def exists(self, shot, tmpl: str, threshold: float = 0.75) -> bool:
        return self.score(shot, tmpl) >= threshold

    def find(self, shot, tmpl: str, threshold: float = 0.75) -> FakeMatch | None:
        if tmpl in self._finds:
            m = self._finds[tmpl]
            if m and m.score >= threshold:
                return m
            return None
        s = self.score(shot, tmpl)
        if s >= threshold:
            return FakeMatch(score=s)
        return None

    def find_one(self, shot, tmpl: str, threshold: float = 0.8, zone=None):
        """API V6: find_one restituisce _MatchResult (found, score, cx, cy)."""
        if tmpl in self._finds:
            m = self._finds[tmpl]
            if m and m.score >= threshold:
                return _MatchResult(found=True, score=m.score, cx=m.cx, cy=m.cy)
        s = self.score(shot, tmpl)
        found = s >= threshold
        return _MatchResult(found=found, score=s, cx=700, cy=300)


# ==============================================================================
# FakeContext builder
# ==============================================================================

class FakeConfig:
    """InstanceConfig minimale per i test."""

    def __init__(self, task_boost_abilitato: bool = True) -> None:
        self._abilitato = task_boost_abilitato

    def task_abilitato(self, nome: str) -> bool:
        if nome == "boost":
            return self._abilitato
        return True


class FakeState:
    def __init__(self, boost_should_run=True):
        from core.state import BoostState
        self.boost = BoostState()
        if not boost_should_run:
            from datetime import datetime, timezone
            self.boost.registra_attivo("8h", riferimento=datetime.now(timezone.utc))


class FakeLogger:
    def __init__(self):
        self.records: list[tuple] = []

    def info(self, task, msg, **kw):
        self.records.append(("INFO", task, msg))

    def error(self, task, msg, **kw):
        self.records.append(("ERROR", task, msg))



def _cfg_zero() -> BoostConfig:
    """Config con tutti i wait azzerati per test veloci."""
    return BoostConfig(
        wait_after_tap=0,
        wait_after_swipe=0,
        wait_after_use=0,
        wait_after_back=0,
        wait_after_speed_tap=0,
    )


def _cfg() -> BoostConfig:
    return BoostConfig()


def _task() -> BoostTask:
    return BoostTask(config=_cfg_zero())


def _make_ctx(
    device:  FakeDevice | None  = None,
    matcher: FakeMatcher | None = None,
    navigator=None,
    task_abilitato: bool = True,
):
    """Costruisce un TaskContext minimale per i test."""
    # Import locale per evitare circular import nei test
    from core.task import TaskContext

    return TaskContext(
        instance_name="FAKE_00",
        config=FakeConfig(task_abilitato),
        state=FakeState(),
        log=FakeLogger(),
        device=device,
        matcher=matcher,
        navigator=navigator,
    )


def run(coro):
    """Esegue una coroutine in modo sincrono."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ==============================================================================
# Helpers — costruzione FakeMatcher per scenari comuni
# ==============================================================================



def _matcher_popup_ok(**extra_scores) -> FakeMatcher:
    """Matcher con manage aperto, speed trovato subito, senza 50_."""
    cfg = _cfg()
    m = FakeMatcher({
        cfg.tmpl_boost:  0.85,
        cfg.tmpl_manage: 0.85,
        cfg.tmpl_speed:  0.80,
        cfg.tmpl_50:     0.10,
        **extra_scores,
    })
    m.set_find(cfg.tmpl_speed, FakeMatch(cx=480, cy=270, score=0.80))
    return m


# ==============================================================================
# Test: should_run()
# ==============================================================================

class TestShouldRun:

    def test_device_none_ritorna_false(self):
        task = _task()
        ctx  = _make_ctx(device=None, matcher=FakeMatcher())
        assert task.should_run(ctx) is False

    def test_matcher_none_ritorna_false(self):
        task   = _task()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=None)
        assert task.should_run(ctx) is False

    def test_task_disabilitato_ritorna_false(self):
        task    = _task()
        device  = FakeDevice()
        matcher = FakeMatcher()
        ctx     = _make_ctx(device=device, matcher=matcher, task_abilitato=False)
        assert task.should_run(ctx) is False

    def test_condizioni_ok_ritorna_true(self):
        task    = _task()
        device  = FakeDevice()
        matcher = FakeMatcher()
        ctx     = _make_ctx(device=device, matcher=matcher, task_abilitato=True)
        assert task.should_run(ctx) is True


# ==============================================================================
# Test: _mappa_outcome()
# ==============================================================================

class TestMappaOutcome:

    def _map(self, outcome: str):
        return BoostTask._mappa_outcome(outcome, log=lambda msg: None)

    def test_attivato_8h_e_ok(self):
        r = self._map(_Outcome.ATTIVATO_8H)
        assert r.success is True
        assert r.skipped is False
        assert "8h" in r.data.get("durata", "")

    def test_attivato_1d_e_ok(self):
        r = self._map(_Outcome.ATTIVATO_1D)
        assert r.success is True
        assert r.skipped is False
        assert "1d" in r.data.get("durata", "")

    def test_gia_attivo_e_ok(self):
        r = self._map(_Outcome.GIA_ATTIVO)
        assert r.success is True
        assert r.skipped is False

    def test_nessun_boost_e_skip(self):
        r = self._map(_Outcome.NESSUN_BOOST)
        assert r.success is True
        assert r.skipped is True

    def test_popup_non_aperto_e_skip(self):
        r = self._map(_Outcome.POPUP_NON_APERTO)
        assert r.success is True
        assert r.skipped is True

    def test_speed_non_trovato_e_skip(self):
        r = self._map(_Outcome.SPEED_NON_TROVATO)
        assert r.success is True
        assert r.skipped is True

    def test_errore_e_fail(self):
        r = self._map(_Outcome.ERRORE)
        assert r.success is False
        assert r.skipped is False

    def test_outcome_sconosciuto_e_fail(self):
        r = self._map("outcome_inesistente")
        assert r.success is False


# ==============================================================================
# Test: TaskResult properties
# ==============================================================================

class TestTaskResult:

    def test_name_ritorna_boost(self):
        assert BoostTask().name() == "boost"

    def test_repr_contiene_boost(self):
        assert "BoostTask" in repr(BoostTask())


# ==============================================================================
# Test: scenario BOOST GIÀ ATTIVO
# ==============================================================================

class TestBoostGiaAttivo:

    def test_ritorna_ok_senza_tap_use(self):
        """Se pin_50_ è visibile dopo lo scroll → ok() senza tap USE."""
        cfg  = _cfg()
        m    = _matcher_popup_ok()
        # Sovrascrive pin_50_ a valore alto
        m.set_score(cfg.tmpl_50, 0.90)

        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=m)
        result = _task().run(ctx)

        assert result.success is True
        assert result.skipped is False
        # Nessun tap USE deve essere avvenuto
        assert not any(c[0] == "tap" and c[1:] == (480, 270) for c in device.calls
                       if len(c) == 3 and c[1] == 480 and c[2] == 270
                       and "use" not in str(c))

    def test_chiude_popup_con_n_back(self):
        cfg  = _cfg()
        m    = _matcher_popup_ok()
        m.set_score(cfg.tmpl_50, 0.90)

        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=m)
        _task().run(ctx)

        assert device.back_count() == cfg.n_back_chiudi


# ==============================================================================
# Test: scenario BOOST 8H ATTIVATO
# ==============================================================================

class TestBoost8h:

    def _matcher_8h(self) -> FakeMatcher:
        cfg = _cfg()
        m   = _matcher_popup_ok()
        m.set_score(cfg.tmpl_speed_8h,  0.85)
        m.set_score(cfg.tmpl_speed_use, 0.85)
        m.set_find(cfg.tmpl_speed_use, FakeMatch(cx=700, cy=300, score=0.85))
        return m

    def test_ritorna_ok_con_durata_8h(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_8h())
        result = _task().run(ctx)

        assert result.success is True
        assert result.skipped is False
        assert result.data.get("durata") == "8h"

    def test_tap_use_eseguito(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_8h())
        _task().run(ctx)

        use_taps = [c for c in device.calls if c[0] == "tap" and c[1] == 700]
        assert len(use_taps) == 1

    def test_back_dopo_use(self):
        """Dopo tap USE viene inviato un solo BACK (non N_BACK_CHIUDI)."""
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_8h())
        _task().run(ctx)

        assert device.back_count() == 1


# ==============================================================================
# Test: scenario BOOST 1D ATTIVATO (fallback)
# ==============================================================================

class TestBoost1d:

    def _matcher_1d(self) -> FakeMatcher:
        cfg = _cfg()
        m   = _matcher_popup_ok()
        # 8h non disponibile, 1d sì
        m.set_score(cfg.tmpl_speed_8h,  0.10)
        m.set_score(cfg.tmpl_speed_1d,  0.85)
        m.set_score(cfg.tmpl_speed_use, 0.85)
        m.set_find(cfg.tmpl_speed_use, FakeMatch(cx=700, cy=300, score=0.85))
        return m

    def test_ritorna_ok_con_durata_1d(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_1d())
        result = _task().run(ctx)

        assert result.success is True
        assert result.data.get("durata") == "1d"

    def test_tap_use_eseguito(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_1d())
        _task().run(ctx)

        use_taps = [c for c in device.calls if c[0] == "tap" and c[1] == 700]
        assert len(use_taps) == 1


# ==============================================================================
# Test: scenario NESSUN BOOST DISPONIBILE
# ==============================================================================

class TestNessunBoost:

    def _matcher_nessun_boost(self) -> FakeMatcher:
        cfg = _cfg()
        m   = _matcher_popup_ok()
        m.set_score(cfg.tmpl_speed_8h,  0.10)
        m.set_score(cfg.tmpl_speed_1d,  0.10)
        m.set_score(cfg.tmpl_speed_use, 0.10)
        return m

    def test_ritorna_skip(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_nessun_boost())
        result = _task().run(ctx)

        assert result.success is True
        assert result.skipped is True

    def test_chiude_popup_con_n_back(self):
        cfg    = _cfg()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_nessun_boost())
        _task().run(ctx)

        assert device.back_count() == cfg.n_back_chiudi


# ==============================================================================
# Test: scenario POPUP NON APERTO
# ==============================================================================

class TestPopupNonAperto:

    def _matcher_popup_ko(self) -> FakeMatcher:
        cfg = _cfg()
        return FakeMatcher({
            cfg.tmpl_boost:  0.85,
            cfg.tmpl_manage: 0.20,   # sotto soglia → popup non rilevato
        })

    def test_ritorna_skip(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_popup_ko())
        result = _task().run(ctx)

        assert result.success is True
        assert result.skipped is True

    def test_chiude_con_n_back(self):
        cfg    = _cfg()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_popup_ko())
        _task().run(ctx)

        assert device.back_count() == cfg.n_back_chiudi

    def test_nessun_tap_speed(self):
        """Se il popup non si apre, non deve avvenire nessun tap aggiuntivo."""
        cfg    = _cfg()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_popup_ko())
        _task().run(ctx)

        # Solo il tap iniziale su TAP_BOOST
        taps = [c for c in device.calls if c[0] == "tap"]
        assert len(taps) == 1
        assert taps[0][1:] == cfg.tap_boost


# ==============================================================================
# Test: scenario SPEED NON TROVATO (scroll esaurito)
# ==============================================================================

class TestSpeedNonTrovato:

    def _matcher_speed_ko(self) -> FakeMatcher:
        cfg = _cfg()
        return FakeMatcher({
            cfg.tmpl_boost:  0.85,
            cfg.tmpl_manage: 0.85,
            cfg.tmpl_speed:  0.20,   # mai trovato
            cfg.tmpl_50:     0.10,
        })

    def test_ritorna_skip(self):
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_speed_ko())
        result = _task().run(ctx)

        assert result.success is True
        assert result.skipped is True

    def test_esegue_max_swipe_swipe(self):
        """
        Deve tentare MAX_SWIPE swipe prima di arrendersi.
        (swipe_n va da 0 a MAX_SWIPE incluso → MAX_SWIPE swipe effettuati)
        """
        cfg    = _cfg()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_speed_ko())
        _task().run(ctx)

        swipes = [c for c in device.calls if c[0] in ("swipe", "scroll")]
        assert len(swipes) == cfg.max_swipe

    def test_chiude_popup_con_n_back(self):
        cfg    = _cfg()
        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=self._matcher_speed_ko())
        _task().run(ctx)

        assert device.back_count() == cfg.n_back_chiudi


# ==============================================================================
# Test: navigator assente (no crash)
# ==============================================================================

class TestNavigatorAssente:

    def test_run_senza_navigator_non_crasha(self):
        """Se navigator è None il task prosegue senza fail strutturale."""
        cfg = _cfg()
        m   = _matcher_popup_ok()
        m.set_score(cfg.tmpl_speed_8h,  0.85)
        m.set_score(cfg.tmpl_speed_use, 0.85)
        m.set_find(cfg.tmpl_speed_use, FakeMatch(cx=700, cy=300, score=0.85))

        device = FakeDevice()
        ctx    = _make_ctx(device=device, matcher=m, navigator=None)
        result = _task().run(ctx)

        # Deve comunque completare (ok o skip, non fail strutturale)
        assert result is not None
        assert isinstance(result.success, bool)


# ==============================================================================
# Test: BoostConfig defaults
# ==============================================================================

class TestBoostConfig:

    def test_default_tap_boost(self):
        assert BoostConfig().tap_boost == (142, 47)

    def test_default_n_back_chiudi(self):
        assert BoostConfig().n_back_chiudi == 3

    def test_default_max_swipe(self):
        assert BoostConfig().max_swipe == 8

    def test_default_soglie_positive(self):
        cfg = BoostConfig()
        for attr in ("soglia_boost", "soglia_manage", "soglia_speed",
                     "soglia_50", "soglia_8h", "soglia_1d", "soglia_use"):
            assert 0 < getattr(cfg, attr) < 1, f"{attr} fuori range"

    def test_template_paths_contengono_pin(self):
        cfg = BoostConfig()
        for attr in ("tmpl_boost", "tmpl_manage", "tmpl_speed",
                     "tmpl_50", "tmpl_speed_8h", "tmpl_speed_1d", "tmpl_speed_use"):
            assert "pin" in getattr(cfg, attr), f"{attr} non contiene 'pin'"
