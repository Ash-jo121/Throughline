from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.config import BRIEF_DB_PATH
from throughline.memory import remember_incident, reset_memory
from throughline.seed import INCOMING_TICKET, PAST_INCIDENTS
from throughline.service import build_incident_brief, remember_ticket_background


NO_MATCH_TICKET = {
    "id": "JIRA-9001",
    "date": "2026-07-05",
    "raw_customer": "soylent",
    "component": "DataExportService",
    "summary": "CSV exports stall before completion for large accounts.",
    "sentry_error": {
        "error_class": "ExportWorkerTimeout",
        "service": "export-worker",
    },
}


async def main() -> None:
    if BRIEF_DB_PATH.exists():
        BRIEF_DB_PATH.unlink()
        print(f"removed {BRIEF_DB_PATH}")

    await reset_memory()
    for incident in PAST_INCIDENTS:
        print(f"remembering {incident['id']} ({incident['component']})")
        await remember_incident(incident)

    for ticket in (INCOMING_TICKET, NO_MATCH_TICKET):
        print(f"generating brief for {ticket['id']} ({ticket['component']})")
        brief = await build_incident_brief(ticket)
        await remember_ticket_background(ticket)
        print(
            f"created {brief.incident_ref}: {brief.confidence}, match={brief.matched_incident_id}"
        )

    print("demo reset complete")


if __name__ == "__main__":
    asyncio.run(main())
