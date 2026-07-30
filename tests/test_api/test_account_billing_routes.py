"""Tests for local account-linked billing handoffs."""

from __future__ import annotations

import inspect
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ormah.api import routes_account
from ormah.api.routes_account import router as account_router
from ormah.cloud import billing
from ormah.cloud.client import CloudError
from ormah.config import Settings
from ormah.engine.memory_engine import MemoryEngine

INTENT_ID = "3f1a6c4e-4b0a-4d5f-9a2b-8c7d6e5f4a3b"
CHECKOUT_URL = "https://checkout.stripe.com/c/session-abc123"
PORTAL_URL = "https://billing.stripe.com/p/portal-abc123"
EXPIRES_AT = 4_000_000_000

SECRETS = {
    "price_id": "price_1SecretPriceId",
    "stripe_customer_id": "cus_1SecretCustomerId",
    "secret_key": "sk_live_1SecretKey",
    "token": "account-bearer-token-value",
    "presigned_url": "https://blobs.example.com/store?signature=leak",
}

OFFER_PAYLOAD = {
    "name": "Ormah Protection",
    "unit_amount": 500,
    "currency": "usd",
    "interval": "month",
    "interval_count": 1,
    **SECRETS,
}


class FakeCloudClient:
    def __init__(self, *, offer=None, checkout=None, portal=None, error=None):
        self._results = {
            "get_billing_offer": offer,
            "create_checkout_session": checkout,
            "create_portal_session": portal,
        }
        self._error = error
        self.calls: list[tuple] = []
        self.closed = False

    def _respond(self, name: str, *args):
        self.calls.append((name, *args))
        if self._error is not None:
            raise self._error
        return self._results[name]

    def get_billing_offer(self):
        return self._respond("get_billing_offer")

    def create_checkout_session(self, protection_intent_id):
        return self._respond("create_checkout_session", protection_intent_id)

    def create_portal_session(self):
        return self._respond("create_portal_session")

    def close(self):
        self.closed = True


def build_client(tmp_memory_dir, *, account_token="local-account-token", cloud_client=None):
    settings = Settings(memory_dir=tmp_memory_dir, account_token=account_token)
    engine = MemoryEngine(settings)
    engine.startup()
    test_app = FastAPI()
    test_app.include_router(account_router)
    test_app.state.engine = engine
    if cloud_client is not None:
        test_app.state.cloud_client = cloud_client
    return engine, test_app


@pytest.fixture
def fake_client():
    return FakeCloudClient(
        offer=dict(OFFER_PAYLOAD),
        checkout={
            "status": "checkout_required",
            "url": CHECKOUT_URL,
            "expires_at": EXPIRES_AT,
        },
        portal={"url": PORTAL_URL},
    )


@pytest.fixture
def client(tmp_memory_dir, fake_client):
    engine, test_app = build_client(tmp_memory_dir, cloud_client=fake_client)
    with TestClient(test_app) as http:
        yield http
    engine.shutdown()


def test_routes_require_a_signed_in_account(tmp_memory_dir, fake_client):
    engine, test_app = build_client(tmp_memory_dir, account_token=None, cloud_client=fake_client)
    with TestClient(test_app) as http:
        responses = [
            http.get("/admin/account/offer"),
            http.post(
                "/admin/account/checkout",
                json={"protection_intent_id": INTENT_ID},
            ),
            http.post("/admin/account/portal"),
        ]
    engine.shutdown()

    assert {response.status_code for response in responses} == {401}
    assert all(response.json()["detail"]["error"] == "sign_in_required" for response in responses)
    assert fake_client.calls == []


def test_offer_returns_only_service_contract_fields(client, fake_client):
    response = client.get("/admin/account/offer")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Ormah Protection",
        "unit_amount": 500,
        "currency": "usd",
        "interval": "month",
        "interval_count": 1,
    }
    assert fake_client.calls == [("get_billing_offer",)]
    assert not any(value in response.text for value in SECRETS.values())


def test_checkout_returns_validated_hosted_handoff(client, fake_client):
    response = client.post("/admin/account/checkout", json={"protection_intent_id": INTENT_ID})

    assert response.status_code == 200
    assert response.json() == {
        "status": "checkout_required",
        "url": CHECKOUT_URL,
        "expires_at": EXPIRES_AT,
    }
    assert fake_client.calls == [("create_checkout_session", INTENT_ID)]


@pytest.mark.parametrize("status", ["already_subscribed", "subscription_pending"])
def test_checkout_non_handoff_statuses_drop_urls(tmp_memory_dir, status):
    fake = FakeCloudClient(
        checkout={"status": status, "url": CHECKOUT_URL, "expires_at": EXPIRES_AT}
    )
    engine, test_app = build_client(tmp_memory_dir, cloud_client=fake)
    with TestClient(test_app) as http:
        response = http.post("/admin/account/checkout", json={"protection_intent_id": INTENT_ID})
    engine.shutdown()

    assert response.json() == {"status": status}
    assert CHECKOUT_URL not in response.text


