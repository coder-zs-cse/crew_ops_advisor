"""Resolve, generate, and validate the seeded dataset directory.

The world the advisor sees is a JSON snapshot. ``CREWOPS_DATA_SEED`` picks
which snapshot: ``data/data-seed-{n}/``. If that folder is missing or empty,
the generator fills it on startup, then the validator checks it is internally
consistent. An explicit ``CREWOPS_DATA_DIR`` still wins and skips generation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .dataset_generate import generate_dataset
from .dataset_validate import validate_dataset

log = logging.getLogger("crewops.dataset")

REQUIRED_FILES = (
    "flights.json",
    "crew.json",
    "rosters.json",
    "duty_clocks.json",
    "reserve_pool.json",
    "certifications.json",
    "rules.json",
    "costs.json",
    "risk_signals.json",
    "scenarios.json",
    "questions.json",
    "held_out_scenarios.json",
)


def seed_data_dir(backend_root: str | Path, seed: int) -> Path:
    return Path(backend_root) / "data" / f"data-seed-{int(seed)}"


def dataset_ready(path: Path) -> bool:
    if not path.is_dir():
        return False
    for name in REQUIRED_FILES:
        file = path / name
        if not file.is_file() or file.stat().st_size == 0:
            return False
    return True


def ensure_dataset(*, seed: int, dest: str | Path) -> Path:
    """Return a complete dataset directory, generating it when empty."""
    dest_path = Path(dest)
    if dataset_ready(dest_path):
        log.info("dataset ready: %s (seed=%s)", dest_path, seed)
        return dest_path

    dest_path.mkdir(parents=True, exist_ok=True)
    log.info("generating dataset seed=%s into %s", seed, dest_path)
    generate_dataset(int(seed), dest_path)

    missing = [name for name in REQUIRED_FILES if not (dest_path / name).is_file()]
    if missing:
        raise RuntimeError(
            f"dataset generation for seed={seed} did not write {missing} into {dest_path}"
        )

    errors = validate_dataset(dest_path)
    if errors:
        preview = "; ".join(errors[:8])
        raise RuntimeError(
            f"generated dataset seed={seed} failed validation ({len(errors)} error(s)): {preview}"
        )

    log.info("dataset generated and validated: %s", dest_path)
    return dest_path
