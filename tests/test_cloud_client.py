from __future__ import annotations

import stat
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
import respx

from ormah.cloud.client import (
    CloudClient,
    CloudError,
    client_from_settings,
    get_or_create_device_id,
)

BASE_URL = "https://cloud.test"
TOKEN = "opaque-account-token"


@respx.mock
def test_auth_and_entitlement_requests_match_service_shapes():
    request_route = respx.post(f"{BASE_URL}/auth/request-code").mock(
        return_value=httpx.Response(202, json={"message": "sent"})
    )
    verify_route = respx.post(f"{BASE_URL}/auth/verify").mock(
        return_value=httpx.Response(200, json={"token": TOKEN, "token_type": "bearer"})
    )
    entitlement_route = respx.get(f"{BASE_URL}/me/entitlements").mock(
        return_value=httpx.Response(
            200,
            json={"backup": True, "founding": False, "plan_status": "active"},
        )
    )
    device_id = str(uuid.uuid4())

    with CloudClient(BASE_URL) as client:
        client.request_code("Person@Example.com")
        assert client.verify_code("Person@Example.com", "123456", device_id, "Test laptop") == TOKEN
        assert client.get_entitlements()["plan_status"] == "active"

    assert request_route.calls[0].request.content == b'{"email":"person@example.com"}'
    assert "authorization" not in request_route.calls[0].request.headers
    assert b'"device_id"' in verify_route.calls[0].request.content
    assert "authorization" not in verify_route.calls[0].request.headers
    assert entitlement_route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"


@respx.mock
def test_revoke_resolves_server_token_id_from_device():
    device_id = str(uuid.uuid4())
    respx.get(f"{BASE_URL}/me/tokens").mock(
        return_value=httpx.Response(
            200,
            json={
                "tokens": [
                    {
                        "token_id": "server-side-hmac-id",
                        "device_id": device_id,
                        "device_name": "Laptop",
                    }
                ]
            },
        )
    )
    revoke_route = respx.post(f"{BASE_URL}/me/tokens/revoke").mock(
        return_value=httpx.Response(200, json={"revoked": True})
    )

    with CloudClient(BASE_URL, TOKEN, device_id=device_id) as client:
        assert client.revoke_token() == {"revoked": True}

    assert revoke_route.calls[0].request.content == b'{"token_id":"server-side-hmac-id"}'
    assert TOKEN.encode() not in revoke_route.calls[0].request.content


@respx.mock
def test_upload_blob_and_head_methods_match_service_shapes():
    store_id = str(uuid.uuid4())
    protocol_route = respx.get(f"{BASE_URL}/protocol").mock(
        return_value=httpx.Response(
            200,
            json={
                "protocol_version": 2,
                "capabilities": ["immutable-promotion"],
                "max_ciphertext_bytes": 1024,
            },
        )
    )
    create_route = respx.post(f"{BASE_URL}/stores/{store_id}/uploads").mock(
        return_value=httpx.Response(
            201,
            json={"upload_id": "upload", "snapshot_id": "snapshot", "put_url": "https://put"},
        )
    )
    finalize_route = respx.post(f"{BASE_URL}/stores/{store_id}/uploads/upload/finalize").mock(
        return_value=httpx.Response(
            200,
            json={
                "snapshot_id": "snapshot",
                "status": "committed",
                "head": {"snapshot_id": "snapshot", "seq": 4},
            },
        )
    )
    respx.get(f"{BASE_URL}/stores/{store_id}/blobs").mock(
        return_value=httpx.Response(200, json={"blobs": [{"snapshot_id": "snapshot"}]})
    )
    download_route = respx.post(f"{BASE_URL}/stores/{store_id}/presign-download").mock(
        return_value=httpx.Response(200, json={"get_url": "https://get"})
    )
    respx.get(f"{BASE_URL}/stores/{store_id}/head").mock(
        return_value=httpx.Response(200, json={"snapshot_id": "snapshot", "seq": 4})
    )

    with CloudClient(BASE_URL, TOKEN) as client:
        client.create_upload(store_id, 42, "a" * 64)
        client.finalize_upload(store_id, "upload", {"expected_seq": 3})
        assert client.list_blobs(store_id)["blobs"][0]["snapshot_id"] == "snapshot"
        assert client.presign_download(store_id, "snapshot") == {"get_url": "https://get"}
        assert client.get_head(store_id) == {"snapshot_id": "snapshot", "seq": 4}

    assert create_route.calls[0].request.content == (
        b'{"size_bytes":42,"sha256":"' + b"a" * 64 + b'"}'
    )
    assert create_route.calls[0].request.headers["x-ormah-client-version"]
    assert uuid.UUID(create_route.calls[0].request.headers["x-request-id"])
    assert protocol_route.call_count == 1
    assert finalize_route.calls[0].request.content == b'{"advance_head":{"expected_seq":3}}'
    assert download_route.calls[0].request.content == b'{"snapshot_id":"snapshot"}'