@pytest.mark.parametrize(
    "intent_id",
    [
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",
        "3f1a6c4e4b0a4d5f9a2b8c7d6e5f4a3b",
        "urn:uuid:3f1a6c4e-4b0a-4d5f-9a2b-8c7d6e5f4a3b",
        12345,
    ],
)
def test_checkout_rejects_noncanonical_uuid4(client, fake_client, intent_id):
    response = client.post("/admin/account/checkout", json={"protection_intent_id": intent_id})

    assert response.status_code == 422
    assert fake_client.calls == []


def test_checkout_rejects_client_controlled_fields(client, fake_client):
    response = client.post(
        "/admin/account/checkout",
        json={
            "protection_intent_id": INTENT_ID,
            "return_url": "https://evil.example.com",
        },
    )

    assert response.status_code == 422
    assert fake_client.calls == []


def test_checkout_never_logs_hosted_url(client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = client.post("/admin/account/checkout", json={"protection_intent_id": INTENT_ID})

    assert response.status_code == 200
    assert CHECKOUT_URL not in caplog.text


def test_portal_returns_hosted_handoff(client, fake_client):
    response = client.post("/admin/account/portal")

    assert response.status_code == 200
    assert response.json() == {"url": PORTAL_URL}
    assert fake_client.calls == [("create_portal_session",)]


def test_portal_rejects_client_controlled_fields(client, fake_client):
    for body in (
        {"return_url": "https://evil.example.com"},
        {"customer_id": "cus_123"},
    ):
        assert client.post("/admin/account/portal", json=body).status_code == 422
    assert fake_client.calls == []


@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_error"),
    [
        (None, 503, "cloud_unreachable"),
        (400, 400, "invalid_request"),
        (401, 401, "sign_in_required"),
        (403, 403, "account_forbidden"),
        (404, 404, "not_found"),
        (409, 409, "conflict"),
        (422, 400, "invalid_request"),
        (429, 429, "rate_limited"),
        (200, 502, "billing_unavailable"),
        (503, 502, "billing_unavailable"),
    ],
)
def test_cloud_errors_map_to_static_local_errors(
    tmp_memory_dir, status_code, expected_status, expected_error
):
    error = CloudError(
        "server leaked sk_live_secret",
        status_code=status_code,
        payload={"token": SECRETS["token"]},
    )
    fake = FakeCloudClient(error=error)
    engine, test_app = build_client(tmp_memory_dir, cloud_client=fake)
    with TestClient(test_app) as http:
        response = http.get("/admin/account/offer")
    engine.shutdown()

    assert response.status_code == expected_status
    assert response.json()["detail"]["error"] == expected_error
    assert "sk_live_secret" not in response.text
    assert SECRETS["token"] not in response.text


@pytest.mark.parametrize(
    ("method", "result"),
    [
        ("offer", {}),
        ("checkout", {"status": "checkout_required"}),
        ("portal", {}),
    ],
)
def test_injected_client_contract_violations_fail_closed(tmp_memory_dir, method, result):
    fake = FakeCloudClient(
        offer=result if method == "offer" else None,
        checkout=result if method == "checkout" else None,
        portal=result if method == "portal" else None,
    )
    engine, test_app = build_client(tmp_memory_dir, cloud_client=fake)
    with TestClient(test_app) as http:
        if method == "offer":
            response = http.get("/admin/account/offer")
        elif method == "checkout":
            response = http.post(
                "/admin/account/checkout",
                json={"protection_intent_id": INTENT_ID},
            )
        else:
            response = http.post("/admin/account/portal")
    engine.shutdown()

    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "billing_unavailable"


def test_handlers_are_thin_local_adapters():
    source = inspect.getsource(routes_account)

    for forbidden in (
        "httpx",
        "https://",
        "Bearer",
        "run_cloud_backup",
        "run_restore_verification",
    ):
        assert forbidden not in source


def test_owned_client_is_closed(tmp_memory_dir, monkeypatch):
    built: list[FakeCloudClient] = []

    def fake_factory(settings):
        fake = FakeCloudClient(offer=dict(OFFER_PAYLOAD))
        built.append(fake)
        return fake

    monkeypatch.setattr(billing, "client_from_settings", fake_factory)
    engine, test_app = build_client(tmp_memory_dir)
    with TestClient(test_app) as http:
        response = http.get("/admin/account/offer")
    engine.shutdown()

    assert response.status_code == 200
    assert len(built) == 1
    assert built[0].closed is True


def test_route_payloads_never_include_account_or_provider_secrets(client):
    bodies = [
        client.get("/admin/account/offer").text,
        client.post("/admin/account/checkout", json={"protection_intent_id": INTENT_ID}).text,
        client.post("/admin/account/portal").text,
    ]

    for body in bodies:
        payload = json.loads(body)
        assert not any(value in body for value in SECRETS.values())
        assert set(payload) <= {
            "name",
            "unit_amount",
            "currency",
            "interval",
            "interval_count",
            "status",
            "url",
            "expires_at",
        }
