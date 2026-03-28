"""Helpers for locating and inspecting the shared Ormah model cache."""

from __future__ import annotations

import os
from pathlib import Path


def get_fastembed_cache_dir() -> Path:
    """Return the effective shared model cache directory."""
    raw = os.environ.get("FASTEMBED_CACHE_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share" / "ormah" / "models"


def get_model_cache_dirname(model_name: str, models: list[dict]) -> str | None:
    """Resolve a fastembed model name to its on-disk cache directory name."""
    for model in models:
        if model.get("model") != model_name:
            continue
        hf_repo = (model.get("sources") or {}).get("hf", "")
        if hf_repo:
            return f"models--{hf_repo.replace('/', '--')}"
        return None
    return None


def is_model_cached(
    model_name: str,
    models: list[dict],
    cache_dir: Path | None = None,
) -> bool:
    """Return True when the model's expected fastembed cache directory exists."""
    dir_name = get_model_cache_dirname(model_name, models)
    if dir_name is None:
        return False
    effective_cache_dir = cache_dir or get_fastembed_cache_dir()
    return (effective_cache_dir / dir_name).exists()
