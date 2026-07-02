from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from throughline.config import COGNEE_ROOT, DATASET_NAME
from throughline.memory import (
    cognee,
    recall_related,
    remember_incident,
    remember_ticket,
    reset_memory,
)
from throughline.seed import COMPONENT_PROBE_QUERY, INCOMING_TICKET, PAST_INCIDENTS


async def main() -> None:
    await reset_memory()
    for incident in PAST_INCIDENTS:
        await remember_incident(incident)
    await remember_ticket(INCOMING_TICKET)

    inventory = await cognee.get_schema_inventory(samples_per_type=25)
    answer = await recall_related(COMPONENT_PROBE_QUERY)

    component_samples = _samples_for_type(inventory, "Component")
    paymentservice_count = sum(1 for sample in component_samples if sample == "PaymentService")

    print("Schema inventory:")
    print(json.dumps(inventory, indent=2))
    print("\nPaymentService component sample count:", paymentservice_count)
    print("\nPaymentService incident probe answer:")
    print(answer)

    destination = COGNEE_ROOT / "throughline_graph.html"
    await cognee.visualize_graph(
        destination_file_path=str(destination),
        include_session_events=False,
        dataset=DATASET_NAME,
    )
    print(f"\nGraph visualization written to {destination}")

    normalized = answer.lower()
    failures = []
    if paymentservice_count != 1:
        failures.append(
            f"expected one PaymentService component sample, found {paymentservice_count}"
        )
    if "inc-2024-11" not in normalized:
        failures.append("PaymentService probe did not return INC-2024-11")
    if "inc-2025-03" in normalized or "inc-2025-07" in normalized:
        failures.append("PaymentService probe returned an incident from another component")

    if failures:
        raise SystemExit("Graph probe failed: " + "; ".join(failures))

    print("\nGraph probe passed: PaymentService is behaving as the shared pivot.")


def _samples_for_type(inventory: list[dict], type_name: str) -> list[str]:
    for item in inventory:
        if item.get("type") == type_name:
            return list(item.get("samples", []))
    return []


if __name__ == "__main__":
    asyncio.run(main())
