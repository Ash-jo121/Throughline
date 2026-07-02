from __future__ import annotations

import pytest

from throughline.memory import recall_related, remember_incident, require_llm_key, reset_memory
from throughline.seed import HERO_QUERY, PAST_INCIDENTS


@pytest.mark.asyncio
async def test_recall_returns_paymentservice_backoff_fix() -> None:
    require_llm_key()
    await reset_memory()
    for incident in PAST_INCIDENTS:
        await remember_incident(incident)

    answer = await recall_related(HERO_QUERY)
    normalized = answer.lower()

    assert any(token in normalized for token in ("1290", "backoff", "inc-2024-11")), answer
