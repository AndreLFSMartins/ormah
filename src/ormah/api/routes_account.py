"""Local admin routes for account-linked hosted billing handoffs.

Handlers here are thin wrappers over ``ormah.cloud.billing``: they authenticate
the local request against the signed-in account, validate input, delegate, and
translate stable billing reason codes into HTTP status codes. No remote request
is constructed in this module, and each route only creates a short-lived hosted
handoff — never a backup or verification run.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from ormah.cloud.billing import (
    BillingError,
    BillingErrorCode,
    get_offer,
    open_portal,
    start_checkout,
    validate_protection_intent_id,
)

router = APIRouter(prefix="/admin/account", tags=["account"])

_ERROR_STATUS: dict[BillingErrorCode, int] = {
    BillingErrorCode.SIGN_IN_REQUIRED: 401,
    BillingErrorCode.ACCOUNT_FORBIDDEN: 403,
    BillingErrorCode.INVALID_REQUEST: 400,
    BillingErrorCode.NOT_FOUND: 404,
    BillingErrorCode.CONFLICT: 409,
    BillingErrorCode.RATE_LIMITED: 429,
    BillingErrorCode.CLOUD_UNREACHABLE: 503,
    BillingErrorCode.BILLING_UNAVAILABLE: 502,
}


class CheckoutRequest(BaseModel):
    """The only accepted Checkout input: which protection intent to pay for."""

    model_config = ConfigDict(extra="forbid")

    protection_intent_id: str

    @field_validator("protection_intent_id")
    @classmethod
    def _canonical_uuid(cls, value: str) -> str:
        return validate_protection_intent_id(value)


class PortalRequest(BaseModel):
    """Portal sessions take no client input: no customer, no return URL."""

    model_config = ConfigDict(extra="forbid")


def _settings(request: Request):
    return request.app.state.engine.settings


def _cloud_client(request: Request):
    """Injection seam for tests and the desktop shell.

    Production leaves this unset, and the billing adapter builds its own
    short-lived authenticated client from settings.
    """
    return getattr(request.app.state, "cloud_client", None)


def _http_error(exc: BillingError) -> HTTPException:
    """Map a stable billing reason code onto a local HTTP error."""
    return HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, 502),
        detail={"error": exc.code.value, "message": str(exc)},
    )


@router.get("/offer")
def account_offer(request: Request):
    """Return the hosted plan offer for the signed-in account.

    Carries no hosted URL, price ID, or customer ID.
    """
    try:
        offer = get_offer(_settings(request), client=_cloud_client(request))
    except BillingError as exc:
        raise _http_error(exc) from exc
    return offer.to_payload()


@router.post("/checkout")
def account_checkout(body: CheckoutRequest, request: Request):
    """Create a hosted Checkout handoff for one protection intent."""
    try:
        handoff = start_checkout(
            _settings(request),
            body.protection_intent_id,
            client=_cloud_client(request),
        )
    except BillingError as exc:
        raise _http_error(exc) from exc
    return handoff.to_payload()


@router.post("/portal")
def account_portal(request: Request, body: PortalRequest | None = None):
    """Create a hosted billing-portal handoff for the signed-in account."""
    try:
        handoff = open_portal(_settings(request), client=_cloud_client(request))
    except BillingError as exc:
        raise _http_error(exc) from exc
    return handoff.to_payload()
