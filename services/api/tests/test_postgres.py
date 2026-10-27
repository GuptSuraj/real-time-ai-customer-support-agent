"""Real row-lock tests, enabled in CI or with POSTGRES_TEST_URL pointing to a disposable database."""

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from support_api.db import Base
from support_api.domain import confirm_action
from support_api.models import Call, PendingAction, Ticket, Verification
from support_api.seed import seed


@pytest.fixture()
def postgres():
    url = os.getenv("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_URL not set; row-lock test requires PostgreSQL")
    admin = create_engine(url)
    schema = "support_test_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)
        call = Call(customer_id="cust-aarav", room="concurrency-room", status="active")
        db.add(call)
        db.flush()
        action = PendingAction(
            call_id=call.id,
            kind="ticket",
            payload={"title": "Concurrency issue", "description": "Create exactly one ticket"},
            expires_at=time.time() + 300,
        )
        db.add(action)
        db.add(
            Verification(
                call_id=call.id,
                code_hash="used",
                expires_at=time.time() + 300,
                consumed=True,
                verified_until=time.time() + 300,
            )
        )
        db.commit()
        ids = call.id, action.id
    yield factory, ids
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_concurrent_confirmations_commit_once(postgres):
    factory, (call_id, action_id) = postgres
    barrier = Barrier(2)

    def execute():
        with factory() as db:
            barrier.wait()
            call = db.scalar(select(Call).where(Call.id == call_id).with_for_update())
            result = confirm_action(db, call, action_id, "user-aarav")
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert results[0] == results[1]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Ticket).where(Ticket.call_id == call_id)) == 1
