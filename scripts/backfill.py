from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.memory import remember_incident, reset_memory
from throughline.seed import PAST_INCIDENTS


async def main() -> None:
    await reset_memory()
    for incident in PAST_INCIDENTS:
        print(f"remembering {incident['id']} ({incident['component']})")
        await remember_incident(incident)
    print(f"backfilled {len(PAST_INCIDENTS)} incidents")


if __name__ == "__main__":
    asyncio.run(main())
