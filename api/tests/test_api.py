import pytest
from fastapi.testclient import TestClient

from app.events import LoggingPublisher
from app.main import app, get_publisher, get_store
from app.store import InMemoryStore

TORONTO = {"city": "Toronto", "country": "CA", "latitude": 43.6532, "longitude": -79.3832}
LONDON = {"city": "London", "country": "GB", "latitude": 51.5072, "longitude": -0.1276}

@pytest.fixture
def publisher() -> LoggingPublisher:
    return LoggingPublisher()

@pytest.fixture
def client(publisher: LoggingPublisher):
    store = InMemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_publisher] = lambda: publisher
    yield TestClient(app)
    app.dependency_overrides.clear()

def txn(amount=100, location=TORONTO, timestamp="2026-10-08T12:00:00Z", txn_type="withdrawal"):
    return {
        "account_id": "acc-1",
        "amount": amount,
        "transaction_type": txn_type,
        "location": location,
        "timestamp": timestamp,
    }

def test_normal_transaction_is_approved(client, publisher):
    res = client.post("/transactions", json=txn())
    assert res.status_code == 201
    assert res.json()["status"] == "approved"
    assert publisher.published == []


def test_large_withdrawal_is_flagged_and_published(client, publisher):
    res = client.post("/transactions", json=txn(amount=9000))
    body = res.json()
    assert body["status"] == "flagged"
    assert body["reasons"] == ["LARGE_WITHDRAWAL"]
    assert len(publisher.published) == 1
    assert publisher.published[0].transaction_id == body["transaction_id"]

def test_impossible_travel_across_two_requests(client):
    client.post("/transactions", json=txn(timestamp="2026-10-08T12:00:00Z"))
    res = client.post("/transactions", json=txn(location=LONDON, timestamp="2026-10-08T12:10:00Z"))
    assert res.json()["reasons"] == ["IMPOSSIBLE_TRAVEL"]


def test_failed_logins_then_transaction_is_flagged(client):
    for minute in ("01", "02", "03"):
        r = client.post(
            "/login-attempts",
            json={"account_id": "acc-1", "success": False, "timestamp": f"2026-10-08T12:{minute}:00Z"},
        )
        assert r.status_code == 204
    res = client.post("/transactions", json=txn(timestamp="2026-10-08T12:05:00Z"))
    assert res.json()["reasons"] == ["EXCESSIVE_FAILED_LOGINS"]


def test_get_transaction_by_id(client):
    created = client.post("/transactions", json=txn()).json()
    res = client.get(f"/transactions/{created['transaction_id']}")
    assert res.status_code == 200
    assert res.json() == created

def test_unknown_transaction_returns_404(client):
    assert client.get("/transactions/does-not-exist").status_code == 404

@pytest.mark.parametrize(
    "bad",
    [
        txn(amount=-5),
        txn(timestamp="2026-10-08T12:00:00"),
        txn(txn_type="refund"),
    ],
)
def test_invalid_input_returns_422(client, bad):
    assert client.post("/transactions", json=bad).status_code == 422