from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.memory import recall_related


async def main() -> None:
    try:
        component = sys.argv[1] if len(sys.argv) > 1 else "CampaignScheduler"
        query = (
            f"List every ticket or incident in Component {component}. "
            "Include Jira keys, incident ids, customers, error classes, and whether a known fix exists."
        )
        answer = await recall_related(query, session_id=f"probe_component_{uuid4()}")
        sys.stdout.buffer.write(answer.text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    finally:
        await _close_cognee_telemetry_session()


async def _close_cognee_telemetry_session() -> None:
    try:
        from cognee.shared import utils

        session = getattr(utils, "_telemetry_session", None)
        if session is not None and not session.closed:
            await session.close()
            utils._telemetry_session = None
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