@respx.mock
def test_finalize_cas_conflict_returns_current_head_payload():
    store_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/stores/{store_id}/uploads/upload/finalize").mock(
        return_value=httpx.Response(
            409,
            json={
                "detail": {
                    "message": "Sync head changed.",
                    "snapshot_id": "loser",
                    "status": "committed",
                    "head": {"snapshot_id": "winner", "seq": 2},
                }
            },
        )
    )

    with CloudClient(BASE_URL, TOKEN) as client:
        result = client.finalize_upload(store_id, "upload", {"expected_seq": 1})

    assert result["status"] == "committed"
    assert result["head"] == {"snapshot_id": "winner", "seq": 2}


@pytest.mark.parametrize("status_code", [401, 403, 500])
@respx.mock
def test_non_success_responses_raise_cloud_error(status_code):
    respx.get(f"{BASE_URL}/me/entitlements").mock(
        return_value=httpx.Response(status_code, json={"detail": "denied"})
    )

    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError) as exc_info:
            client.get_entitlements()

    assert exc_info.value.status_code == status_code
    assert TOKEN not in str(exc_info.value)


@respx.mock
def test_non_cas_conflict_still_raises():
    store_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/stores/{store_id}/uploads/upload/finalize").mock(
        return_value=httpx.Response(409, json={"detail": "Uploaded object is not available."})
    )

    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="not available"):
            client.finalize_upload(store_id, "upload")


@respx.mock
def test_upload_fails_closed_without_immutable_protocol():
    respx.get(f"{BASE_URL}/protocol").mock(
        return_value=httpx.Response(
            200,
            json={
                "protocol_version": 1,
                "capabilities": [],
                "max_ciphertext_bytes": 1024,
            },
        )
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="immutable"):
            client.create_upload(str(uuid.uuid4()), 42, "a" * 64)


@respx.mock
def test_upload_rejects_bundle_above_negotiated_limit_before_reservation():
    respx.get(f"{BASE_URL}/protocol").mock(
        return_value=httpx.Response(
            200,
            json={
                "protocol_version": 2,
                "capabilities": ["immutable-promotion"],
                "max_ciphertext_bytes": 10,
            },
        )
    )
    create = respx.post(f"{BASE_URL}/stores/{uuid.uuid4()}/uploads")
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="processing limit"):
            client.create_upload(str(uuid.uuid4()), 11, "a" * 64)
    assert not create.called


@respx.mock
def test_network_errors_are_wrapped():
    respx.get(f"{BASE_URL}/me/entitlements").mock(side_effect=httpx.ConnectError("offline"))
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="Could not reach"):
            client.get_entitlements()


