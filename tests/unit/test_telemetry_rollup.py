# ==============================================================================
#  tests/unit/test_telemetry_rollup.py — Issue #53 Step 4
# ==============================================================================

import json
import time
import pytest

from core import telemetry
from core.telemetry import (
    TaskTelemetry, record,
    compute_rollup, save_rollup, load_rollup,
    compute_and_save_rollup, cleanup_old_rollups,
    OUTCOME_OK, OUTCOME_SKIP, OUTCOME_FAIL, OUTCOME_ABORT,
    ANOM_OCR_FAIL, ANOM_ADB_UNHEALTHY,
)


@pytest.fixture
def telemetry_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DOOMSDAY_ROOT", str(tmp_path))
    yield tmp_path


def _make_event(task, instance, outcome, dur=0.5,
                anomalies=None, output=None, success=None):
    e = TaskTelemetry.start(task=task, instance=instance, cycle=1)
    # forza ts_end manualmente per controllare durata
    e.ts_end     = e.ts_start
    e.duration_s = float(dur)
    if outcome == OUTCOME_OK:
        e.success = True
    elif outcome == OUTCOME_SKIP:
        e.success = True
    else:
        e.success = False if success is None else success
    e.outcome   = outcome
    e.output    = dict(output or {})
    e.anomalies = list(anomalies or [])
    return e


# ==============================================================================
# 1. Rollup vuoto
# ==============================================================================

def test_rollup_empty(telemetry_root):
    r = compute_rollup("2026-04-27")
    assert r["date"] == "2026-04-27"
    assert r["totals"]["events"] == 0
    assert r["per_task"] == {}
    assert r["per_instance"] == {}


# ==============================================================================
# 2. Rollup base — totali corretti
# ==============================================================================

def test_rollup_totals(telemetry_root):
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK))
    record(_make_event("raccolta", "FAU_01", OUTCOME_OK))
    record(_make_event("rifornimento", "FAU_00", OUTCOME_FAIL))
    record(_make_event("arena", "FAU_02", OUTCOME_ABORT,
                        anomalies=[ANOM_ADB_UNHEALTHY]))

    r = compute_rollup()
    assert r["totals"]["events"] == 4
    assert r["totals"]["ok"]     == 2
    assert r["totals"]["fail"]   == 1
    assert r["totals"]["abort"]  == 1
    assert r["anomalies_global"][ANOM_ADB_UNHEALTHY] == 1


# ==============================================================================
# 3. per_task — ok_pct + durations
# ==============================================================================

def test_rollup_per_task_ok_pct(telemetry_root):
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK,   dur=10.0))
    record(_make_event("raccolta", "FAU_01", OUTCOME_OK,   dur=20.0))
    record(_make_event("raccolta", "FAU_02", OUTCOME_SKIP, dur=2.0))
    record(_make_event("raccolta", "FAU_03", OUTCOME_FAIL, dur=5.0))

    r = compute_rollup()
    t = r["per_task"]["raccolta"]
    assert t["exec"]   == 4
    assert t["ok"]     == 2
    assert t["skip"]   == 1
    assert t["fail"]   == 1
    assert t["ok_pct"] == 75.0   # (2 ok + 1 skip) / 4
    assert t["duration_avg_s"] > 0
    assert t["duration_p50"]   > 0
    assert t["duration_p95"]   > 0
    assert t["duration_max_s"] == 20.0


# ==============================================================================
# 4. per_task — anomalies + output_aggregates
# ==============================================================================

def test_rollup_per_task_anomalies_and_output(telemetry_root):
    record(_make_event("rifornimento", "FAU_00", OUTCOME_OK,
                        output={"spedizioni": 4, "mode": "mappa", "saturo": False},
                        anomalies=[ANOM_OCR_FAIL]))
    record(_make_event("rifornimento", "FAU_01", OUTCOME_OK,
                        output={"spedizioni": 2, "mode": "mappa", "saturo": True},
                        anomalies=[ANOM_OCR_FAIL]))
    record(_make_event("rifornimento", "FAU_02", OUTCOME_OK,
                        output={"spedizioni": 1, "mode": "membri"}))

    r = compute_rollup()
    t = r["per_task"]["rifornimento"]
    assert t["anomalies"][ANOM_OCR_FAIL] == 2

    out = t["output_aggregates"]
    assert out["spedizioni_sum"]    == 7
    assert out["spedizioni_max"]    == 4
    assert out["mode__mappa"]       == 2
    assert out["mode__membri"]      == 1
    assert out["saturo_true"]       == 1
    assert out["saturo_false"]      == 1


# ==============================================================================
# 5. per_instance — breakdown
# ==============================================================================

