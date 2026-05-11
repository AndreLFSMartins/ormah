"""Shared wording for the agent-backed maintenance whisper signal."""

MAINTENANCE_DUE_MARKER = "maintenance_due"
MAINTENANCE_DUE_SIGNAL = (
    "maintenance_due: run the ormah-maintenance agent in the background; "
    "continue the conversation without blocking the user."
)


def is_maintenance_due_signal(line: str) -> bool:
    """Return true for the current signal line and the legacy bare marker."""
    stripped = line.strip()
    return stripped in {MAINTENANCE_DUE_MARKER, MAINTENANCE_DUE_SIGNAL}
