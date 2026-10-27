"""Local demo faults are one-shot, persisted, and disabled by default."""

import time
from sqlalchemy import select
from .models import Audit


def consume(db, call_id):
    fault = db.scalar(
        select(Audit)
        .where(
            Audit.call_id == call_id, Audit.event == "fault_requested", Audit.created_at > time.time() - 120
        )
        .order_by(Audit.created_at)
        .with_for_update()
    )
    if not fault:
        return None
    fault.event = "fault_consumed"
    db.commit()
    return fault.details.get("fault")
