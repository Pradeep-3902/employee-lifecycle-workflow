
"""Append-only workflow audit events."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def record_event(
    connection,
    employee_id: str | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> str:
    """
    Append an audit event and return its unique ID.

    The event sequence is allocated atomically by SQLite. This function
    deliberately does not commit; transaction ownership remains with the
    calling service.
    """
    required_values = {
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }

    for field_name, value in required_values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    event_day = date.today()
    event_date = event_day.isoformat()
    sequence_date = event_day.strftime("%Y%m%d")

    allocated = connection.execute(
        """
        INSERT INTO audit_event_sequences (event_date, last_sequence)
        VALUES (?, 1)
        ON CONFLICT(event_date)
        DO UPDATE SET last_sequence = last_sequence + 1
        RETURNING last_sequence
        """,
        (sequence_date,),
    ).fetchone()

    if allocated is None:
        raise RuntimeError("Unable to allocate an audit event sequence")

    event_id = f"AUD-{sequence_date}-{allocated['last_sequence']:06d}"

    connection.execute(
        """
        INSERT INTO audit_events (
            audit_event_id,
            employee_id,
            event_type,
            event_date,
            entity_type,
            entity_id,
            old_value,
            new_value
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            employee_id,
            event_type,
            event_date,
            entity_type,
            entity_id,
            old_value,
            new_value,
        ),
    )

    return event_id
