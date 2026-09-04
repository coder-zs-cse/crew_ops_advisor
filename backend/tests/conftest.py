import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DATA_DIR = str(BACKEND / "data")


@pytest.fixture(scope="session")
def data_dir() -> str:
    return DATA_DIR


@pytest.fixture(scope="session")
def world():
    from app.core.loader import load_world

    return load_world(DATA_DIR)
