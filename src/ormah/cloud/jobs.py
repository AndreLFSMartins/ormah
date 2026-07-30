"""Guarded scheduler adapters for shared cloud protection operations."""

from __future__ import annotations

import logging

from ormah.cloud.protection import CloudProtectionService
from ormah.cloud.state import ProtectionOperationPhase


logger = logging.getLogger(__name__)


def run_cloud_backup(engine) -> str | None:
    """Run one scheduled backup, swallowing every exception at the scheduler boundary."""

    try:
        result = CloudProtectionService.from_engine(engine).backup_now(
            reason="cloud", only_if_due=True
        )
        if result.phase is ProtectionOperationPhase.COMPLETED:
            return result.snapshot_id
    except Exception as exc:
        logger.warning("Scheduled Ormah Cloud backup failed with %s", type(exc).__name__)
    return None


def run_restore_verification(engine) -> bool:
    """Run weekly verification, swallowing every exception at the scheduler boundary."""

    try:
        if not engine.settings.cloud_backup_enabled:
            logger.debug("Ormah Cloud restore verification is disabled")
            return False
        result = CloudProtectionService.from_engine(engine).verify_now()
        return result.phase is ProtectionOperationPhase.COMPLETED
    except Exception as exc:
        logger.warning(
            "Scheduled Ormah Cloud restore verification failed with %s", type(exc).__name__
        )
        return False