@respx.mock
def test_read_processing_limit_falls_back_offline_but_write_does_not():
    respx.get(f"{BASE_URL}/protocol").mock(side_effect=httpx.ConnectError("offline"))
    with CloudClient(BASE_URL, TOKEN) as client:
        assert client.processing_limit(require_hardened_write=False) == 512 * 1024 * 1024
        with pytest.raises(CloudError, match="Could not reach"):
            client.processing_limit(require_hardened_write=True)


def test_device_id_is_stable_uuid4_and_mode_0600(tmp_path):
    path = tmp_path / "device_id"
    first = get_or_create_device_id(path)
    second = get_or_create_device_id(path)

    assert first == second
    assert uuid.UUID(first).version == 4
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_corrupt_device_id_fails_closed(tmp_path):
    path = tmp_path / "device_id"
    path.write_text("not-a-uuid\n")

    with pytest.raises(CloudError, match="expected UUIDv4"):
        get_or_create_device_id(path)


@respx.mock
def test_get_billing_offer_returns_safe_display_metadata():
    respx.get(f"{BASE_URL}/billing/offer").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Ormah Protection",
                "unit_amount": 900,
                "currency": "USD",
                "interval": "month",
                "interval_count": 1,
                "stripe_price_id": "price_internal_do_not_expose",
            },
        )
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        offer = client.get_billing_offer()

    assert offer == {
        "name": "Ormah Protection",
        "unit_amount": 900,
        "currency": "usd",
        "interval": "month",
        "interval_count": 1,
    }
    assert "stripe_price_id" not in offer


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "name": "",
            "unit_amount": 900,
            "currency": "usd",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": "900",
            "currency": "usd",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": -1,
            "currency": "usd",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": True,
            "currency": "usd",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": 900,
            "currency": "us",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": 900,
            "currency": "u\u0455d",
            "interval": "month",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": 900,
            "currency": "usd",
            "interval": "fortnight",
            "interval_count": 1,
        },
        {
            "name": "Ormah",
            "unit_amount": 900,
            "currency": "usd",
            "interval": "month",
            "interval_count": 0,
        },
    ],
)
@respx.mock
def test_get_billing_offer_fails_closed_on_malformed_payload(payload):
    respx.get(f"{BASE_URL}/billing/offer").mock(return_value=httpx.Response(200, json=payload))
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="billing offer"):
            client.get_billing_offer()


@respx.mock
def test_create_checkout_session_sends_only_intent_id():
    intent_id = str(uuid.uuid4())
    expires_at = int(time.time()) + 3600
    route = respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "checkout_required",
                "url": "https://checkout.stripe.com/c/pay/cs_test_abc",
                "expires_at": expires_at,
            },
        )
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        result = client.create_checkout_session(intent_id)

    assert result == {
        "status": "checkout_required",
        "url": "https://checkout.stripe.com/c/pay/cs_test_abc",
        "expires_at": expires_at,
    }
    assert route.calls[0].request.content == (
        b'{"protection_intent_id":"' + intent_id.encode() + b'"}'
    )


@respx.mock
def test_create_checkout_session_rejects_non_uuid_intent():
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="protection_intent_id") as exc_info:
            client.create_checkout_session("not-a-uuid")
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("status", ["already_subscribed", "subscription_pending"])
@respx.mock
def test_create_checkout_session_handles_non_checkout_statuses(status):
    intent_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(200, json={"status": status})
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        result = client.create_checkout_session(intent_id)

    assert result == {"status": status}
    assert "url" not in result
    assert "expires_at" not in result


