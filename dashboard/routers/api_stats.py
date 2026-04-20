# ==============================================================================
#  DOOMSDAY ENGINE V6 — dashboard/routers/api_stats.py
#
#  Endpoint statistiche per istanza.
#  Prefix: /api/stats
# ==============================================================================

from fastapi import APIRouter, HTTPException

from dashboard.models import InstanceStats
from dashboard.services.stats_reader import get_instance_stats, get_all_stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/", response_model=list[InstanceStats])
def all_stats():
    """Statistiche aggregate tutte le istanze."""
    return get_all_stats()


@router.get("/{nome}", response_model=InstanceStats)
def instance_stats(nome: str):
    """Statistiche per singola istanza."""
    s = get_instance_stats(nome)
    if s.stato_live == "unknown" and not s.ultimo_tick.task_eseguiti:
        # Non distinguiamo "non trovata" da "nessun dato" — restituiamo
        # comunque il modello default, la UI mostra "nessun dato"
        pass
    return s
