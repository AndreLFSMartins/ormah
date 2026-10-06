"""Shared account-linked billing handoffs for local Ormah callers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import logging
from pathlib import Path
from typing import Any, Callable, NoReturn
import uuid

from ormah.cloud.client import CloudClient, CloudError, client_from_settings
from ormah.cloud.keys import STORE_ID_NAME, get_or_create_store_id
from ormah.cloud.state import (
    CloudState,
    CloudStateError,
    ProtectionIntentStatus,
    load_state,
    mutate_state,
)

logger = logging.getLogger(__name__)


class BillingErrorCode(StrEnum):
    """Stable failures exposed to CLI, REST, and desktop callers."""

    SIGN_IN_REQUIRED = "sign_in_required"
    ACCOUNT_FORBIDDEN = "account_forbidden"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    CLOUD_UNREACHABLE = "cloud_unreachable"
    BILLING_UNAVAILABLE = "billing_unavailable"
    STATE_UNAVAILABLE = "state_unavailable"


_ERROR_MESSAGES = {
    BillingErrorCode.SIGN_IN_REQUIRED: "Sign in to your Ormah account first.",
    BillingErrorCode.ACCOUNT_FORBIDDEN: "This Ormah account may not manage billing.",
    BillingErrorCode.INVALID_REQUEST: "Ormah Cloud rejected the billing request.",
    BillingErrorCode.NOT_FOUND: "Ormah Cloud has no such billing resource.",
    BillingErrorCode.CONFLICT: "This billing request conflicts with the account's current state.",
    BillingErrorCode.RATE_LIMITED: "Too many billing requests; try again shortly.",
    BillingErrorCode.CLOUD_UNREACHABLE: "Could not reach Ormah Cloud.",
    BillingErrorCode.BILLING_UNAVAILABLE: "Ormah Cloud billing is unavailable right now.",
    BillingErrorCode.STATE_UNAVAILABLE: "Local protection state is unavailable right now.",
}

_STATUS_ERROR_CODES = {
    400: BillingErrorCode.INVALID_REQUEST,
    401: BillingErrorCode.SIGN_IN_REQUIRED,
    403: BillingErrorCode.ACCOUNT_FORBIDDEN,
    404: BillingErrorCode.NOT_FOUND,
    409: BillingErrorCode.CONFLICT,
    422: BillingErrorCode.INVALID_REQUEST,
    429: BillingErrorCode.RATE_LIMITED,
}


class BillingError(RuntimeError):
    def __init__(self, code: BillingErrorCode) -> None:
        super().__init__(_ERROR_MESSAGES[code])
        self.code = code


class CheckoutStatus(StrEnum):
    CHECKOUT_REQUIRED = "checkout_required"
    ALREADY_SUBSCRIBED = "already_subscribed"
    SUBSCRIPTION_PENDING = "subscription_pending"


@dataclass(frozen=True)
class BillingOffer:
    """Display-safe fields returned by the configured Stripe Price."""

    name: str
    unit_amount: int
    currency: str
    interval: str
    interval_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit_amount": self.unit_amount,
            "currency": self.currency,
            "interval": self.interval,
            "interval_count": self.interval_count,
        }


@dataclass(frozen=True)
class CheckoutHandoff:
    status: CheckoutStatus
    url: str | None = None
    expires_at: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status.value}
        if self.url is not None:
            payload["url"] = self.url
            payload["expires_at"] = self.expires_at
        return payload


@dataclass(frozen=True)
class PortalHandoff:
    url: str

    def to_payload(self) -> dict[str, str]:
        return {"url": self.url}


def _canonical_uuid4(value: Any, message: str, *, require_canonical: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(message)
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(message) from exc
    if (
        parsed.version != 4
        or parsed.variant != uuid.RFC_4122
        or (require_canonical and str(parsed) != value)
    ):
        raise ValueError(message)
    return str(parsed)


def validate_protection_intent_id(value: Any) -> str:
    """Accept only the canonical dashed UUIDv4 used by durable protection state."""
    return _canonical_uuid4(
        value,
        "protection_intent_id must be a canonical UUIDv4 string",
        require_canonical=True,
    )


def _canonical_account_id(value: Any) -> str:
    """Validate the opaque account identifier returned by authenticated cloud metadata."""
    try:
        return _canonical_uuid4(
            value,
            "account_id must be a UUIDv4 string",
            require_canonical=False,
        )
    except ValueError:
        raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE) from None


def _map_cloud_error(exc: CloudError) -> BillingError:
    if exc.status_code is None:
        return BillingError(BillingErrorCode.CLOUD_UNREACHABLE)
    return BillingError(
        _STATUS_ERROR_CODES.get(exc.status_code, BillingErrorCode.BILLING_UNAVAILABLE)
    )


def _require_account(settings) -> None:
    token = getattr(settings, "account_token", None)
    if not isinstance(token, str) or not token.strip():
        raise BillingError(BillingErrorCode.SIGN_IN_REQUIRED)


def _invoke(
    settings,
    client: CloudClient | None,
    operation: Callable[[CloudClient], dict[str, Any]],
) -> dict[str, Any]:
    _require_account(settings)
    owned_client = client is None
    client = client or client_from_settings(settings)
    try:
        payload = operation(client)
    except CloudError as exc:
        raise _map_cloud_error(exc) from exc
    finally:
        if owned_client:
            client.close()
    if not isinstance(payload, dict):
        raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE)
    return payload


def _pending_checkout_state(
    settings,
    protection_intent_id: str,
    *,
    state_dir: Path | None,
) -> tuple[str, CloudState]:
    """Load and validate the store-bound half of a durable Checkout intent."""
    memory_dir = Path(settings.memory_dir).expanduser()
    if not (memory_dir / STORE_ID_NAME).is_file():
        _raise_state_unavailable(FileNotFoundError())
    try:
        store_id = get_or_create_store_id(memory_dir)
        state = load_state(store_id, state_dir=state_dir)
    except (OSError, ValueError, CloudStateError) as exc:
        _raise_state_unavailable(exc)

    _validate_pending_checkout(state, protection_intent_id, store_id)
    return store_id, state


def _raise_state_unavailable(exc: BaseException) -> NoReturn:
    logger.warning(
        "Durable protection state is unavailable; error_type=%s",
        type(exc).__name__,
    )
    raise BillingError(BillingErrorCode.STATE_UNAVAILABLE) from None


def _validate_pending_checkout(
    state: CloudState,
    protection_intent_id: str,
    store_id: str,
    *,
    account_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    if (
        state.pending_protection_intent_id != protection_intent_id
        or state.pending_protection_store_id != store_id
        or state.pending_protection_account_id is None
        or state.pending_protection_created_at is None
        or state.pending_protection_expires_at is None
        or state.pending_protection_expires_at <= now
        or state.pending_protection_status
        not in {
            ProtectionIntentStatus.ACCOUNT_BOUND,
            ProtectionIntentStatus.CHECKOUT_PENDING,
        }
    ):
        raise BillingError(BillingErrorCode.CONFLICT)

    try:
        stored_account_id = _canonical_uuid4(
            state.pending_protection_account_id,
            "pending account binding must be a UUIDv4 string",
            require_canonical=False,
        )
    except ValueError as exc:
        _raise_state_unavailable(exc)
    if account_id is not None and stored_account_id != account_id:
        raise BillingError(BillingErrorCode.CONFLICT)


def _mark_checkout_pending(
    settings,
    store_id: str,
    protection_intent_id: str,
    account_id: str,
    *,
    state_dir: Path | None,
) -> CloudState:
    """Atomically revalidate and reserve this durable intent for Checkout."""

    def transition(state: CloudState) -> CloudState:
        _validate_pending_checkout(
            state,
            protection_intent_id,
            store_id,
            account_id=account_id,
        )
        return replace(
            state,
            pending_protection_account_id=account_id,
            pending_protection_status=ProtectionIntentStatus.CHECKOUT_PENDING,
        )

    try:
        return mutate_state(
            store_id,
            transition,
            memory_dir=Path(settings.memory_dir),
            state_dir=state_dir,
        )
    except BillingError:
        raise
    except (OSError, ValueError, CloudStateError, TimeoutError) as exc:
        _raise_state_unavailable(exc)


def get_offer(settings, *, client: CloudClient | None = None) -> BillingOffer:
    """Return the authenticated account's configured subscription offer."""

    payload = _invoke(settings, client, lambda cloud: cloud.get_billing_offer())
    try:
        offer = BillingOffer(
            name=payload["name"],
            unit_amount=payload["unit_amount"],
            currency=payload["currency"],
            interval=payload["interval"],
            interval_count=payload["interval_count"],
        )
    except (KeyError, TypeError):
        raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE) from None
    logger.debug("Ormah Cloud billing offer read")
    return offer