@respx.mock
def test_create_checkout_session_rejects_unrecognized_status():
    intent_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(200, json={"status": "mystery_status"})
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="checkout status"):
            client.create_checkout_session(intent_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "checkout_required"},
        {"status": "checkout_required", "url": "https://checkout.stripe.com/c/x"},
        {"status": "checkout_required", "expires_at": 4_000_000_000},
        {
            "status": "checkout_required",
            "url": "https://checkout.stripe.com/c/x",
            "expires_at": "not-a-timestamp",
        },
        {
            "status": "checkout_required",
            "url": "https://checkout.stripe.com/c/x",
            "expires_at": 0,
        },
    ],
)
@respx.mock
def test_create_checkout_session_fails_closed_on_malformed_checkout_required(payload):
    intent_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError):
            client.create_checkout_session(intent_id)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://checkout.stripe.com/c/pay/cs_test",
        "https://checkout.stripe.com:8443/c/pay/cs_test",
        "https://evilcheckout.stripe.com/c/pay/cs_test",
        "https://checkout.stripe.com.evil.com/c/pay/cs_test",
        "https://attacker@checkout.stripe.com/c/pay/cs_test",
        "https://@checkout.stripe.com/c/pay/cs_test",
        "https://:@checkout.stripe.com/c/pay/cs_test",
        "https://user:pass@checkout.stripe.com/c/pay/cs_test",
        "https://checkout.stripe.com/c/pay/cs_test\x00ignored",
        "https://checkout.stripe.com/c/pay/cs_test\u200b",
        "https://checkout.stripe.com/c/pay/cs_tést",
        "https://checkout.stripe.com",
        "https://billing.stripe.com/c/pay/cs_test",
        "https://[invalid/c/pay/cs_test",
        "not-a-url",
        "",
    ],
)
@respx.mock
def test_create_checkout_session_rejects_unsafe_checkout_urls(bad_url):
    intent_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "checkout_required",
                "url": bad_url,
                "expires_at": int(time.time()) + 3600,
            },
        )
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="billing URL"):
            client.create_checkout_session(intent_id)


@respx.mock
def test_create_checkout_session_propagates_rate_limit():
    intent_id = str(uuid.uuid4())
    respx.post(f"{BASE_URL}/billing/checkout-session").mock(
        return_value=httpx.Response(
            429,
            json={"detail": "billing_rate_limited"},
        )
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="billing_rate_limited") as exc_info:
            client.create_checkout_session(intent_id)

    assert exc_info.value.status_code == 429


@respx.mock
def test_create_portal_session_returns_validated_url():
    route = respx.post(f"{BASE_URL}/billing/portal-session").mock(
        return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/session/xyz"})
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        result = client.create_portal_session()

    assert result == {"url": "https://billing.stripe.com/session/xyz"}
    assert route.calls[0].request.content == b""


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://billing.stripe.com/session/xyz",
        "https://billing.stripe.com:8443/session/xyz",
        "https://evilbilling.stripe.com/session/xyz",
        "https://billing.stripe.com.evil.com/session/xyz",
        "https://@billing.stripe.com/session/xyz",
        "https://user:pass@billing.stripe.com/session/xyz",
        "https://billing.stripe.com/session/xyz\x1f",
        "https://billing.stripe.com/session/xyz\u2060",
        "https://checkout.stripe.com/session/xyz",
        None,
        123,
    ],
)
@respx.mock
def test_create_portal_session_rejects_unsafe_urls(bad_url):
    respx.post(f"{BASE_URL}/billing/portal-session").mock(
        return_value=httpx.Response(200, json={"url": bad_url})
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="billing URL"):
            client.create_portal_session()


@respx.mock
def test_create_portal_session_propagates_rate_limit():
    respx.post(f"{BASE_URL}/billing/portal-session").mock(
        return_value=httpx.Response(429, json={"detail": "billing_rate_limited"})
    )
    with CloudClient(BASE_URL, TOKEN) as client:
        with pytest.raises(CloudError, match="billing_rate_limited") as exc_info:
            client.create_portal_session()

    assert exc_info.value.status_code == 429


def test_client_factory_reads_settings():
    client = client_from_settings(SimpleNamespace(cloud_api_url=BASE_URL, account_token=TOKEN))
    try:
        assert client.base_url == f"{BASE_URL}/"
        assert client.token == TOKEN
    finally:
        client.close()
