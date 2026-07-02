from __future__ import annotations

import os

import pytest

from throughline.memory import recall_related, remember_incident, reset_memory
from throughline.seed import HERO_QUERY, PAST_INCIDENTS


@pytest.mark.asyncio
async def test_recall_returns_paymentservice_backoff_fix() -> None:
    if not os.getenv("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY is required for live Cognee recall")

    await reset_memory()
    for incident in PAST_INCIDENTS:
        await remember_incident(incident)

    answer = await recall_related(HERO_QUERY)
    normalized = answer.lower()

    assert any(token in normalized for token in ("1290", "backoff", "inc-2024-11")), answer
