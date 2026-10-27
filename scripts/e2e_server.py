"""Test-only ASGI entrypoint. Never used by Docker or the regular API entrypoint."""

import time
import uvicorn
from support_api import main
from support_api.db import Base, SessionLocal, engine
from support_api.models import Escalation, PendingAction
from support_api.seed import seed

# This disposable test database deliberately has a separate, fixed /tmp path.
assert engine.url.database == "/tmp/northstar-e2e.db"
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
with SessionLocal() as db:
    seed(db)


async def dispatch(call):
    with SessionLocal() as db:
        db.add(
            PendingAction(
                call_id=call.id,
                kind="refund",
                payload={"order_id": "ORD-1007", "reason": "Returned headphones received"},
                expires_at=time.time() + 300,
            )
        )
        db.add(
            Escalation(call_id=call.id, reason="Customer needs a representative", deadline=time.time() + 300)
        )
        db.commit()


main.lk.dispatch = dispatch
main.lk.join_token = lambda *args: "e2e-invalid-token-no-media"

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=8001)
