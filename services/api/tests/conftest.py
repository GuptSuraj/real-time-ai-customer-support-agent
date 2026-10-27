import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SESSION_SECRET"] = "test-secret-at-least-32-characters-long"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from support_api import main
from support_api.db import Base, get_db
from support_api.seed import seed


@pytest.fixture()
def harness(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)

    def db_override():
        with factory() as db:
            yield db

    main.app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(main, "SessionLocal", factory)
    main.login_attempts.clear()

    async def dispatch(_):
        return None

    monkeypatch.setattr(main.lk, "dispatch", dispatch)
    monkeypatch.setattr(main.lk, "join_token", lambda *args: "test-room-token")

    async def noop(*args):
        return None

    monkeypatch.setattr(main.lk, "delete_room", noop)
    with TestClient(main.app) as client:
        yield client, factory
    main.app.dependency_overrides.clear()
    engine.dispose()


def sign_in(client, email="aarav@example.com"):
    response = client.post("/auth/login", json={"email": email, "password": "Demo-support-2026!"})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return response.json()["user"]


@pytest.fixture()
def customer(harness):
    client, factory = harness
    sign_in(client)
    return client, factory


@pytest.fixture()
def call(customer):
    client, factory = customer
    result = client.post("/calls", json={"language": "en"})
    assert result.status_code == 200, result.text
    call = result.json()["call"]
    from support_api.models import Call
    from support_api.security import agent_token

    with factory() as db:
        token = agent_token(db.get(Call, call["id"]))
    return client, factory, call, {"Authorization": "Bearer " + token}


def verify(client, call_id):
    challenge = client.post(f"/calls/{call_id}/verification", json={}).json()
    result = client.post(
        f"/calls/{call_id}/verification/complete",
        json={"challenge_id": challenge["challenge_id"], "code": challenge["demo_code"]},
    )
    assert result.status_code == 200, result.text
    return challenge
