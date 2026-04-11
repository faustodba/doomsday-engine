# tests/tasks/conftest.py
#
# Patch globali per velocizzare i test dei task async (step 11-17).
# asyncio.sleep nei task store, vip, boost, alleanza, messaggi viene
# azzerato per evitare attese reali nei test unitari.

import asyncio
from unittest.mock import patch, AsyncMock
import pytest


@pytest.fixture(autouse=True)
def patch_asyncio_sleep():
    """
    Patcha asyncio.sleep in tutti i moduli task per azzerare le attese.
    Autouse=True → applicato a tutti i test nella cartella tasks/.
    """
    async def _instant_sleep(_duration=0):
        pass

    patches = [
        patch("tasks.store.asyncio.sleep",        side_effect=_instant_sleep),
        patch("tasks.boost.asyncio.sleep",         side_effect=_instant_sleep),
        patch("tasks.vip.asyncio.sleep",           side_effect=_instant_sleep),
        patch("tasks.alleanza.asyncio.sleep",      side_effect=_instant_sleep),
        patch("tasks.messaggi.asyncio.sleep",      side_effect=_instant_sleep),
        patch("tasks.arena.asyncio.sleep",         side_effect=_instant_sleep),
        patch("tasks.arena_mercato.asyncio.sleep", side_effect=_instant_sleep),
    ]

    started = []
    for p in patches:
        try:
            started.append(p.start())
        except Exception:
            pass

    yield

    for p in patches:
        try:
            p.stop()
        except Exception:
            pass