def test_rollup_per_instance(telemetry_root):
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK))
    record(_make_event("rifornimento", "FAU_00", OUTCOME_OK))
    record(_make_event("raccolta", "FAU_01", OUTCOME_FAIL,
                        anomalies=[ANOM_ADB_UNHEALTHY]))

    r = compute_rollup()
    f0 = r["per_instance"]["FAU_00"]
    assert f0["exec"] == 2
    assert f0["ok"]   == 2
    assert f0["tasks_breakdown"] == {"raccolta": 1, "rifornimento": 1}
    assert f0["anomalies_total"] == 0

    f1 = r["per_instance"]["FAU_01"]
    assert f1["exec"]            == 1
    assert f1["fail"]            == 1
    assert f1["anomalies_total"] == 1


# ==============================================================================
# 6. save + load roundtrip
# ==============================================================================

def test_save_and_load_rollup(telemetry_root):
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK, dur=12.5))

    r = compute_and_save_rollup()
    assert r is not None
    assert r["totals"]["events"] == 1

    loaded = load_rollup()
    assert loaded is not None
    assert loaded["date"]            == r["date"]
    assert loaded["totals"]["events"] == 1
    assert "raccolta" in loaded["per_task"]


# ==============================================================================
# 7. cleanup_old_rollups
# ==============================================================================

def test_cleanup_old_rollups(telemetry_root):
    rdir = telemetry_root / "data" / "telemetry" / "rollup"
    rdir.mkdir(parents=True, exist_ok=True)
    # Crea 2 vecchi e 1 recente
    (rdir / "rollup_2025-01-01.json").write_text("{}")
    (rdir / "rollup_2025-06-15.json").write_text("{}")
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    (rdir / f"rollup_{today}.json").write_text("{}")

    removed = cleanup_old_rollups(retention_days=30)
    assert removed == 2
    assert (rdir / f"rollup_{today}.json").exists()
    assert not (rdir / "rollup_2025-01-01.json").exists()


# ==============================================================================
# 8. Percentile basic sanity
# ==============================================================================

def test_percentile_simple():
    from core.telemetry import _percentile
    assert _percentile([], 50)         == 0.0
    assert _percentile([10], 50)       == 10.0
    assert _percentile([1,2,3,4,5], 0) == 1.0
    assert _percentile([1,2,3,4,5], 100) == 5.0
    assert _percentile([1,2,3,4,5], 50) == 3.0
    # p95 di 100 elementi 0..99 → ~94
    p95 = _percentile(list(range(100)), 95)
    assert 93 < p95 < 96


# ==============================================================================
# 9. Live writer (Step 5) — compute_live_24h + save_live + writer loop
# ==============================================================================

def test_compute_live_24h_empty(telemetry_root):
    from core.telemetry import compute_live_24h
    r = compute_live_24h()
    assert "window_start" in r
    assert "window_end" in r
    assert r["totals"]["events"] == 0


def test_compute_live_24h_filters_by_window(telemetry_root):
    from core.telemetry import compute_live_24h
    # Eventi correnti
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK))
    record(_make_event("raccolta", "FAU_01", OUTCOME_OK))

    # Evento "vecchio" simulato — manipolo direttamente events file
    from core.telemetry import _events_dir, _today_utc_str
    from datetime import datetime, timezone, timedelta
    import json
    old_path = _events_dir() / f"events_{_today_utc_str()}.jsonl"
    with open(old_path, "a", encoding="utf-8") as f:
        # ts_start 25 ore fa → fuori finestra 24h
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        f.write(json.dumps({
            "event_id": "OLD12345", "ts_start": old_ts, "ts_end": old_ts,
            "duration_s": 1.0, "task": "old_raccolta", "instance": "FAU_OLD",
            "cycle": 0, "success": True, "outcome": "ok", "msg": "",
            "output": {}, "anomalies": [], "retry_count": 0,
        }) + "\n")

    r = compute_live_24h()
    assert r["totals"]["events"] == 2  # solo i 2 nuovi, l'old è fuori finestra
    assert "raccolta" in r["per_task"]
    assert "old_raccolta" not in r["per_task"]


def test_save_and_load_live(telemetry_root):
    from core.telemetry import compute_and_save_live, load_live
    record(_make_event("raccolta", "FAU_00", OUTCOME_OK, dur=5.0))
    live = compute_and_save_live()
    assert live is not None
    loaded = load_live()
    assert loaded["totals"]["events"] == 1
    assert "window_start" in loaded
    assert "raccolta" in loaded["per_task"]


def test_live_writer_loop_runs_and_stops(telemetry_root):
    """Il loop scrive almeno una volta poi si ferma quando stop_event è set."""
    import threading, time as _time
    from core.telemetry import live_writer_loop, load_live

    record(_make_event("raccolta", "FAU_00", OUTCOME_OK, dur=2.0))

    stop = threading.Event()
    th = threading.Thread(target=live_writer_loop, args=(stop, 0.2), daemon=True)
    th.start()

    # Aspetta la prima scrittura (immediata all'avvio)
    _time.sleep(0.1)
    live = load_live()
    assert live is not None
    assert live["totals"]["events"] == 1

    stop.set()
    th.join(timeout=2)
    assert not th.is_alive()


