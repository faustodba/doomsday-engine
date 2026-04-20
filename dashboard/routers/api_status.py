# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_status.py
#
#  Endpoint status + storico eventi.
#  Prefix: /api
# ==============================================================================

from fastapi import APIRouter

from dashboard.models import EngineStatus
from dashboard.services.stats_reader import get_engine_status

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=EngineStatus)
def status():
    """Snapshot live engine_status.json. Polling ogni 5s dalla UI."""
    return get_engine_status()


@router.get("/status/storico")
def storico(n: int = 50):
    from dashboard.services.stats_reader import get_storico
    return get_storico(n)
