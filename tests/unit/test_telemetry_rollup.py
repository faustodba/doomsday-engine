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
