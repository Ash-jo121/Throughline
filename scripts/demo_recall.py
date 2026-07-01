from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.memory import recall_related, remember_incident, reset_memory
from throughline.seed import HERO_QUERY, PAST_INCIDENTS


async def main() -> None:
    await reset_memory()
    for incident in PAST_INCIDENTS:
        await remember_incident(incident)

    answer = await recall_related(HERO_QUERY)
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
