"""Shared LLM adapter error types."""


class LlmCancelledError(Exception):
    """The call was cancelled by the host (shutdown/stop), not by the provider.

    Says NOTHING about the payload being processed: callers must treat it like any
    other transient provider failure and never count it against per-slice budgets.
    """


class LlmTimeoutError(Exception):
    """The provider call exceeded its time budget.

    Distinct from a fast failure (missing binary, connection refused). Raised by the
    claude_cli adapter; classification lives with the ingest path (ADR-0004 slice 3).
    """
