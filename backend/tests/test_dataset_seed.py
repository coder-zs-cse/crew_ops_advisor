"""Seeded dataset generation — no network, writes into a temp dir."""

from __future__ import annotations

from pathlib import Path

from app.core.dataset import REQUIRED_FILES, dataset_ready, ensure_dataset
from app.core.dataset_generate import generate_dataset
from app.core.dataset_validate import validate_dataset


def test_generate_and_validate_seed_writes_a_complete_snapshot(tmp_path: Path) -> None:
    dest = tmp_path / "data-seed-42"
    generate_dataset(42, dest)
    assert dataset_ready(dest)
    for name in REQUIRED_FILES:
        assert (dest / name).stat().st_size > 0
    errors = validate_dataset(dest)
    assert errors == []
    manifest = (dest / "manifest.json").read_text(encoding="utf-8")
    assert '"seed": 42' in manifest


def test_ensure_dataset_is_idempotent(tmp_path: Path) -> None:
    dest = tmp_path / "data-seed-7"
    first = ensure_dataset(seed=7, dest=dest)
    stamp = (first / "flights.json").stat().st_mtime
    second = ensure_dataset(seed=7, dest=dest)
    assert second == first
    assert (second / "flights.json").stat().st_mtime == stamp