def start_checkout(
    settings,
    protection_intent_id: str,
    *,
    client: CloudClient | None = None,
    state_dir: Path | None = None,
) -> CheckoutHandoff:
    """Create or resume Checkout for one durable protection intent."""

    try:
        intent_id = validate_protection_intent_id(protection_intent_id)
    except ValueError:
        raise BillingError(BillingErrorCode.INVALID_REQUEST) from None
    _require_account(settings)
    store_id, _ = _pending_checkout_state(settings, intent_id, state_dir=state_dir)

    def create_for_bound_account(cloud: CloudClient) -> dict[str, Any]:
        entitlements = cloud.get_entitlements()
        if not isinstance(entitlements, dict):
            raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE)
        account_id = _canonical_account_id(entitlements.get("account_id"))
        _mark_checkout_pending(
            settings,
            store_id,
            intent_id,
            account_id,
            state_dir=state_dir,
        )
        return cloud.create_checkout_session(intent_id)

    payload = _invoke(settings, client, create_for_bound_account)
    try:
        status = CheckoutStatus(payload["status"])
        if status is CheckoutStatus.CHECKOUT_REQUIRED:
            handoff = CheckoutHandoff(
                status=status,
                url=payload["url"],
                expires_at=payload["expires_at"],
            )
        else:
            handoff = CheckoutHandoff(status=status)
    except (KeyError, TypeError, ValueError):
        raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE) from None
    logger.debug("Ormah Cloud checkout handoff: status=%s", handoff.status.value)
    return handoff


def open_portal(settings, *, client: CloudClient | None = None) -> PortalHandoff:
    """Create a Stripe Customer Portal handoff for the signed-in account."""

    payload = _invoke(settings, client, lambda cloud: cloud.create_portal_session())
    try:
        handoff = PortalHandoff(url=payload["url"])
    except (KeyError, TypeError):
        raise BillingError(BillingErrorCode.BILLING_UNAVAILABLE) from None
    logger.debug("Ormah Cloud billing portal handoff created")
    return handoff
