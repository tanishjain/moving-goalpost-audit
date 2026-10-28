import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "code" / "src", ROOT / "code" / "scripts" / "validation", ROOT / "reproduce", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "reproduction_output")


@pytest.fixture()
def snapshot_copy(tmp_path):
    """A throwaway copy of the snapshot for tamper tests; the distributed files are never modified."""
    dst = tmp_path / "snapshot"
    shutil.copytree(ROOT, dst, ignore=IGNORE)
    return dst