# ==============================================================================
# 10. Anomaly pattern detector (Step 8)
# ==============================================================================

def _ev_with_ts(task, instance, outcome, ts_start_iso,
                anomalies=None, output=None, dur=1.0):
    e = TaskTelemetry.start(task=task, instance=instance, cycle=1)
    e.ts_start = ts_start_iso
    e.ts_end = ts_start_iso  # forzato uguale per semplicità
    e.duration_s = float(dur)
    e.success = outcome in (OUTCOME_OK, OUTCOME_SKIP)
    e.outcome = outcome
    e.anomalies = list(anomalies or [])
    e.output = dict(output or {})
    return e


def test_detect_adb_cascade_high_severity():
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev_with_ts("raccolta", "FAU_00", OUTCOME_ABORT,
                    (base + timedelta(seconds=i*30)).isoformat(),
                    anomalies=[ANOM_ADB_UNHEALTHY])
        for i in range(5)
    ]
    patterns = detect_anomaly_patterns(events)
    assert len(patterns["adb_cascade"]) == 1
    cascade = patterns["adb_cascade"][0]
    assert cascade["instance"] == "FAU_00"
    assert cascade["count"]    == 5
    assert cascade["severity"] == "high"


def test_detect_adb_cascade_no_match_below_threshold():
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)
    # solo 2 eventi → < soglia 3
    events = [
        _ev_with_ts("raccolta", "FAU_00", OUTCOME_ABORT,
                    (base + timedelta(seconds=i*30)).isoformat(),
                    anomalies=[ANOM_ADB_UNHEALTHY])
        for i in range(2)
    ]
    patterns = detect_anomaly_patterns(events)
    assert patterns["adb_cascade"] == []


def test_detect_rifornimento_skip_chain():
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev_with_ts("rifornimento", "FAU_00", OUTCOME_SKIP,
                    (base + timedelta(seconds=i*100)).isoformat())
        for i in range(4)
    ]
    patterns = detect_anomaly_patterns(events)
    assert len(patterns["rifornimento_skip_chain"]) == 1
    chain = patterns["rifornimento_skip_chain"][0]
    assert chain["count"] == 4
    assert chain["instance"] == "FAU_00"


def test_detect_rifornimento_skip_chain_breaks_on_success():
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)
    # 2 skip, 1 ok, 2 skip → no chain (max 2 consecutivi)
    outcomes = [OUTCOME_SKIP, OUTCOME_SKIP, OUTCOME_OK, OUTCOME_SKIP, OUTCOME_SKIP]
    events = [
        _ev_with_ts("rifornimento", "FAU_00", o,
                    (base + timedelta(seconds=i*100)).isoformat())
        for i, o in enumerate(outcomes)
    ]
    patterns = detect_anomaly_patterns(events)
    assert patterns["rifornimento_skip_chain"] == []


def test_detect_task_timeout_recurring():
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)
    # 5 eventi normali (50s ciascuno) + 3 outliers (300s)
    events = []
    for i in range(5):
        events.append(_ev_with_ts(
            "raccolta", f"FAU_0{i}", OUTCOME_OK,
            (base + timedelta(seconds=i*60)).isoformat(), dur=50.0))
    for i in range(3):
        events.append(_ev_with_ts(
            "raccolta", f"FAU_1{i}", OUTCOME_OK,
            (base + timedelta(minutes=i*10)).isoformat(), dur=300.0))
    patterns = detect_anomaly_patterns(events)
    assert len(patterns["task_timeout_recurring"]) == 1
    rec = patterns["task_timeout_recurring"][0]
    assert rec["task"] == "raccolta"
    assert rec["count"] == 3
    assert rec["max_observed_s"] == 300.0


def test_detect_no_pattern_on_empty_events():
    from core.telemetry import detect_anomaly_patterns
    p = detect_anomaly_patterns([])
    assert p["adb_cascade"]             == []
    assert p["rifornimento_skip_chain"] == []
    assert p["task_timeout_recurring"]  == []
    assert p["home_stab_loop"]          == []


def test_patterns_detected_in_rollup(telemetry_root):
    """patterns_detected è populato in compute_rollup output."""
    from core.telemetry import detect_anomaly_patterns
    from datetime import datetime, timezone, timedelta
    base = datetime.now(timezone.utc)
    # ADB cascade per FAU_00
    for i in range(3):
        ev = _ev_with_ts("raccolta", "FAU_00", OUTCOME_ABORT,
                          (base + timedelta(seconds=i*60)).isoformat(),
                          anomalies=[ANOM_ADB_UNHEALTHY])
        record(ev)

    r = compute_rollup()
    assert "patterns_detected" in r
    assert len(r["patterns_detected"]["adb_cascade"]) == 1
